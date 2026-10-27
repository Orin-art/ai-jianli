from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from app.db import SessionLocal
from app.main import app, today
from app.matching import match_job
from app.models import Job
from app.imports import fingerprint


def profile(**values):
    return SimpleNamespace(**({'target_city': '上海', 'target_role': '后端开发', 'education': '本科', 'major': '计算机科学'} | values))


def job(**values):
    return SimpleNamespace(**({'city': '上海', 'title': '后端开发工程师', 'education': '大专', 'major': '计算机', 'experience': '不限', 'salary_min': 8000, 'salary_max': 12000} | values))


@pytest.mark.parametrize('education, requirement, included', [
    ('本科', '大专', True), ('大专', '本科', False), ('硕士', '本科', True),
    ('不限', '博士', False), ('本科', '不限', True), ('本科', '高中及以下', True),
    ('高中及以下', '中专', False), ('中专', '大专', False),
])
def test_education_eligibility(education, requirement, included):
    result = match_job(profile(education=education), job(education=requirement))
    assert (result is not None) == included
    if result and education == '不限' and requirement != '不限':
        assert '学历信息不足，需核对岗位要求' in result['warnings']
        assert '学历满足要求' not in result['reasons']
    if result and education == '高中及以下' and requirement == '中专':
        assert '高中与中专类别或具体学历要求需核对' in result['warnings']


@pytest.mark.parametrize('student_values, job_values', [
    ({'target_city': ''}, {}), ({'target_role': ''}, {}),
    ({'target_role': '前端开发'}, {}), ({'major': ''}, {}),
    ({}, {'major': ''}), ({}, {'major': '金融'}),
    ({}, {'major': '计算机专业除外'}), ({}, {'major': '非计算机专业'}),
    ({}, {'major': '计算机/金融除外'}),
])
def test_unmatched_and_unknown_conditions_are_excluded(student_values, job_values):
    assert match_job(profile(**student_values), job(**job_values)) is None


def test_unrestricted_major_and_unverified_experience_salary():
    result = match_job(profile(major=''), job(major='不限', experience='1-3年', salary_min=None, salary_max=None))
    assert '岗位专业不限' in result['reasons']
    assert '经验要求为1-3年，学员经验需核对' in result['warnings']
    assert '岗位薪资未填写' in result['warnings']


def test_multiple_intentions_and_city_boundaries():
    assert match_job(profile(target_city='北京市、上海市', target_role='前端开发/后端开发'), job())
    assert match_job(profile(target_city='海'), job()) is None
    assert match_job(profile(target_city='全国'), job(city='深圳'))
    assert match_job(profile(target_role='ＪＡＶＡ 开发'), job(title='Java开发工程师'))
    assert match_job(profile(target_city='上海'), job(city='上海/北京'))


def seed_jobs(client, rows):
    user_id = client.get('/api/auth/me').json()['id']
    ids = []
    with SessionLocal() as db:
        for i, values in enumerate(rows):
            data = {'title': f'后端开发-{i}', 'company': '测试企业', 'city': '上海', 'education': '大专', 'major': '计算机', 'experience': '不限', **values}
            item = Job(**data, fingerprint=fingerprint(data), created_by=user_id)
            db.add(item); db.flush(); ids.append(item.id)
        db.commit()
    return ids


def test_candidates_exclusions_sorting_and_snapshot(clients):
    client = clients('alice')
    student = client.post('/api/students', json={'name': '匹配学员', 'target_city': '上海市', 'target_role': '后端开发', 'education': '本科', 'major': '计算机科学'}).json()
    ids = seed_jobs(client, [
        {}, {'title': '其他职责'}, {'status': '失效'},
        {'expires_on': today() - timedelta(days=1)}, {'education': '硕士'},
        {'city': '北京'}, {'title': '已推荐岗位'}, {'expires_on': today()},
    ])
    url = f"/api/students/{student['id']}"
    assert client.post(url + '/recommendations', json={'job_id': ids[6]}).status_code == 201
    data = client.get(url + '/matched-jobs').json()
    assert data['total'] == 2
    assert [j['id'] for j in data['items']] == [ids[7], ids[0]]
    assert '学历满足要求' in data['items'][0]['reasons']
    assert '专业要求需结合原文核对' in data['items'][0]['warnings']
    assert client.post(url + '/recommendations', json={'job_id': ids[0]}).status_code == 201
    assert client.get(url + '/matched-jobs').json()['total'] == 1
    with SessionLocal() as db:
        db.get(Job, ids[0]).title = '后续改名'
        db.commit()
    snapshots = client.get(url).json()['recommendations']
    assert next(r for r in snapshots if r['job_id'] == ids[0])['snapshot']['title'] == '后端开发-0'


def test_matching_access_and_transfer(clients):
    alice, bob, admin = clients('alice'), clients('bob'), clients('admin')
    student = alice.post('/api/students', json={'name': '私有学员', **vars(profile())}).json()
    seed_jobs(alice, [{}])
    url = f"/api/students/{student['id']}/matched-jobs"
    assert TestClient(app).get(url).status_code == 401
    assert bob.get(url).status_code == 404
    assert alice.get(url).json()['total'] == 1
    assert admin.get(url).status_code == 200
    assert admin.get('/api/students/999999/matched-jobs').status_code == 404
    payload = {k: student[k] for k in ('name', 'phone', 'school', 'education', 'major', 'target_city', 'target_role', 'status', 'notes')}
    payload['owner_id'] = bob.get('/api/auth/me').json()['id']
    assert admin.put(f"/api/students/{student['id']}", json=payload).status_code == 200
    assert alice.get(url).status_code == 404
    assert bob.get(url).json()['total'] == 1


def test_recommend_rechecks_live_job(clients):
    client = clients('alice')
    student = client.post('/api/students', json={'name': '核对学员', **vars(profile())}).json()
    ids = seed_jobs(client, [{}])
    url = f"/api/students/{student['id']}"
    assert client.get(url + '/matched-jobs').json()['total'] == 1
    with SessionLocal() as db:
        db.get(Job, ids[0]).status = '失效'
        db.commit()
    assert client.post(url + '/recommendations', json={'job_id': ids[0]}).status_code == 400
    assert client.get(url + '/matched-jobs').json()['total'] == 0


def test_five_candidate_limit_and_replenishment(clients):
    client = clients('alice')
    student = client.post('/api/students', json={'name': '上限学员', **vars(profile())}).json()
    ids = seed_jobs(client, [{} for _ in range(12)])
    url = f"/api/students/{student['id']}"
    data = client.get(url + '/matched-jobs?page_size=100&page=2').json()
    assert data['total'] == 12 and data['limit'] == 5
    assert [j['id'] for j in data['items']] == list(reversed(ids[-5:]))
    assert data['missing_fields'] == []
    assert client.get(url).json()['recommendations'] == []
    for job_id in reversed(ids[-6:]):
        assert client.post(url + '/recommendations', json={'job_id': job_id}).status_code == 201
    data = client.get(url + '/matched-jobs').json()
    assert data['total'] == 6 and len(data['items']) == 5
    assert len(client.get(url).json()['recommendations']) == 6
    assert all(j['id'] not in ids[-6:] for j in data['items'])


def test_missing_profile_returns_explanation_without_filling_candidates(clients):
    client = clients('alice')
    student = client.post('/api/students', json={'name': '待完善'}).json()
    seed_jobs(client, [{}])
    data = client.get(f"/api/students/{student['id']}/matched-jobs").json()
    assert data['items'] == [] and data['total'] == 0
    assert '意向城市' in data['missing_fields']
    assert '意向岗位' in data['missing_fields']
