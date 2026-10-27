"""Local, conservative field suggestions. Never changes student data or calls external services."""
import re
import unicodedata
from io import BytesIO
from zipfile import ZipFile
from defusedxml import ElementTree
from pypdf import PdfReader
from .ocr import run_ocr, OcrError

MAX_TEXT = 100000
LABELS = r'姓名|名字|手机号码|手机|联系电话|电话|毕业院校|毕业学校|学校|院校|所学专业|专业名称|专业|最高学历|学历|邮箱|电子邮箱|性别|年龄|出生日期|求职意向|毕业时间|姓名拼音'
FIELD_LABELS = {
    'name': r'姓名|名字|Name',
    'school': r'毕业院校|毕业学校|学校|院校',
    'major': r'所学专业|专业名称|专业',
    'education': r'最高学历|学历',
}
FIELD_NAMES = {'name': '姓名', 'phone': '电话', 'school': '学校', 'major': '专业', 'education': '学历'}
EDUCATIONS = {'博士研究生': '博士', '博士': '博士', '硕士研究生': '硕士', '硕士': '硕士', '大学本科': '本科', '本科': '本科', '学士': '本科', '大学专科': '大专', '大专': '大专', '专科': '大专', '中专': '中专', '高中': '高中及以下'}
EDU_PATTERN = '|'.join(sorted(EDUCATIONS, key=len, reverse=True))

def read_text(content, suffix):
    warnings = []
    method, retryable = 'text', False
    if suffix == '.docx':
        with ZipFile(BytesIO(content)) as archive:
            if len(archive.infolist()) > 1000 or sum(i.file_size for i in archive.infolist()) > 30 * 1024 * 1024:
                raise ValueError('oversized docx')
            root = ElementTree.fromstring(archive.read('word/document.xml'))
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            lines = [''.join(t.text or '' for t in p.findall('.//w:t', ns)) for p in root.findall('.//w:p', ns)]
            text = '\n'.join(lines)
    elif suffix == '.pdf':
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            return '', ['简历已加密，请上传未加密版本或手动填写资料。'], method, False
        if len(reader.pages) > 20:
            warnings.append('仅识别了前 20 页，请核对是否有遗漏。')
        parts = []
        scan_pages = []
        length = 0
        for i, page in enumerate(reader.pages):
            if i >= 20:
                break
            part = page.extract_text() or ''
            parts.append(part)
            if sum(c.isalnum() for c in part) < 15:
                scan_pages.append(i)
            length += len(part)
            if length >= MAX_TEXT:
                break
        if scan_pages:
            if len(scan_pages) > 5:
                warnings.append('扫描页面较多，仅对前 5 个需要识别的页面执行 OCR，其余内容请人工核对。')
            try:
                result = run_ocr(content, suffix, scan_pages[:5])
                for index, value in result['texts'].items():
                    # OCR replaces sparse/empty text only when it finds readable content.
                    if value.strip():
                        parts[int(index)] = value
                method = 'mixed' if any(parts[i].strip() for i in range(len(parts)) if i not in scan_pages) else 'ocr'
                if result.get('uncertain'):
                    warnings.append('部分图片文字置信度较低，已跳过，请对照原简历核对遗漏字段。')
            except OcrError as exc:
                warnings.append(str(exc)); retryable = True
        text = '\n'.join(parts)
    elif suffix in ('.jpg', '.jpeg', '.png'):
        method = 'ocr'
        try:
            result = run_ocr(content, suffix)
            text = result['texts'].get(0, '')
            if result.get('uncertain'):
                warnings.append('部分图片文字置信度较低，已跳过，请核对遗漏字段。')
        except OcrError as exc:
            text = ''; warnings.append(str(exc)); retryable = True
    else:
        raise ValueError('Unsupported resume format')
    if len(text) > MAX_TEXT:
        warnings.append('简历文字较长，仅识别前 100,000 个字符。')
    return text[:MAX_TEXT], warnings, method, retryable

