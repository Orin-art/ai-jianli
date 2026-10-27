from app.db import SessionLocal
from app.models import Resume
from app import resume_cache
from test_resume_parser import docx
from test_business import add_job

def upload(client, sid, name):
    response = client.post(f'/api/students/{sid}/resumes', files={'file': (name, docx(['学校：清河大学', '电话：13800138000']))})
    assert response.status_code == 201, response.text
    return response.json()['id']

def test_resume_delete_permissions_and_preserves_student_history(clients):
    a, b, admin = clients('alice'), clients('bob'), clients('admin')
    sid = a.post('/api/students', json={'name': '测试学员', 'school': '清河大学', 'phone': '13800138000'}).json()['id']
    first = upload(a, sid, '历史简历.docx')
    second = upload(a, sid, '新版简历.docx')
    job = add_job(a)
    assert a.post(f'/api/students/{sid}/recommendations', json={'job_id': job['id']}).status_code == 201
    assert a.post(f'/api/students/{sid}/followups', json={'content': '继续准备面试'}).status_code == 201
    with SessionLocal() as db:
        assert db.get(Resume, first).extraction_cache is not None
    assert b.delete(f'/api/resumes/{first}').status_code == 404
    assert a.get(f'/api/resumes/{first}/download').status_code == 200
    assert a.delete(f'/api/resumes/{first}').status_code == 204
    assert a.delete(f'/api/resumes/{first}').status_code == 404
    assert a.get(f'/api/resumes/{first}/download').status_code == 404
    assert a.get(f'/api/resumes/{first}/extraction').status_code == 404
    assert a.post(f'/api/resumes/{first}/apply', json={'changes': [{'field': 'school', 'value': '远山大学', 'expected': '清河大学'}]}).status_code == 404
    with SessionLocal() as db:
        assert db.get(Resume, first) is None
    detail = a.get(f'/api/students/{sid}').json()
    assert detail['school'] == '清河大学' and detail['phone'] == '13800138000'
    assert len(detail['recommendations']) == 1 and len(detail['followups']) == 1
    assert [r['id'] for r in detail['resumes']] == [second]
    assert admin.delete(f'/api/resumes/{second}').status_code == 204
    assert a.get(f'/api/students/{sid}').json()['resumes'] == []
    assert any(log['action'] == '删除简历及识别缓存' for log in admin.get('/api/audit-logs').json()['items'])

def test_delete_while_extraction_cannot_recreate_cache(clients, monkeypatch):
    a = clients('alice')
    sid = a.post('/api/students', json={'name': '测试学员'}).json()['id']
    rid = upload(a, sid, '测试简历.docx')
    def remove_during_parse(*args):
        with SessionLocal() as db:
            db.delete(db.get(Resume, rid)); db.commit()
        return {'fields': {}, 'warnings': [], 'retryable': False, 'method': 'text'}
    monkeypatch.setattr(resume_cache, 'parse_resume', remove_during_parse)
    response = a.get(f'/api/resumes/{rid}/extraction?refresh=true')
    assert response.status_code == 404
    with SessionLocal() as db:
        assert db.get(Resume, rid) is None
