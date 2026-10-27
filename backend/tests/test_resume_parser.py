from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from html import escape
from pypdf import PdfWriter
from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
from app.resume_parser import extract_fields, parse_resume

def docx(lines):
    data = BytesIO()
    paragraphs = ''.join(f'<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>' for line in lines)
    with ZipFile(data, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{paragraphs}</w:body></w:document>')
    return data.getvalue()

def pdf_with_contact(encrypted=False, text=True):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=400)
    if text:
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 20 350 Td (Name: Alice Chen) Tj 0 -20 Td (Phone: 13800138000) Tj ET')
        page[NameObject('/Contents')] = stream
    if encrypted:
        writer.encrypt('test-password')
    data = BytesIO(); writer.write(data)
    return data.getvalue()

def test_labeled_fields_and_table_layout():
    text = '姓名：张小禾 电话：+86 138-0013-8000\n学校：清河大学 专业：计算机科学与技术\n学历：本科'
    fields, warnings = extract_fields(text)
    assert {key: f['value'] for key, f in fields.items()} == {'name': '张小禾', 'phone': '13800138000', 'school': '清河大学', 'major': '计算机科学与技术', 'education': '本科'}
    assert not warnings
    result = parse_resume(docx(['姓名', '张小禾', '联系电话', '13800138000', '毕业院校', '清河大学', '专业', '软件工程', '学历', '大学本科']), '.docx')
    assert len(result['fields']) == 5, result
    assert result['fields']['education']['value'] == '本科'

def test_ambiguity_and_education_section():
    fields, warnings = extract_fields('电话：13800138000\n手机：13900139000\n学校：清河大学\n毕业院校：远山大学\n学历：本科\n最高学历：硕士')
    assert 'phone' not in fields and 'school' not in fields and 'education' not in fields
    assert len(warnings) == 3
    fields, warnings = extract_fields('个人简历\n13800138000\n教育背景\n2020.09-2024.06 清河大学 计算机学院 本科\n工作经历\n大学本科及以上学历岗位招聘')
    assert fields['school']['value'] == '清河大学'
    assert fields['education']['value'] == '本科'
    assert 'major' not in fields
    assert 'school' not in extract_fields('工作经历\n清河大学外包服务项目\n要求硕士学历')[0]

def test_pdf_text_blank_encryption_and_failures():
    result = parse_resume(pdf_with_contact(), '.pdf')
    assert result['fields']['phone']['value'] == '13800138000'
    assert result['fields']['name']['value'] == 'Alice Chen'
    assert 'OCR' in parse_resume(pdf_with_contact(text=False), '.pdf')['warnings'][0]
    assert '加密' in parse_resume(pdf_with_contact(encrypted=True), '.pdf')['warnings'][0]
    assert parse_resume(b'%PDF-1.4\ninvalid', '.pdf')['fields'] == {}

def test_resume_upload_preview_confirm_privacy_and_conflicts(clients):
    a, b = clients('alice'), clients('bob')
    student = a.post('/api/students', json={'name': '原姓名', 'phone': '13900139000', 'school': ''}).json()
    sid = student['id']
    body = docx(['姓名：张小禾', '电话：13800138000', '学校：清河大学', '专业：软件工程', '学历：硕士'])
    response = a.post(f'/api/students/{sid}/resumes', files={'file': ('简历.docx', body)})
    assert response.status_code == 201, response.text
    resume = response.json(); rid = resume['id']
    assert resume['extraction']['fields']['school']['value'] == '清河大学'
    # Upload only suggests values. Nothing changes until the consultant confirms.
    profile = a.get(f'/api/students/{sid}').json()
    assert profile['phone'] == '13900139000' and profile['school'] == ''
    assert b.get(f'/api/resumes/{rid}/extraction').status_code == 404
    payload = {'changes': [{'field': 'school', 'value': '清河大学', 'expected': ''}, {'field': 'major', 'value': '软件工程', 'expected': ''}]}
    assert b.post(f'/api/resumes/{rid}/apply', json=payload).status_code == 404
    result = a.post(f'/api/resumes/{rid}/apply', json=payload)
    assert result.status_code == 200, result.text
    assert result.json()['school'] == '清河大学'
    assert result.json()['phone'] == '13900139000' and result.json()['name'] == '原姓名'
    assert a.get('/api/students?q=清河大学').json()['total'] == 1
    assert b.get('/api/students?q=清河大学').json()['total'] == 0
    assert a.get(f'/api/resumes/{rid}/extraction').json()['fields']['phone']['value'] == '13800138000'
    # Re-applying a stale preview must not overwrite a later edit.
    assert a.post(f'/api/resumes/{rid}/apply', json=payload).status_code == 409
    assert a.post(f'/api/resumes/{rid}/apply', json={'changes': [{'field': 'phone', 'value': '13800138000', 'expected': ''}]}).status_code == 409
    assert a.post(f'/api/resumes/{rid}/apply', json={'changes': [{'field': 'education', 'value': '学霸', 'expected': '本科'}]}).status_code == 422
    assert a.post(f'/api/resumes/{rid}/apply', json={'changes': [{'field': 'owner_id', 'value': '3', 'expected': '2'}]}).status_code == 422
    assert a.post(f'/api/resumes/{rid}/apply', json={'changes': [{'field': 'phone', 'value': '13800138000', 'expected': '13900139000'}]}).status_code == 200
    # Existing records survive reassignment, but the previous owner loses parser access.
    admin = clients('admin')
    assert admin.put(f'/api/students/{sid}', json={'name': '张小禾', 'school': '清河大学', 'owner_id': 3}).status_code == 200
    assert a.get(f'/api/resumes/{rid}/extraction').status_code == 404
    assert b.get(f'/api/resumes/{rid}/extraction').status_code == 200
    assert any(log['action'] == '确认简历信息填补' for log in admin.get('/api/audit-logs').json()['items'])
