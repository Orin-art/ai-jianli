"""Explainable candidate sorting; missing information never proves suitability."""
import re
import unicodedata

EDUCATION = {'高中及以下': 1, '中专': 1, '大专': 2, '本科': 3, '硕士': 4, '博士': 5}
MATCH_LIMIT = 5


def normalized(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value or '').casefold())


def choices(value):
    # Whitespace inside a name (e.g. Java 开发) is not an alternative separator.
    return [normalized(v) for v in re.split(r'[,，、;；/|\n]+', value or '') if normalized(v)]


def city_name(value):
    value = normalized(value)
    return value[:-1] if value.endswith('市') else value


def match_job(student, job):
    reasons, warnings = [], []
    priority = 0
    cities = choices(student.target_city)
    if not cities:
        return None
    if cities and not any(c in ('不限', '全国') for c in cities):
        if not any(city_name(c) == city_name(j) for c in cities for j in choices(job.city)):
            return None
        reasons.append('城市符合意向')
        priority += 4
    else:
        reasons.append('学员意向城市不限')

    if job.education == '不限':
        reasons.append('岗位学历不限')
    elif student.education not in EDUCATION or job.education not in EDUCATION:
        return None
    elif EDUCATION[student.education] < EDUCATION[job.education]:
        return None
    elif student.education != job.education and EDUCATION[student.education] == EDUCATION[job.education] == 1:
        return None
    else:
        reasons.append('学历满足要求')
        priority += 1

    roles = choices(student.target_role)
    if not roles:
        return None
    elif any(len(r) >= 2 and r in normalized(job.title) for r in roles):
        reasons.append('岗位名称包含意向关键词')
        priority += 8
    else:
        return None

    major = normalized(job.major)
    if not major:
        return None
    elif major in ('不限', '专业不限', '不限专业', '无专业限制'):
        reasons.append('岗位专业不限')
    elif not normalized(student.major):
        return None
    elif any(word in major for word in ('非', '除外', '不含', '不接受', '不招')):
        return None
    elif any(len(m) >= 2 and m in normalized(student.major) for m in choices(job.major)):
        # Even a literal overlap is evidence, not proof of eligibility (e.g. exclusions).
        reasons.append('专业文本有重合')
        warnings.append('专业要求需结合原文核对')
        priority += 2
    else:
        return None

    if job.experience != '不限':
        warnings.append(f'经验要求为{job.experience}，学员经验需核对')
    if job.salary_min is None and job.salary_max is None:
        warnings.append('岗位薪资未填写')
    else:
        warnings.append('学员薪资期望尚未记录，需确认薪资')
    return {'reasons': reasons, 'warnings': warnings, 'priority': priority}
