from datetime import datetime, date
from sqlalchemy import String, Text, ForeignKey, JSON, LargeBinary, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, now

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default='consultant')
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=now)

class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)

class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(default=0)
    window_start: Mapped[datetime] = mapped_column(default=now)

class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160), index=True)
    company: Mapped[str] = mapped_column(String(160), index=True)
    city: Mapped[str] = mapped_column(String(80), index=True)
    education: Mapped[str] = mapped_column(String(20), default='不限')
    experience: Mapped[str] = mapped_column(String(20), default='不限')
    major: Mapped[str] = mapped_column(String(200), default='')
    salary_min: Mapped[int | None]
    salary_max: Mapped[int | None]
    description: Mapped[str] = mapped_column(Text, default='')
    source: Mapped[str] = mapped_column(String(300), default='')
    expires_on: Mapped[date | None]
    status: Mapped[str] = mapped_column(String(20), default='有效', index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(default=now)

class ImportBatch(Base):
    __tablename__ = 'import_batches'
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(200))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    status: Mapped[str] = mapped_column(String(20), default='待确认')
    rows: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=now)
    committed_at: Mapped[datetime | None]

class Student(Base):
    __tablename__ = 'students'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(40), default='')
    school: Mapped[str] = mapped_column(String(200), default='')
    education: Mapped[str] = mapped_column(String(20), default='本科')
    major: Mapped[str] = mapped_column(String(200), default='')
    target_city: Mapped[str] = mapped_column(String(100), default='')
    target_role: Mapped[str] = mapped_column(String(200), default='')
    status: Mapped[str] = mapped_column(String(20), default='服务中')
    notes: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(default=now)

class Resume(Base):
    __tablename__ = 'resumes'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('students.id'), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    extraction_cache: Mapped[dict | None] = mapped_column(JSON)
    extraction_version: Mapped[str] = mapped_column(String(64), default='')
    uploaded_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(default=now)

class Recommendation(Base):
    __tablename__ = 'recommendations'
    __table_args__ = (UniqueConstraint('student_id', 'job_id', name='uq_recommendation_student_job'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('students.id'), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    snapshot: Mapped[dict] = mapped_column(JSON)
    stage: Mapped[str] = mapped_column(String(20), default='已推荐')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(default=now)

class Followup(Base):
    __tablename__ = 'followups'
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey('students.id'), index=True)
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey('recommendations.id'))
    stage: Mapped[str] = mapped_column(String(20), default='沟通')
    content: Mapped[str] = mapped_column(Text)
    next_date: Mapped[date | None]
    handled_at: Mapped[datetime | None] = mapped_column(DateTime)
    job_snapshot: Mapped[dict | None] = mapped_column(JSON)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(default=now)

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=now)
