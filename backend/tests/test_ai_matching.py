import json
from urllib.error import HTTPError, URLError

import pytest
from fastapi import HTTPException
from app import ai_matching
from app.db import SessionLocal
from app.models import Job, Resume, Student
from app import vector_index
from test_matching import seed_jobs
from test_resume_parser import docx

TEXT = '姓名：测试学员\n电话：13800138000\n邮箱：student@example.com\n学历：本科\n专业：计算机科学\n专业技能：熟悉 Python 和 FastAPI，使用 PostgreSQL 构建后端接口。\n项目经历：开发校园管理系统，实现登录权限和数据分页。'
EVIDENCE = '熟悉 Python 和 FastAPI，使用 PostgreSQL 构建后端接口'


@pytest.fixture(autouse=True)
def local_vector_stub(monkeypatch):
    monkeypatch.setattr(vector_index, 'status', lambda: {'ready': True, 'engine': 'Qdrant'})
    monkeypatch.setattr(vector_index, 'search', lambda query, jobs, limit: {
        'hits': [{'job_id': job.id, 'score': 0.8, 'chunk': job.description, 'digest': 'test'} for job in jobs[:limit]],
        'model': 'BAAI/bge-small-zh-v1.5'})


def analysis():
    return {'summary': '具备 Python 后端项目经历', 'skills': [{'value': 'Python', 'evidence': EVIDENCE}],
            'experience': [{'value': '校园管理系统项目', 'evidence': '开发校园管理系统，实现登录权限和数据分页'}],
            'education': {'value': '本科', 'evidence': '学历：本科'}, 'major': {'value': '计算机科学', 'evidence': '专业：计算机科学'},
            'target_roles': ['软件工程师'], 'warnings': ['简历未说明全职工作年限']}


def setup(client):
    student = client.post('/api/students', json={'name': '测试学员', 'phone': '13800138000', 'education': '本科', 'target_city': '上海', 'target_role': '后端开发'}).json()
    resume = client.post(f"/api/students/{student['id']}/resumes", files={'file': ('resume.docx', docx(TEXT.splitlines()))}).json()
    jobs = seed_jobs(client, [{'title': '软件工程师', 'description': '使用 Python 和 FastAPI 开发后端接口', 'major': '', 'experience': '不限'},
                              {'title': '外地软件工程师', 'city': '北京'}, {'title': '硕士软件工程师', 'education': '硕士'}, {'status': '失效'}])
    return student, resume, jobs


def ranking(job_id):
    return {'items': [{'job_id': job_id, 'reason': 'Python 后端技能与岗位职责直接相关', 'resume_evidence': EVIDENCE,
                       'job_evidence': '使用 Python 和 FastAPI 开发后端接口', 'gaps': ['专业要求未填写，需确认']}],
            'explanation': '按技能与岗位职责匹配，未推断全职经验。'}


def mock_model(monkeypatch, job_id, mutate=None):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key-never-sent')
    payloads = []
    def respond(system, payload):
        payloads.append(payload)
        if 'jobs' not in payload:
            return analysis()
        if mutate:
            mutate()
        return ranking(job_id)
    monkeypatch.setattr(ai_matching, 'call_model', respond)
    return payloads


def test_ai_semantic_matching_redaction_evidence_and_manual_save(clients, monkeypatch):
    client, admin = clients('alice'), clients('admin')
    student, resume, jobs = setup(client)
    payloads = mock_model(monkeypatch, jobs[0])
    url = f"/api/students/{student['id']}"
    response = client.post(url + '/ai-matched-jobs', json={'resume_id': resume['id'], 'consent': True})
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result['items']) == 1 and result['items'][0]['id'] == jobs[0]
    assert result['analysis']['skills'][0]['evidence'] == EVIDENCE
    serialized = json.dumps(payloads, ensure_ascii=False)
    assert '13800138000' not in serialized and 'student@example.com' not in serialized and '测试学员' not in serialized
    assert [job['id'] for job in payloads[1]['jobs']] == [jobs[0]]
    assert 'phone' not in payloads[1]['preferences']
    assert client.get(url).json()['recommendations'] == []
    assert client.post(url + '/recommendations', json={'job_id': jobs[0]}).status_code == 201
    assert any(log['action'] == 'DeepSeek 简历分析与岗位候选生成' for log in admin.get('/api/audit-logs').json()['items'])


