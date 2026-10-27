import logging
from datetime import date, timedelta
from io import BytesIO
from pathlib import PurePath
from zipfile import ZipFile, BadZipFile
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, or_, update, delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import get_db, now
from .models import User, AuthSession, LoginAttempt, Job, ImportBatch, Student, Resume, Recommendation, Followup, AuditLog
from .schemas import LoginInput, UserInput, UserPatch, JobInput, StudentInput, RecommendationInput, FollowupInput, ResumeApplyInput, AIRecommendationInput
from .resume_cache import extract_resume
from .ocr import status as ocr_status, client as ocr_client
from .ocr_worker import MAX_PIXELS
from PIL import Image, UnidentifiedImageError
from contextlib import asynccontextmanager
from pydantic import ValidationError
from .security import current_user, admin, passwords, DUMMY_HASH, COOKIE, token_hash, new_session, audit, user_dict
from .imports import HEADERS, fingerprint, inspect_xlsx, workbook_bytes, template_bytes
from .body_limit import BodyLimitMiddleware
from .matching import MATCH_LIMIT, match_job
from . import ai_matching
from . import vector_index

@asynccontextmanager
async def lifespan(app):
    vector_index.start()
    yield
    vector_index.stop()
    ocr_client.close()

app = FastAPI(title='知途 · 求职服务工作台', version='0.1.0', lifespan=lifespan)

@app.middleware('http')
async def security_headers(request: Request, call_next):
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and request.headers.get('x-requested-with') != 'career-web':
        return JSONResponse({'detail': '缺少请求校验标识'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse({'detail': [{'loc': e['loc'], 'msg': e['msg']} for e in exc.errors()]}, status_code=422)

app.add_middleware(BodyLimitMiddleware)

def today():
    return (now() + timedelta(hours=8)).date()

def as_dict(obj, exclude=()):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in exclude}

def job_dict(job):
    data = as_dict(job, ('fingerprint',))
    data['effective_status'] = '失效' if job.status == '失效' or (job.expires_on and job.expires_on < today()) else '有效'
    return data

def visible_students(user):
    query = select(Student)
    return query if user.role == 'admin' else query.where(Student.owner_id == user.id)

def student_access(db, user, student_id):
    student = db.scalar(visible_students(user).where(Student.id == student_id))
    if not student:
        raise HTTPException(404, '学员不存在或无权访问')
    return student

def owned_batch(db, user, batch_id):
    batch = db.get(ImportBatch, batch_id)
    if not batch or (batch.user_id != user.id and user.role != 'admin'):
        raise HTTPException(404, '导入批次不存在或无权访问')
    return batch

def batch_dict(batch, with_rows=True):
    data = as_dict(batch, ('rows',))
    data['counts'] = {state: sum(r['state'] == state for r in batch.rows) for state in ('可导入', '错误', '重复', '已导入')}
    data['total'] = len(batch.rows)
    if with_rows:
        data['rows'] = batch.rows
    return data

def valid_job():
    return (Job.status == '有效') & or_(Job.expires_on.is_(None), Job.expires_on >= today())

@app.get('/api/health')
def health(db: Session = Depends(get_db)):
    db.execute(text('SELECT 1'))
    return {'status': 'ok'}

@app.get('/api/ocr/status')
def get_ocr_status(user: User = Depends(current_user)):
    return ocr_status()

@app.get('/api/ai/status')
def ai_status(user: User = Depends(current_user)):
    return {**ai_matching.status(), 'retrieval': vector_index.status()}

@app.post('/api/ai/reindex')
def reindex_jobs(user: User = Depends(admin)):
    return vector_index.sync()

@app.post('/api/auth/login')
def login(data: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    key = token_hash(f'{request.client.host if request.client else "local"}:{data.username.casefold()}')
    attempt = db.get(LoginAttempt, key)
    if attempt and attempt.window_start > now() - timedelta(minutes=15) and attempt.failures >= 5:
        raise HTTPException(429, '登录失败次数过多，请在 15 分钟后重试')
    user = db.scalar(select(User).where(User.username == data.username))
    good = passwords.verify(data.password, user.password_hash if user else DUMMY_HASH)
    if not good or not user or not user.active:
        if not attempt:
            attempt = LoginAttempt(key=key, failures=0, window_start=now())
            db.add(attempt)
        if attempt.window_start < now() - timedelta(minutes=15):
            attempt.failures = 0
            attempt.window_start = now()
        attempt.failures += 1
        db.commit()
        raise HTTPException(401, '账号或密码错误，或账号已停用')
    if attempt:
        db.delete(attempt)
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now()))
    new_session(db, user, response)
    audit(db, user, '登录', 'user', user.id)
    db.commit()
    return user_dict(user)

