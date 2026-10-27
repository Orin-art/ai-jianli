from fastapi.testclient import TestClient
from app.main import app
from test_matching import profile, seed_jobs


def test_cancel_preserves_followups_reminders_and_allows_recommend_again(clients):
    alice, admin = clients('alice'), clients('admin')
    student = alice.post('/api/students', json={'name': '取消推荐学员', **vars(profile())}).json()
    sid = student['id']
    jobs = seed_jobs(alice, [{}, {}])
    url = f'/api/students/{sid}'
    first = alice.post(url + '/recommendations', json={'job_id': jobs[0]}).json()
    other = alice.post(url + '/recommendations', json={'job_id': jobs[1]}).json()
    followup = alice.post(url + '/followups', json={'recommendation_id': first['id'], 'stage': '面试中', 'content': '已约面试，保持跟进', 'next_date': '2026-01-01'}).json()
    assert alice.delete(url + f"/recommendations/{first['id']}").status_code == 204
    detail = alice.get(url).json()
    assert [r['id'] for r in detail['recommendations']] == [other['id']]
    retained = detail['followups'][0]
    assert retained['id'] == followup['id'] and retained['recommendation_id'] is None
    assert retained['stage'] == '面试中' and retained['content'] == followup['content']
    assert retained['next_date'] == followup['next_date']
    assert alice.get('/api/dashboard').json()['reminders'][0]['student_id'] == sid
    assert jobs[0] in [j['id'] for j in alice.get(url + '/matched-jobs').json()['items']]
    assert alice.delete(url + f"/recommendations/{first['id']}").status_code == 404
    assert alice.post(url + '/followups', json={'recommendation_id': first['id'], 'stage': '面试中', 'content': '旧页面提交'}).status_code == 404
    assert alice.post(url + '/recommendations', json={'job_id': jobs[0]}).status_code == 201
    logs = admin.get('/api/audit-logs').json()['items']
    assert any(log['entity_id'] == first['id'] and log['action'].startswith('取消岗位推荐') for log in logs)


def test_cancel_access_wrong_student_transfer_and_admin(clients):
    alice, bob, admin = clients('alice'), clients('bob'), clients('admin')
    student = alice.post('/api/students', json={'name': '权限学员', **vars(profile())}).json()
    sid = student['id']
    job_id = seed_jobs(alice, [{}])[0]
    rec = alice.post(f'/api/students/{sid}/recommendations', json={'job_id': job_id}).json()
    url = f"/api/students/{sid}/recommendations/{rec['id']}"
    assert TestClient(app, headers={'X-Requested-With': 'career-web'}).delete(url).status_code == 401
    assert bob.delete(url).status_code == 404
    different = alice.post('/api/students', json={'name': '另一个学员'}).json()['id']
    assert alice.delete(f"/api/students/{different}/recommendations/{rec['id']}").status_code == 404
    assert len(alice.get(f'/api/students/{sid}').json()['recommendations']) == 1
    payload = {k: student[k] for k in ('name', 'phone', 'school', 'education', 'major', 'target_city', 'target_role', 'status', 'notes')}
    payload['owner_id'] = bob.get('/api/auth/me').json()['id']
    assert admin.put(f'/api/students/{sid}', json=payload).status_code == 200
    assert alice.delete(url).status_code == 404
    assert bob.delete(url).status_code == 204
    again = bob.post(f'/api/students/{sid}/recommendations', json={'job_id': job_id}).json()
    assert admin.delete(f"/api/students/{sid}/recommendations/{again['id']}").status_code == 204
