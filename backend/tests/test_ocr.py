from io import BytesIO
from unittest.mock import Mock
import pytest
from PIL import Image
from pypdf import PdfWriter, PdfReader
from sqlalchemy import select
from app import resume_parser, resume_cache, ocr
from app.db import SessionLocal
from app.models import Resume
from app.ocr_worker import ordered_text
from test_resume_parser import pdf_with_contact

def image_bytes(kind='PNG', size=(300, 200)):
    output = BytesIO(); Image.new('RGB', size, 'white').save(output, format=kind)
    return output.getvalue()

def scanned_pdf(count=1, text_first=False):
    writer = PdfWriter()
    if text_first:
        writer.add_page(PdfReader(BytesIO(pdf_with_contact())).pages[0])
    for _ in range(count):
        writer.add_blank_page(width=300, height=400)
    output = BytesIO(); writer.write(output)
    return output.getvalue()

def fake_ocr(content, suffix, pages=None):
    return {'ok': True, 'texts': {i: '姓名：张小禾\n电话：13800138000\n学校：清河大学\n专业：软件工程\n学历：本科' for i in (pages or [0])}, 'uncertain': False}

def test_images_scan_fallback_and_page_limit(monkeypatch):
    seen = []
    def fake(content, suffix, pages=None):
        seen.append((suffix, pages))
        return fake_ocr(content, suffix, pages)
    monkeypatch.setattr(resume_parser, 'run_ocr', fake)
    result = resume_parser.parse_resume(image_bytes(), '.png')
    assert result['method'] == 'ocr' and not result['retryable']
    assert result['fields']['phone']['value'] == '13800138000'
    result = resume_parser.parse_resume(scanned_pdf(6), '.pdf')
    assert seen[-1] == ('.pdf', [0, 1, 2, 3, 4])
    assert any('前 5' in warning for warning in result['warnings'])
    result = resume_parser.parse_resume(scanned_pdf(1, text_first=True), '.pdf')
    assert seen[-1] == ('.pdf', [1]) and result['method'] == 'mixed'
    before = len(seen)
    resume_parser.parse_resume(pdf_with_contact(), '.pdf')
    resume_parser.parse_resume(pdf_with_contact(encrypted=True), '.pdf')
    assert len(seen) == before

def test_failed_ocr_retains_file_and_text_for_retry(monkeypatch):
    def busy(*args):
        raise ocr.OcrError('OCR 正忙，请重试')
    monkeypatch.setattr(resume_parser, 'run_ocr', busy)
    result = resume_parser.parse_resume(scanned_pdf(text_first=True), '.pdf')
    assert result['retryable'] and result['fields']['phone']['value'] == '13800138000'
    assert '正忙' in result['warnings'][0]
    result = resume_parser.parse_resume(image_bytes(), '.png')
    assert result['retryable'] and not result['fields']

def test_line_order_and_confidence_filter():
    text, uncertain = ordered_text({'rec_texts': ['张小禾', '姓名：', '模糊文字', '13800138000', '电话：'], 'rec_scores': [0.98, 0.99, 0.2, 0.98, 0.99], 'rec_boxes': [[130, 10, 240, 40], [10, 12, 100, 42], [10, 90, 100, 120], [130, 55, 300, 85], [10, 55, 100, 85]]})
    assert text == '姓名： 张小禾\n电话： 13800138000' and uncertain

def test_worker_busy_timeout_and_unavailable(monkeypatch):
    monkeypatch.setattr(ocr, 'status', lambda: {'available': False})
    client = ocr.OcrClient()
    with pytest.raises(ocr.OcrError, match='尚未就绪'):
        client.run(b'private', '.png')
    monkeypatch.setattr(ocr, 'status', lambda: {'available': True})
    client.lock.acquire()
    with pytest.raises(ocr.OcrError, match='另一份'):
        client.run(b'private', '.png')
    client.lock.release()
    connection, process = Mock(), Mock()
    connection.poll.return_value = False; process.is_alive.return_value = True
    client.connection = connection; client.process = process
    close = Mock(); monkeypatch.setattr(client, 'close', close)
    with pytest.raises(ocr.OcrError, match='超时'):
        client.run(b'private', '.png')
    close.assert_called_once()
    assert client.lock.acquire(blocking=False)
    client.lock.release()

def test_image_upload_cache_refresh_validation_and_privacy(clients, monkeypatch):
    a, b = clients('alice'), clients('bob')
    sid = a.post('/api/students', json={'name': '测试学员'}).json()['id']
    calls = []
    def parse(content, suffix):
        calls.append(suffix)
        return {'fields': {'phone': {'value': '13800138000', 'evidence': '电话：13800138000'}}, 'warnings': [], 'method': 'ocr', 'retryable': False}
    monkeypatch.setattr(resume_cache, 'parse_resume', parse)
    response = a.post(f'/api/students/{sid}/resumes', files={'file': ('简历.png', image_bytes())})
    assert response.status_code == 201, response.text
    result = response.json(); rid = result['id']
    assert result['content_type'] == 'image/png' and result['extraction']['method'] == 'ocr'
    assert a.get(f'/api/resumes/{rid}/extraction').status_code == 200
    assert len(calls) == 1
    assert b.get(f'/api/resumes/{rid}/extraction').status_code == 404
    assert b.get(f'/api/resumes/{rid}/download').status_code == 404
    assert len(calls) == 1
    assert a.get(f'/api/resumes/{rid}/extraction?refresh=true').status_code == 200
    assert len(calls) == 2
    profile = a.get(f'/api/students/{sid}').json()
    assert profile['phone'] == ''
    assert 'extraction_cache' not in profile['resumes'][0]
    with SessionLocal() as db:
        resume = db.get(Resume, rid)
        assert resume.extraction_cache is not None
        resume.extraction_version = 'old-version'; db.commit()
    a.get(f'/api/resumes/{rid}/extraction')
    assert len(calls) == 3
    assert a.post(f'/api/students/{sid}/resumes', files={'file': ('伪装.png', b'not an image')}).status_code == 400
    assert a.post(f'/api/students/{sid}/resumes', files={'file': ('错格式.jpg', image_bytes())}).status_code == 400
    assert a.post(f'/api/students/{sid}/resumes', files={'file': ('超大.png', image_bytes(size=(5000, 4100)))}).status_code == 400
    jpeg = a.post(f'/api/students/{sid}/resumes', files={'file': ('简历.jpg', image_bytes('JPEG'))})
    assert jpeg.status_code == 201 and jpeg.json()['content_type'] == 'image/jpeg'

def test_retryable_results_are_not_cached(clients, monkeypatch):
    a = clients('alice')
    sid = a.post('/api/students', json={'name': '测试学员'}).json()['id']
    def unavailable(*args):
        return {'fields': {}, 'warnings': ['OCR 正忙'], 'method': 'ocr', 'retryable': True}
    monkeypatch.setattr(resume_cache, 'parse_resume', unavailable)
    result = a.post(f'/api/students/{sid}/resumes', files={'file': ('简历.png', image_bytes())}).json()
    rid = result['id']
    with SessionLocal() as db:
        assert db.get(Resume, rid).extraction_cache is None
    monkeypatch.setattr(resume_cache, 'parse_resume', lambda *args: {'fields': {}, 'warnings': [], 'method': 'ocr', 'retryable': False})
    assert not a.get(f'/api/resumes/{rid}/extraction').json()['retryable']
    with SessionLocal() as db:
        assert db.get(Resume, rid).extraction_cache is not None