def test_ai_permissions_consent_and_not_configured(clients, monkeypatch):
    client, bob = clients('alice'), clients('bob')
    student, resume, jobs = setup(client)
    url = f"/api/students/{student['id']}/ai-matched-jobs"
    data = {'resume_id': resume['id'], 'consent': True}
    assert bob.post(url, json=data).status_code == 404
    other = client.post('/api/students', json={'name': '另一个学员'}).json()
    assert client.post(f"/api/students/{other['id']}/ai-matched-jobs", json=data).status_code == 404
    assert client.post(url, json={'resume_id': resume['id'], 'consent': False}).status_code == 422
    assert client.post(url, json={'resume_id': resume['id']}).status_code == 422
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    assert client.get('/api/ai/status').json()['configured'] is False
    assert client.post(url, json=data).status_code == 503


@pytest.mark.parametrize('failure', ['fake_id', 'duplicate', 'too_many', 'fake_resume_evidence', 'fake_job_evidence', 'fake_analysis_evidence'])
def test_invalid_ai_output_never_becomes_a_recommendation(clients, monkeypatch, failure):
    client = clients('alice')
    student, resume, jobs = setup(client)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key-never-sent')
    def respond(system, payload):
        if 'jobs' not in payload:
            result = analysis()
            if failure == 'fake_analysis_evidence':
                result['skills'][0]['evidence'] = '并不存在的技能事实'
            return result
        result = ranking(jobs[0])
        if failure == 'fake_id': result['items'][0]['job_id'] = jobs[1]
        if failure == 'duplicate': result['items'] *= 2
        if failure == 'too_many': result['items'] *= 6
        if failure == 'fake_resume_evidence': result['items'][0]['resume_evidence'] = '具备五年全职管理经验'
        if failure == 'fake_job_evidence': result['items'][0]['job_evidence'] = '岗位没有这一条件'
        return result
    monkeypatch.setattr(ai_matching, 'call_model', respond)
    response = client.post(f"/api/students/{student['id']}/ai-matched-jobs", json={'resume_id': resume['id'], 'consent': True})
    assert response.status_code == 502
    assert client.get(f"/api/students/{student['id']}").json()['recommendations'] == []


@pytest.mark.parametrize('change, expected', [('expire', 200), ('delete_resume', 409), ('transfer', 404), ('edit_profile', 409)])
def test_ai_rechecks_live_state_after_generation(clients, monkeypatch, change, expected):
    client = clients('alice')
    student, resume, jobs = setup(client)
    def mutate():
        with SessionLocal() as db:
            if change == 'expire': db.get(Job, jobs[0]).status = '失效'
            if change == 'delete_resume': db.delete(db.get(Resume, resume['id']))
            if change == 'transfer': db.get(Student, student['id']).owner_id = 3
            if change == 'edit_profile': db.get(Student, student['id']).target_city = '北京'
            db.commit()
    mock_model(monkeypatch, jobs[0], mutate)
    response = client.post(f"/api/students/{student['id']}/ai-matched-jobs", json={'resume_id': resume['id'], 'consent': True})
    assert response.status_code == expected, response.text
    if change == 'expire':
        assert response.json()['items'] == [] and response.json()['warnings']


def test_deepseek_transport_and_private_errors(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'private-test-key')
    requests = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]}).encode()
    def transport(request, timeout):
        requests.append(request)
        assert timeout == 40
        return Response()
    monkeypatch.setattr(ai_matching, 'urlopen', transport)
    assert ai_matching.call_model('output json', {'test': True}) == {'ok': True}
    body = json.loads(requests[0].data)
    assert body['response_format']['type'] == 'json_object' and body['thinking']['type'] == 'disabled'
    assert requests[0].full_url == 'https://api.deepseek.com/chat/completions'
    for error, code in [(HTTPError('url', 401, 'private-test-key', {}, None), 503), (URLError('private-test-key'), 504)]:
        def fail(*args, **kwargs): raise error
        monkeypatch.setattr(ai_matching, 'urlopen', fail)
        with pytest.raises(HTTPException) as caught:
            ai_matching.call_model('json', {})
        assert caught.value.status_code == code and 'private-test-key' not in caught.value.detail


def test_vector_failure_does_not_fall_back_or_call_paid_model(clients, monkeypatch):
    client = clients('alice')
    student, resume, _ = setup(client)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'not-sent')
    monkeypatch.setattr(vector_index, 'status', lambda: {'ready': False})
    monkeypatch.setattr(ai_matching, 'call_model', lambda *args: pytest.fail('Paid model must not be called'))
    result = client.post(f"/api/students/{student['id']}/ai-matched-jobs", json={'resume_id': resume['id'], 'consent': True})
    assert result.status_code == 503 and '未调用 DeepSeek' in result.json()['detail']
