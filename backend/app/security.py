import hashlib
import os
import secrets
from datetime import timedelta
from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy.orm import Session
from .db import get_db, now
from .models import User, AuthSession, AuditLog

passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash(secrets.token_urlsafe(24))
COOKIE = 'career_session'
SECURE = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
SESSION_HOURS = int(os.getenv('SESSION_HOURS', '8'))

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    session = db.get(AuthSession, token_hash(token)) if token else None
    if not session or session.expires_at <= now():
        raise HTTPException(401, '登录已过期，请重新登录')
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, '账号不可用')
    return user

def admin(user: User = Depends(current_user)):
    if user.role != 'admin':
        raise HTTPException(403, '仅主账号可执行此操作')
    return user

def new_session(db, user, response):
    token = secrets.token_urlsafe(48)
    seconds = SESSION_HOURS * 3600
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, expires_at=now() + timedelta(seconds=seconds)))
    response.set_cookie(COOKIE, token, httponly=True, secure=SECURE, samesite='strict', max_age=seconds, path='/')

def audit(db, user, action, entity, entity_id):
    db.add(AuditLog(user_id=user.id, action=action, entity=entity, entity_id=entity_id))

def user_dict(u):
    return {'id': u.id, 'username': u.username, 'name': u.name, 'role': u.role, 'active': u.active}
