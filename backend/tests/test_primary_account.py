import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.db import SessionLocal
from app.models import User
from app.security import passwords


def test_only_primary_can_manage_accounts_and_cannot_create_another_primary(clients):
    primary, alice = clients('admin'), clients('alice')
    payload = {'username': 'new-advisor', 'name': '新顾问', 'password': 'New-Password-123'}
    assert alice.post('/api/users', json=payload).status_code == 403
    assert alice.patch('/api/users/3', json={'active': False}).status_code == 403
    assert alice.get('/api/users').status_code == 403
    assert primary.post('/api/users', json={**payload, 'role': 'admin'}).status_code == 422
    created = primary.post('/api/users', json=payload)
    assert created.status_code == 201 and created.json()['role'] == 'consultant'
    assert primary.patch('/api/users/1', json={'active': False}).status_code == 400
    assert primary.patch(f"/api/users/{created.json()['id']}", json={'role': 'admin'}).status_code == 422
    with SessionLocal() as db:
        db.add(User(username='other-primary', name='第二主账号', role='admin', password_hash=passwords.hash('Password-123')))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert len(db.scalars(select(User).where(User.role == 'admin')).all()) == 1


def test_primary_cli_refuses_second_primary(clients, monkeypatch):
    from app.manage import main
    monkeypatch.setattr('sys.argv', ['manage', 'create-admin', '--username', 'another-admin'])
    monkeypatch.setattr('getpass.getpass', lambda _: 'Password-123')
    with pytest.raises(SystemExit, match='主账号已存在'):
        main()


def test_team_stats_filter_assignment_and_isolation(clients):
    primary, alice, bob = clients('admin'), clients('alice'), clients('bob')
    sid = alice.post('/api/students', json={'name': '交接学员', 'school': '交接大学', 'notes': '保持资料'}).json()['id']
    url = f'/api/students/{sid}'
    alice.post(url + '/followups', json={'content': '待交接沟通', 'next_date': '2020-01-01'})
    alice.post('/api/students', json={'name': '已结束学员', 'status': '已结束'})
    stats = {u['username']: u for u in primary.get('/api/users').json()}
    assert [stats['alice'][k] for k in ('student_count', 'serving_count', 'due_count')] == [2, 1, 1]
    assert stats['bob']['student_count'] == stats['bob']['due_count'] == 0
    rows = primary.get('/api/students?owner_id=2').json()
    assert rows['total'] == 2 and all(s['owner_name'] == '顾问甲' for s in rows['items'])
    assert primary.get('/api/students?owner_id=3').json()['total'] == 0
    assert bob.get('/api/students?owner_id=2').status_code == 403
    assert bob.patch(url + '/owner', json={'owner_id': 3, 'expected_owner_id': 2}).status_code == 403
    assert alice.patch(url + '/owner', json={'owner_id': 3, 'expected_owner_id': 2}).status_code == 403
    assert primary.patch(url + '/owner', json={'owner_id': 999, 'expected_owner_id': 2}).status_code == 400
    assert primary.patch(url + '/owner', json={'owner_id': 3, 'expected_owner_id': 1}).status_code == 409
    assert primary.patch(url + '/owner', json={'owner_id': 3, 'expected_owner_id': 2}).status_code == 200
    assert alice.get(url).status_code == 404
    retained = bob.get(url).json()
    assert retained['school'] == '交接大学' and retained['notes'] == '保持资料'
    assert retained['followups'][0]['content'] == '待交接沟通'
    assert primary.get(url).status_code == 200
    stats = {u['username']: u for u in primary.get('/api/users').json()}
    assert [stats['bob'][k] for k in ('student_count', 'serving_count', 'due_count')] == [1, 1, 1]
    assert stats['alice']['serving_count'] == stats['alice']['due_count'] == 0
    f = retained['followups'][0]
    bob.post(url + f"/followups/{f['id']}/handle")
    assert next(u for u in primary.get('/api/users').json() if u['username'] == 'bob')['due_count'] == 0
    assert primary.patch('/api/users/2', json={'active': False}).status_code == 200
    assert primary.patch(url + '/owner', json={'owner_id': 2, 'expected_owner_id': 3}).status_code == 400
    # A disabled advisor's students remain visible and can be reassigned by the primary.
    assert primary.get('/api/students?owner_id=2').json()['total'] == 1
    assert primary.post('/api/students', json={'name': '直接分配', 'owner_id': 3}).status_code == 201
    assert any('转交学员 2 → 3' == log['action'] for log in primary.get('/api/audit-logs').json()['items'])
