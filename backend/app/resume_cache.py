from .resume_parser import parse_resume
from fastapi import HTTPException
from sqlalchemy.orm.exc import StaleDataError

PARSER_VERSION = 'resume-v2-ppocrv5-mobile-3.3.3'

def extract_resume(resume, db, refresh=False):
    if not refresh and resume.extraction_version == PARSER_VERSION and resume.extraction_cache is not None:
        return resume.extraction_cache
    suffix = '.' + resume.filename.rsplit('.', 1)[-1].lower()
    result = parse_resume(resume.content, suffix)
    if not result.get('retryable', False):
        resume.extraction_cache = result
        resume.extraction_version = PARSER_VERSION
        try:
            db.commit()
        except StaleDataError:
            db.rollback()
            raise HTTPException(404, '该简历已被删除，请刷新学员档案') from None
    return result