@app.post('/api/auth/logout')
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        db.commit()
    response.delete_cookie(COOKIE, path='/')
    return {'ok': True}

@app.get('/api/auth/me')
def me(user: User = Depends(current_user)):
    return user_dict(user)

@app.get('/api/users')
def users(user: User = Depends(admin), db: Session = Depends(get_db)):
    return [user_dict(u) for u in db.scalars(select(User).order_by(User.id))]

@app.post('/api/users', status_code=201)
def create_user(data: UserInput, user: User = Depends(admin), db: Session = Depends(get_db)):
    account = User(username=data.username, name=data.name, password_hash=passwords.hash(data.password), role='consultant')
    db.add(account)
    try:
        db.flush()
        audit(db, user, '创建顾问', 'user', account.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '用户名已存在')
    return user_dict(account)

@app.patch('/api/users/{user_id}')
def patch_user(user_id: int, data: UserPatch, user: User = Depends(admin), db: Session = Depends(get_db)):
    account = db.get(User, user_id)
    if not account:
        raise HTTPException(404, '账号不存在')
    if account.role == 'admin':
        raise HTTPException(400, '管理员账号请使用服务端管理命令维护')
    if data.active is not None:
        account.active = data.active
    if data.password:
        account.password_hash = passwords.hash(data.password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == account.id))
    audit(db, user, '更新账号并撤销会话', 'user', account.id)
    db.commit()
    return user_dict(account)

@app.get('/api/dashboard')
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = visible_students(user).with_only_columns(Student.id)
    # Only the newest follow-up on each student is an active reminder.
    latest = select(func.max(Followup.id)).where(Followup.student_id.in_(ids)).group_by(Followup.student_id)
    reminders = db.execute(select(Followup, Student.name).join(Student, Followup.student_id == Student.id).where(Followup.id.in_(latest), Followup.handled_at.is_(None), Followup.next_date <= today(), Student.status == '服务中').order_by(Followup.next_date, Followup.id).limit(20)).all()
    return {
        'jobs': db.scalar(select(func.count()).select_from(Job)),
        'active_jobs': db.scalar(select(func.count()).select_from(Job).where(valid_job())),
        'students': db.scalar(select(func.count()).select_from(Student).where(Student.id.in_(ids))),
        'recommendations': db.scalar(select(func.count()).select_from(Recommendation).where(Recommendation.student_id.in_(ids))),
        'reminders': [{**as_dict(f), 'student_name': name} for f, name in reminders],
    }

