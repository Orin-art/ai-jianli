from fastapi.testclient import TestClient
from app.main import app
from test_matching import seed_jobs


def test_handled_reminder_stays_hidden_without_reviving_older_events(clients):
    alice = clients('alice')
    sid = alice.post('/api/students', json={'name': '跟进学员'}).json()['id']
    url = f'/api/students/{sid}/followups'
    older = alice.post(url, json={'content': '旧提醒', 'next_date': '2020-01-01'}).json()
    latest = alice.post(url, json={'content': '本次提醒', 'next_date': '2020-01-02'}).json()
    assert [f['id'] for f in alice.get('/api/dashboard').json()['reminders']] == [latest['id']]
    handled = alice.post(url + f"/{latest['id']}/handle").json()
    assert handled['handled_at']
    assert handled['content'] == latest['content'] and handled['next_date'] == latest['next_date']
    assert alice.get('/api/dashboard').json()['reminders'] == []
    # Repeating the action is safe and retains the original processing time.
    assert alice.post(url + f"/{latest['id']}/handle").json()['handled_at'] == handled['handled_at']
    followups = alice.get(f'/api/students/{sid}').json()['followups']
    assert followups[0]['handled_at'] == handled['handled_at']
    assert followups[1]['id'] == older['id'] and followups[1]['handled_at'] is None
    new = alice.post(url, json={'content': '新的跟进', 'next_date': '2020-01-03'}).json()
    assert [f['id'] for f in alice.get('/api/dashboard').json()['reminders']] == [new['id']]


def test_followup_job_snapshot_survives_cancellation(clients):
    alice = clients('alice')
    sid = alice.post('/api/students', json={'name': '岗位跟进学员'}).json()['id']
    job_id = seed_jobs(alice, [{}])[0]
    url = f'/api/students/{sid}'
    rec = alice.post(url + '/recommendations', json={'job_id': job_id}).json()
    followup = alice.post(url + '/followups', json={'recommendation_id': rec['id'], 'stage': '面试中', 'content': '预约面试'}).json()
    assert followup['job_snapshot']['title'] == rec['snapshot']['title']
    assert followup['job_snapshot']['company'] == rec['snapshot']['company']
    assert alice.delete(url + f"/recommendations/{rec['id']}").status_code == 204
    retained = alice.get(url).json()['followups'][0]
    assert retained['recommendation_id'] is None
    assert retained['job_snapshot'] == followup['job_snapshot']


def test_handle_checks_student_access_and_followup_ownership(clients):
    alice, bob, admin = clients('alice'), clients('bob'), clients('admin')
    sid = alice.post('/api/students', json={'name': '权限学员'}).json()['id']
    f = alice.post(f'/api/students/{sid}/followups', json={'content': '沟通'}).json()
    url = f"/api/students/{sid}/followups/{f['id']}/handle"
    assert TestClient(app, headers={'X-Requested-With': 'career-web'}).post(url).status_code == 401
    assert bob.post(url).status_code == 404
    other = alice.post('/api/students', json={'name': '另一学员'}).json()['id']
    assert alice.post(f"/api/students/{other}/followups/{f['id']}/handle").status_code == 404
    assert alice.post(f'/api/students/{sid}/followups/999999/handle').status_code == 404
    assert alice.get(f'/api/students/{sid}').json()['followups'][0]['handled_at'] is None
    assert admin.post(url).status_code == 200
    logs = admin.get('/api/audit-logs').json()['items']
    assert len([log for log in logs if log['entity_id'] == f['id'] and log['action'] == '跟进已处理']) == 1
