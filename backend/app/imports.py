import hashlib
from io import BytesIO
from zipfile import ZipFile, BadZipFile
from datetime import date, datetime
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from pydantic import ValidationError
from fastapi import HTTPException
from .schemas import JobInput, Education, Experience
from typing import get_args

HEADERS = {'岗位名称': 'title', '公司名称': 'company', '城市': 'city', '学历要求': 'education', '经验要求': 'experience', '专业要求': 'major', '最低月薪（元）': 'salary_min', '最高月薪（元）': 'salary_max', '岗位描述': 'description', '来源': 'source', '截止日期': 'expires_on'}
MAX_ROWS = 2000

def fingerprint(data):
    values = [str(data[k]).strip().casefold() for k in ('title', 'company', 'city')]
    return hashlib.sha256('\x1f'.join(values).encode()).hexdigest()

def safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value

def workbook_bytes(headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = '岗位'
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='257763')
    for row in rows:
        ws.append([safe_cell(x) for x in row])
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 22
    output = BytesIO()
    wb.save(output)
    return output.getvalue()

def template_bytes():
    wb = load_workbook(BytesIO(workbook_bytes(list(HEADERS), [])))
    ws = wb.active
    for column, values in [('D', get_args(Education)), ('E', get_args(Experience))]:
        validation = DataValidation(type='list', formula1='"' + ','.join(values) + '"', allow_blank=True)
        validation.errorTitle = '请选择约定值'
        validation.error = '请使用下拉列表中的选项'
        validation.showErrorMessage = True
        ws.add_data_validation(validation)
        validation.add(f'{column}2:{column}2001')
    for column in ('A', 'B', 'C'):
        ws[f'{column}1'].comment = Comment('必填；不要修改表头。相同岗位名称、公司和城市被视为重复。', '知途')
    for column in ('G', 'H'):
        ws[f'{column}1'].comment = Comment('可留空，也可只填写最低或最高月薪。人民币元/月，填写整数；两项都填时最低不高于最高。不支持公式。', '知途')
    ws['K1'].comment = Comment('可留空；格式 YYYY-MM-DD 或 Excel 日期。', '知途')
    result = BytesIO(); wb.save(result)
    return result.getvalue()

def inspect_xlsx(content):
    try:
        with ZipFile(BytesIO(content)) as archive:
            if len(archive.infolist()) > 100 or sum(x.file_size for x in archive.infolist()) > 50 * 1024 * 1024:
                raise HTTPException(400, 'Excel 解压后过大或文件结构过于复杂')
        wb = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
    except (BadZipFile, ValueError, KeyError, OSError):
        raise HTTPException(400, '文件不是有效的 .xlsx 工作簿')
    try:
        if len(wb.worksheets) != 1:
            raise HTTPException(400, '请使用只有一个工作表的导入模板')
        ws = wb.active
        # Ignore untrusted worksheet dimension metadata; enforce actual streamed limits.
        ws.reset_dimensions()
        iterator = ws.iter_rows()
        first = next(iterator, None)
        if not first or len(first) > 30:
            raise HTTPException(400, '表头为空或列数超过 30')
        headers = [str(c.value or '').strip() for c in first]
        if headers != list(HEADERS):
            raise HTTPException(400, '表头与模板不一致，请下载最新模板，保持列名和顺序不变')
        result = []
        for row_number, cells in enumerate(iterator, start=2):
            if row_number > MAX_ROWS + 1:
                raise HTTPException(400, f'每次最多导入 {MAX_ROWS} 行，请拆分文件')
            if all(c.value is None for c in cells):
                continue
            if len(cells) > len(headers) and any(c.value is not None for c in cells[len(headers):]):
                raise HTTPException(400, f'第 {row_number} 行存在模板外的数据列')
            raw = {HEADERS[h]: (cells[i].value if i < len(cells) else None) for i, h in enumerate(headers)}
            display = {k: v.isoformat() if isinstance(v, (date, datetime)) else str(v) if v is not None else '' for k, v in raw.items()}
            errors = []
            if any(c.data_type == 'f' for c in cells):
                errors.append('不支持公式，请先粘贴为数值或文本')
            data = {}
            for key, value in raw.items():
                if value is None or str(value).strip() == '':
                    continue
                if key == 'expires_on' and isinstance(value, datetime):
                    value = value.date()
                data[key] = value if key in ('salary_min', 'salary_max', 'expires_on') else str(value).strip()
            try:
                job = JobInput.model_validate(data)
                payload = job.model_dump(mode='json')
            except ValidationError as exc:
                names = {v: k for k, v in HEADERS.items()}
                errors.extend(f"{names.get(str(e['loc'][0]), '岗位') if e['loc'] else '岗位'}：{e['msg']}" for e in exc.errors())
                payload = display
            result.append({'row_number': row_number, 'data': payload, 'errors': errors, 'state': '错误' if errors else '可导入'})
        if not result:
            raise HTTPException(400, '工作表没有岗位数据')
        return result
    finally:
        wb.close()
