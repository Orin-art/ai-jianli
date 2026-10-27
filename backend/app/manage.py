import argparse
import getpass
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import SessionLocal
from .models import User, AuthSession
from .security import passwords

def main():
    parser = argparse.ArgumentParser(description='创建管理员或重置账号密码（不会自动创建数据库表）')
    parser.add_argument('command', choices=['create-admin', 'reset-password'])
    parser.add_argument('--username', required=True)
    parser.add_argument('--name', default='管理员')
    args = parser.parse_args()
    password = getpass.getpass('密码（至少 10 位）: ')
    if len(password) < 10 or len(password) > 128 or password != password.strip():
        raise SystemExit('密码需为 10～128 位，且首尾不能包含空白')
    if password != getpass.getpass('再次输入密码: '):
        raise SystemExit('两次密码不一致')
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == args.username))
        if args.command == 'create-admin':
            if db.scalar(select(User.id).where(User.role == 'admin')) is not None:
                raise SystemExit('主账号已存在，只能由主账号在顾问管理中创建顾问账号')
            if user:
                raise SystemExit('账号已存在')
            db.add(User(username=args.username, name=args.name, password_hash=passwords.hash(password), role='admin'))
        else:
            if not user:
                raise SystemExit('账号不存在')
            user.password_hash = passwords.hash(password)
            from sqlalchemy import delete
            db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise SystemExit('账号已存在或主账号已创建；系统仅允许一个主账号')
    print('操作成功')

if __name__ == '__main__':
    main()