def extract_fields(text):
    text = unicodedata.normalize('NFKC', text).replace('\r', '\n')
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines() if line.strip()]
    fields, warnings = {}, []

    def choose(field, candidates):
        distinct = {}
        for value, evidence in candidates:
            if value:
                distinct.setdefault(value, evidence)
        if len(distinct) == 1:
            value, evidence = next(iter(distinct.items()))
            fields[field] = {'value': value, 'evidence': evidence[:160]}
        elif len(distinct) > 1:
            warnings.append(f'识别到多个{FIELD_NAMES[field]}，未自动选择，请手动确认。')

    def labeled(pattern):
        found = []
        for i, line in enumerate(lines):
            if re.fullmatch(rf'(?:{pattern})\s*:?', line, re.I) and i + 1 < len(lines):
                value = lines[i + 1]
                if not re.match(rf'^(?:{LABELS})(?:\s*:|$)', value):
                    found.append((value, line + ' ' + value))
            for match in re.finditer(rf'(?:^|[\s|,;])(?:{pattern})(?:\s*:\s*|\s+)', line, re.I):
                rest = line[match.end():]
                rest = re.split(rf'\s*(?:{LABELS})\s*:', rest, maxsplit=1)[0]
                rest = re.split(r'[|;]', rest, maxsplit=1)[0].strip(' ,:')
                if not rest and i + 1 < len(lines):
                    rest = lines[i + 1]
                if rest and not re.match(rf'^(?:{LABELS})\s*:', rest):
                    found.append((rest, line + (' ' + rest if not line[match.end():] else '')))
        return found

    for field, labels in FIELD_LABELS.items():
        candidates = labeled(labels)
        if field == 'name':
            candidates = [(v, e) for v, e in candidates if re.fullmatch(r'[\u4e00-\u9fff·]{2,12}|[A-Za-z][A-Za-z .-]{1,79}', v)]
        if field == 'education':
            candidates = [(EDUCATIONS[m.group()], e) for v, e in candidates if (m := re.search(EDU_PATTERN, v))]
        if field in ('school', 'major'):
            candidates = [(v, e) for v, e in candidates if len(v) <= 200]
        choose(field, candidates)

    # Prefer explicitly labeled phone numbers, otherwise inspect the short contact header.
    phone_lines = [e for _, e in labeled(r'手机号码|手机|联系电话|电话|Phone|Mobile')]
    if not phone_lines:
        phone_lines = []
        for line in lines[:20]:
            if re.search(r'教育背景|教育经历|工作经历|项目经历', line):
                break
            phone_lines.append(line)
    phones = []
    for line in phone_lines:
        for match in re.finditer(r'(?<!\d)(?:\+?86[ -]?)?(1[3-9]\d(?:[ -]?\d){8})(?!\d)', line):
            phones.append((re.sub(r'[ -]', '', match.group(1)), line))
    choose('phone', phones)

    education_lines = []
    in_education = False
    for line in lines:
        if re.search(r'教育背景|教育经历|Education', line, re.I):
            in_education = True
        elif re.search(r'工作经历|实习经历|项目经历|专业技能|获奖经历|校园经历|工作经验|求职意向', line):
            in_education = False
        if in_education:
            education_lines.append(line)
    # Do not guess an unlabelled school from employer names or a job requirement.
    if not labeled(FIELD_LABELS['school']):
        schools = []
        for line in education_lines:
            matches = re.findall(r'[\u4e00-\u9fff·]{2,30}?(?:大学|学院|职业技术学校)', line)
            universities = [s for s in matches if s.endswith('大学')]
            schools.extend((s, line) for s in (universities or matches))
        choose('school', schools)
    if not labeled(FIELD_LABELS['education']):
        choose('education', [(EDUCATIONS[m.group()], line) for line in education_lines for m in re.finditer(EDU_PATTERN, line)])
    return fields, warnings

def parse_resume(content, suffix):
    try:
        text, warnings, method, retryable = read_text(content, suffix)
        if not text.strip():
            return {'fields': {}, 'warnings': warnings or ['未识别到清晰文字，请上传清晰、方向正确的简历或手动填写。'], 'method': method, 'retryable': retryable}
        fields, field_warnings = extract_fields(text)
        if not fields:
            field_warnings.append('未识别出明确的基础信息，请手动填写或使用带清晰字段标签的简历。')
        return {'fields': fields, 'warnings': warnings + field_warnings, 'method': method, 'retryable': retryable}
    except Exception:
        # Upload remains usable even when extraction fails. Do not log document contents.
        return {'fields': {}, 'warnings': ['简历已保存，但文字解析失败。可下载检查原文件，或手动填写资料。'], 'method': 'failed', 'retryable': True}
