import os
import tempfile
from pathlib import Path

# Tests never touch the application's configured database.
TEST_DIR = tempfile.TemporaryDirectory(prefix='career-tests-')
os.environ['DATABASE_URL'] = os.getenv('TEST_DATABASE_URL', 'sqlite:///' + str(Path(TEST_DIR.name) / 'test.db'))
os.environ['COOKIE_SECURE'] = 'false'

import pytest
from fastapi.testclient import TestClient
from app.db import Base, engine, SessionLocal
from app.models import User
from app.main import app
from app.security import passwords

PASSWORD = 'Testing-Password-123'
HASH = passwords.hash(PASSWORD)

@pytest.fixture(scope='session', autouse=True)
def cleanup_engine():
    yield
    engine.dispose()
    TEST_DIR.cleanup()

@pytest.fixture(autouse=True)
def database():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add_all([User(username='admin', name='管理员', password_hash=HASH, role='admin'), User(username='alice', name='顾问甲', password_hash=HASH, role='consultant'), User(username='bob', name='顾问乙', password_hash=HASH, role='consultant')])
        db.commit()
    yield
    Base.metadata.drop_all(engine)

@pytest.fixture
def clients():
    handles = []
    def make(username):
        client = TestClient(app, headers={'X-Requested-With': 'career-web'})
        assert client.post('/api/auth/login', json={'username': username, 'password': PASSWORD}).status_code == 200
        handles.append(client)
        return client
    yield make
    for client in handles:
        client.close()
