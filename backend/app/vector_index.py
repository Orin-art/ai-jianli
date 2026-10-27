"""Internal retrieval client and eventual reconciliation of shared job vectors."""
import json
import logging
import os
import threading
from datetime import timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError

from fastapi import HTTPException
from sqlalchemy import select, or_
from .db import SessionLocal, now
from .models import Job

_wake = threading.Event()
_stop = threading.Event()
_thread = None
_last_sync = None
_sync_error = False


def configured():
    return bool(os.getenv('RETRIEVAL_URL', '').strip())


def request(path, data=None, timeout=180):
    base = os.getenv('RETRIEVAL_URL', '').rstrip('/')
    if not base:
        raise HTTPException(503, 'Qdrant 向量检索服务尚未配置')
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = Request(base + path, data=body, headers={'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except (URLError, TimeoutError, ValueError, OSError):
        raise HTTPException(503, 'Qdrant 向量检索暂不可用，请稍后重试或联系管理员；未改用关键词结果') from None


def document(job):
    return {key: getattr(job, key) for key in ('id', 'title', 'city', 'education', 'major', 'experience', 'description', 'salary_min', 'salary_max')}


def active_jobs(db):
    today = (now() + timedelta(hours=8)).date()
    return list(db.scalars(select(Job).where(Job.status == '有效', or_(Job.expires_on.is_(None), Job.expires_on >= today))))


def sync():
    global _last_sync, _sync_error
    with SessionLocal() as db:
        data = request('/sync', {'jobs': [document(job) for job in active_jobs(db)]})
    _last_sync = now().isoformat()
    _sync_error = False
    return data


def status():
    if not configured():
        return {'ready': False, 'message': 'Qdrant 向量检索尚未配置'}
    try:
        return {**request('/health', timeout=5), 'engine': 'Qdrant', 'last_sync': _last_sync, 'sync_pending': _sync_error}
    except HTTPException:
        return {'ready': False, 'message': 'Qdrant 向量服务正在准备或暂不可用'}


def search(query, jobs, limit=40):
    return request('/search', {'query': query[:6000], 'jobs': [document(job) for job in jobs], 'limit': min(limit, 40)})


def notify():
    _wake.set()


def _run():
    global _sync_error
    while not _stop.is_set():
        _wake.clear()
        try:
            sync()
        except Exception:
            _sync_error = True
            logging.getLogger(__name__).warning('Job vector synchronization failed; will retry')
        if _stop.is_set():
            break
        _wake.wait(60)


def start():
    global _thread
    if not configured():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, daemon=True, name='job-vector-sync')
    _thread.start()


def stop():
    _stop.set()
    _wake.set()
    if _thread:
        _thread.join(timeout=2)


if __name__ == '__main__':
    print(json.dumps(sync(), ensure_ascii=False))
