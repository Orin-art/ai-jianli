"""Isolated browser-test seed. Refuses application databases."""
from sqlalchemy import select
from .db import engine, SessionLocal
from .models import User
from .security import passwords

def main():
    if not engine.url.database or not engine.url.database.endswith('_e2e'):
        raise SystemExit('E2E 初始化仅允许名称以 _e2e 结尾的专用数据库')
    with SessionLocal() as db:
        if not db.scalar(select(User.id).where(User.username == 'e2e-admin')):
            db.add(User(username='e2e-admin', name='测试管理员', password_hash=passwords.hash('E2e-Only-Password-123'), role='admin'))
            db.commit()

if __name__ == '__main__':
    main()