@app.get('/api/jobs')
def jobs(q: str = Query('', max_length=200), city: str = '', education: str = '', experience: str = '', status: str = '', salary_min: int | None = Query(None, ge=0), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Job)
    if q:
        query = query.where(or_(*[col.contains(q, autoescape=True) for col in (Job.title, Job.company, Job.major, Job.description)]))
    if city:
        query = query.where(Job.city.contains(city, autoescape=True))
    if education:
        query = query.where(Job.education == education)
    if experience:
        query = query.where(Job.experience == experience)
    if status:
        if status not in ('有效', '失效'):
            raise HTTPException(422, '岗位状态无效')
        query = query.where(valid_job() if status == '有效' else ~valid_job())
    if salary_min is not None:
        query = query.where(or_(Job.salary_max >= salary_min, (Job.salary_max.is_(None)) & (Job.salary_min >= salary_min)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Job.created_at.desc(), Job.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return {'items': [job_dict(j) for j in items], 'total': total}

@app.get('/api/jobs/{job_id}')
def job_detail(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, '岗位不存在')
    return job_dict(job)

@app.put('/api/jobs/{job_id}')
def update_job(job_id: int, data: JobInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, '岗位不存在')
    for key, value in data.model_dump().items():
        setattr(job, key, value)
    job.fingerprint = fingerprint(data.model_dump())
    audit(db, user, '更新岗位', 'job', job_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '已存在同岗位名称、公司和城市的岗位')
    vector_index.notify()
    return job_dict(job)

@app.get('/api/imports/template')
def import_template(user: User = Depends(current_user)):
    return Response(template_bytes(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename="jobs-template.xlsx"'})

@app.get('/api/imports')
def import_history(page: int = Query(1, ge=1), user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(ImportBatch)
    if user.role != 'admin':
        query = query.where(ImportBatch.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    batches = db.scalars(query.order_by(ImportBatch.id.desc()).offset((page - 1) * 20).limit(20))
    return {'items': [batch_dict(b, False) for b in batches], 'total': total}

@app.post('/api/imports/preview', status_code=201)
def preview_import(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith('.xlsx'):
        raise HTTPException(400, '只支持 .xlsx 文件，请使用导入模板')
    content = file.file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, '文件不能超过 10MB')
    try:
        rows = inspect_xlsx(content)
    except HTTPException:
        raise
    except Exception:
        logging.getLogger(__name__).warning('Rejected malformed workbook', exc_info=True)
        raise HTTPException(400, '工作簿内容无法解析，请使用模板重新保存为 .xlsx')
    seen = set()
    for row in rows:
        if row['errors']:
            continue
        fp = fingerprint(row['data'])
        if fp in seen or db.scalar(select(Job.id).where(Job.fingerprint == fp)):
            row.update(state='重复', errors=['同岗位名称、公司和城市已存在，本行将跳过'])
        seen.add(fp)
    filename = file.filename.replace('\\', '/').rsplit('/', 1)[-1][:200]
    batch = ImportBatch(filename=filename, user_id=user.id, rows=rows)
    db.add(batch)
    db.flush()
    audit(db, user, '预览岗位导入', 'import', batch.id)
    db.commit()
    return batch_dict(batch)

@app.get('/api/imports/{batch_id}')
def import_detail(batch_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return batch_dict(owned_batch(db, user, batch_id))

@app.get('/api/imports/{batch_id}/errors')
def import_errors(batch_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    batch = owned_batch(db, user, batch_id)
    rows = [[r['row_number'], *[r['data'].get(k, '') for k in HEADERS.values()], '；'.join(r['errors'])] for r in batch.rows if r['errors']]
    return Response(workbook_bytes(['原始行号', *HEADERS, '原因'], rows), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename="import-errors.xlsx"'})

@app.post('/api/imports/{batch_id}/commit')
def commit_import(batch_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    batch = owned_batch(db, user, batch_id)
    claimed = db.execute(update(ImportBatch).where(ImportBatch.id == batch_id, ImportBatch.status == '待确认').values(status='处理中'))
    if claimed.rowcount != 1:
        raise HTTPException(409, '该批次已完成或已取消，不能再次入库')
    rows = [{**row} for row in batch.rows]
    for row in rows:
        if row['state'] != '可导入':
            continue
        job = JobInput.model_validate(row['data'])
        try:
            with db.begin_nested():
                db.add(Job(**job.model_dump(), fingerprint=fingerprint(row['data']), created_by=user.id))
                db.flush()
            row['state'] = '已导入'
        except IntegrityError:
            row.update(state='重复', errors=['确认时检测到同岗位名称、公司和城市，本行已跳过'])
    batch.rows = rows
    batch.status = '已完成'
    batch.committed_at = now()
    audit(db, user, '确认岗位导入', 'import', batch.id)
    db.commit()
    vector_index.notify()
    return batch_dict(batch)

@app.post('/api/imports/{batch_id}/cancel')
def cancel_import(batch_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    batch = owned_batch(db, user, batch_id)
    claimed = db.execute(update(ImportBatch).where(ImportBatch.id == batch_id, ImportBatch.status == '待确认').values(status='已取消'))
    if claimed.rowcount != 1:
        raise HTTPException(409, '该批次已完成或已取消，不能取消导入')
    audit(db, user, '取消岗位导入', 'import', batch.id)
    db.commit()
    return batch_dict(batch)

@app.get('/api/students')
def students(q: str = Query('', max_length=200), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = visible_students(user)
    if q:
        query = query.where(or_(Student.name.contains(q, autoescape=True), Student.major.contains(q, autoescape=True), Student.school.contains(q, autoescape=True), Student.target_role.contains(q, autoescape=True)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    return {'items': [as_dict(s) for s in db.scalars(query.order_by(Student.id.desc()).offset((page - 1) * page_size).limit(page_size))], 'total': total}

def check_owner(db, user, owner_id):
    if user.role != 'admin' and owner_id != user.id:
        raise HTTPException(403, '只有管理员可以分配学员')
    owner = db.get(User, owner_id)
    if not owner or not owner.active:
        raise HTTPException(400, '负责顾问不存在或已停用')

@app.post('/api/students', status_code=201)
def create_student(data: StudentInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    payload = data.model_dump()
    payload['owner_id'] = data.owner_id or user.id
    check_owner(db, user, payload['owner_id'])
    student = Student(**payload)
    db.add(student)
    db.flush()
    audit(db, user, '创建学员', 'student', student.id)
    db.commit()
    return as_dict(student)

@app.get('/api/students/{student_id}')
def student_detail(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    student = student_access(db, user, student_id)
    resumes = db.scalars(select(Resume).where(Resume.student_id == student_id).order_by(Resume.id.desc()))
    recommendations = db.scalars(select(Recommendation).where(Recommendation.student_id == student_id).order_by(Recommendation.id.desc()))
    followups = db.scalars(select(Followup).where(Followup.student_id == student_id).order_by(Followup.id.desc()))
    return {**as_dict(student), 'resumes': [as_dict(r, ('content', 'extraction_cache', 'extraction_version')) for r in resumes], 'recommendations': [as_dict(r) for r in recommendations], 'followups': [as_dict(f) for f in followups]}

@app.put('/api/students/{student_id}')
def update_student(student_id: int, data: StudentInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    student = student_access(db, user, student_id)
    owner_id = data.owner_id or student.owner_id
    check_owner(db, user, owner_id)
    old_owner_id = student.owner_id
    transferred = owner_id != old_owner_id
    for key, value in data.model_dump(exclude={'owner_id'}).items():
        setattr(student, key, value)
    student.owner_id = owner_id
    audit(db, user, f'转交学员 {old_owner_id} → {owner_id}' if transferred else '更新学员', 'student', student.id)
    db.commit()
    return as_dict(student)

@app.get('/api/students/{student_id}/matched-jobs')
def matched_jobs(student_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    student = student_access(db, user, student_id)
    recommended = select(Recommendation.job_id).where(Recommendation.student_id == student_id)
    query = select(Job).where(valid_job(), ~Job.id.in_(recommended)).order_by(Job.created_at.desc(), Job.id.desc())
    candidates = []
    for job in db.scalars(query):
        match = match_job(student, job)
        if match is not None:
            candidates.append((job, match))
    # Stable sort keeps newest jobs first when evidence is equal.
    candidates.sort(key=lambda item: item[1]['priority'], reverse=True)
    missing = []
    if not student.target_city.strip():
        missing.append('意向城市')
    if not student.target_role.strip():
        missing.append('意向岗位')
    if student.education == '不限':
        missing.append('具体学历')
    if not student.major.strip():
        missing.append('专业（岗位专业不限时仍可匹配）')
    items = [{**job_dict(job), 'reasons': match['reasons'], 'warnings': match['warnings']} for job, match in candidates[:MATCH_LIMIT]]
    return {'items': items, 'total': len(candidates), 'limit': MATCH_LIMIT, 'missing_fields': missing}

@app.post('/api/students/{student_id}/ai-matched-jobs')
def ai_matched_jobs(student_id: int, data: AIRecommendationInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    student = student_access(db, user, student_id)
    resume = db.scalar(select(Resume).where(Resume.id == data.resume_id, Resume.student_id == student_id))
    if not resume:
        raise HTTPException(404, '简历不存在或不属于此学员')
    preference_keys = ('target_city', 'target_role', 'education', 'major')
    original_preferences = tuple(getattr(student, key) for key in preference_keys)
    recommended = select(Recommendation.job_id).where(Recommendation.student_id == student_id)
    jobs = list(db.scalars(select(Job).where(valid_job(), ~Job.id.in_(recommended)).order_by(Job.created_at.desc(), Job.id.desc())))
    initial_jobs = {job.id: ai_matching.job_payload(job) for job in jobs}
    result = ai_matching.generate(student, resume, jobs)
    db.expire_all()
    student = student_access(db, user, student_id)
    if not db.scalar(select(Resume.id).where(Resume.id == data.resume_id, Resume.student_id == student_id)):
        raise HTTPException(409, '分析期间该简历已删除，请选择简历后重新生成')
    if tuple(getattr(student, key) for key in preference_keys) != original_preferences:
        raise HTTPException(409, '分析期间学员意向或资料已修改，请重新生成')
    available = {job.id: job for job in db.scalars(select(Job).where(valid_job(), ~Job.id.in_(recommended)))}
    checked = []
    for item in result['items']:
        job = available.get(item['job_id'])
        if job and ai_matching.job_payload(job) == initial_jobs.get(job.id):
            checked.append({**job_dict(job), **item})
    if len(checked) != len(result['items']):
        result['warnings'].append('分析期间部分岗位已修改、失效或已推荐，已从结果移除。')
    result['items'] = checked
    audit(db, user, 'DeepSeek 简历分析与岗位候选生成', 'resume', data.resume_id)
    db.commit()
    return {**result, 'resume_id': data.resume_id, 'generated_at': now().isoformat(), **ai_matching.status()}

@app.post('/api/students/{student_id}/resumes', status_code=201)
def upload_resume(student_id: int, file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    student_access(db, user, student_id)
    filename = (file.filename or '').replace('\\', '/').rsplit('/', 1)[-1][:200]
    suffix = PurePath(filename).suffix.lower()
    if suffix not in ('.pdf', '.docx', '.jpg', '.jpeg', '.png'):
        raise HTTPException(400, '简历支持 PDF、DOCX、JPG 和 PNG')
    content = file.file.read(5 * 1024 * 1024 + 1)
    if not content or len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, '简历不能为空且不能超过 5MB')
    mime = 'application/pdf'
    if suffix == '.pdf' and not content.startswith(b'%PDF-'):
        raise HTTPException(400, 'PDF 文件格式无效')
    if suffix == '.docx':
        try:
            with ZipFile(BytesIO(content)) as archive:
                if 'word/document.xml' not in archive.namelist() or len(archive.infolist()) > 1000 or sum(i.file_size for i in archive.infolist()) > 30 * 1024 * 1024:
                    raise ValueError()
        except (BadZipFile, ValueError):
            raise HTTPException(400, 'DOCX 文件格式无效或内容过大')
        mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    if suffix in ('.jpg', '.jpeg', '.png'):
        try:
            with Image.open(BytesIO(content)) as image:
                expected = 'PNG' if suffix == '.png' else 'JPEG'
                if image.format != expected or image.width * image.height > MAX_PIXELS or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError()
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise HTTPException(400, '图片格式无效或过大；仅支持单张 JPG/PNG，最多 2,000 万像素')
        mime = 'image/png' if suffix == '.png' else 'image/jpeg'
    resume = Resume(student_id=student_id, filename=filename, content_type=mime, content=content, uploaded_by=user.id)
    db.add(resume)
    db.flush()
    audit(db, user, '上传简历', 'resume', resume.id)
    db.commit()
    result = extract_resume(resume, db)
    return {**as_dict(resume, ('content', 'extraction_cache', 'extraction_version')), 'extraction': result}

@app.get('/api/resumes/{resume_id}/extraction')
def resume_extraction(resume_id: int, refresh: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    resume = db.get(Resume, resume_id)
    if not resume:
        raise HTTPException(404, '简历不存在或无权访问')
    student_access(db, user, resume.student_id)
    audit(db, user, '识别简历基础信息', 'resume', resume.id)
    db.commit()
    return extract_resume(resume, db, refresh=refresh)

@app.post('/api/resumes/{resume_id}/apply')
def apply_resume_fields(resume_id: int, data: ResumeApplyInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    resume = db.get(Resume, resume_id)
    if not resume:
        raise HTTPException(404, '简历不存在或无权访问')
    student = student_access(db, user, resume.student_id)
    values = {c.field: c.value for c in data.changes}
    if len(values) != len(data.changes):
        raise HTTPException(400, '同一字段不能重复提交')
    payload = {key: getattr(student, key) for key in StudentInput.model_fields}
    try:
        validated = StudentInput.model_validate({**payload, **values})
    except ValidationError:
        raise HTTPException(422, '确认字段的内容或长度不符合学员资料要求，请检查后重试')
    condition = [Student.id == student.id, Student.owner_id == student.owner_id]
    condition.extend(getattr(Student, change.field) == change.expected for change in data.changes)
    applied = db.execute(update(Student).where(*condition).values(**{key: getattr(validated, key) for key in values}))
    if applied.rowcount != 1:
        raise HTTPException(409, '学员资料已被修改，请关闭识别窗口、刷新档案后重新识别并确认')
    audit(db, user, '确认简历信息填补', 'resume', resume.id)
    db.commit()
    return as_dict(student)

@app.get('/api/resumes/{resume_id}/download')
def download_resume(resume_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from urllib.parse import quote
    resume = db.get(Resume, resume_id)
    if not resume:
        raise HTTPException(404, '简历不存在或无权访问')
    student_access(db, user, resume.student_id)
    audit(db, user, '下载简历', 'resume', resume.id)
    db.commit()
    return Response(resume.content, media_type=resume.content_type, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(resume.filename, safe='')}"})

@app.delete('/api/resumes/{resume_id}', status_code=204)
def delete_resume(resume_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    resume = db.get(Resume, resume_id)
    if not resume:
        raise HTTPException(404, '简历不存在或无权访问')
    student_access(db, user, resume.student_id)
    # Recheck ownership in the delete statement in case the student was reassigned.
    allowed_ids = visible_students(user).with_only_columns(Student.id)
    removed = db.execute(delete(Resume).where(Resume.id == resume_id, Resume.student_id.in_(allowed_ids)))
    if removed.rowcount != 1:
        raise HTTPException(404, '简历不存在或无权访问')
    audit(db, user, '删除简历及识别缓存', 'resume', resume_id)
    db.commit()
    return Response(status_code=204)

@app.post('/api/students/{student_id}/recommendations', status_code=201)
def recommend(student_id: int, data: RecommendationInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    student_access(db, user, student_id)
    job = db.get(Job, data.job_id)
    if not job or job_dict(job)['effective_status'] != '有效':
        raise HTTPException(400, '岗位不存在或已失效')
    existing = db.scalar(select(Recommendation).where(Recommendation.student_id == student_id, Recommendation.job_id == job.id))
    if existing:
        raise HTTPException(409, '该岗位已推荐给此学员')
    snapshot = {k: v for k, v in job_dict(job).items() if k not in ('created_at', 'expires_on')}
    snapshot['expires_on'] = job.expires_on.isoformat() if job.expires_on else None
    item = Recommendation(student_id=student_id, job_id=job.id, snapshot=snapshot, created_by=user.id)
    db.add(item)
    try:
        db.flush()
        audit(db, user, '推荐岗位', 'recommendation', item.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '该岗位已推荐给此学员')
    return as_dict(item)

@app.delete('/api/students/{student_id}/recommendations/{recommendation_id}', status_code=204)
def cancel_recommendation(student_id: int, recommendation_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    student_access(db, user, student_id)
    recommendation = db.scalar(select(Recommendation).where(Recommendation.id == recommendation_id, Recommendation.student_id == student_id).with_for_update())
    if not recommendation:
        raise HTTPException(404, '推荐记录不存在或不属于此学员')
    # Keep communication history and reminder dates when removing its job association.
    db.execute(update(Followup).where(Followup.recommendation_id == recommendation_id).values(recommendation_id=None))
    audit(db, user, f'取消岗位推荐（学员#{student_id}，岗位#{recommendation.job_id}）', 'recommendation', recommendation_id)
    db.delete(recommendation)
    db.commit()
    return Response(status_code=204)

@app.post('/api/students/{student_id}/followups', status_code=201)
def create_followup(student_id: int, data: FollowupInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    student_access(db, user, student_id)
    snapshot = None
    if data.recommendation_id:
        recommendation = db.scalar(select(Recommendation).where(Recommendation.id == data.recommendation_id, Recommendation.student_id == student_id).with_for_update())
        if not recommendation or recommendation.student_id != student_id:
            raise HTTPException(404, '推荐记录不存在或不属于此学员')
        if data.stage == '沟通':
            raise HTTPException(400, '关联岗位时请选择岗位进展状态')
        recommendation.stage = data.stage
        snapshot = recommendation.snapshot
    elif data.stage != '沟通':
        raise HTTPException(400, '更新岗位进展需要关联推荐记录')
    followup = Followup(student_id=student_id, created_by=user.id, job_snapshot=snapshot, **data.model_dump())
    db.add(followup)
    db.flush()
    audit(db, user, '新增跟进', 'followup', followup.id)
    db.commit()
    return as_dict(followup)

@app.post('/api/students/{student_id}/followups/{followup_id}/handle')
def handle_followup(student_id: int, followup_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    student_access(db, user, student_id)
    followup = db.scalar(select(Followup).where(Followup.id == followup_id, Followup.student_id == student_id).with_for_update())
    if not followup:
        raise HTTPException(404, '跟进记录不存在或不属于此学员')
    if followup.handled_at is None:
        followup.handled_at = now()
        audit(db, user, '跟进已处理', 'followup', followup.id)
        db.commit()
    return as_dict(followup)

@app.get('/api/audit-logs')
def audit_logs(page: int = Query(1, ge=1), user: User = Depends(admin), db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(AuditLog))
    rows = db.execute(select(AuditLog, User.name).join(User, User.id == AuditLog.user_id).order_by(AuditLog.id.desc()).offset((page - 1) * 30).limit(30)).all()
    return {'items': [{**as_dict(a), 'user_name': name} for a, name in rows], 'total': total}
