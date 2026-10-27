from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

Education = Literal['不限', '高中及以下', '中专', '大专', '本科', '硕士', '博士']
Experience = Literal['不限', '应届生', '1年以下', '1-3年', '3-5年', '5年以上']
Stage = Literal['已推荐', '已投递', '面试中', '已录用', '未通过', '已放弃']

class Input(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')

class LoginInput(Input):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

class UserInput(Input):
    username: str = Field(pattern=r'^[A-Za-z0-9_.-]{3,64}$')
    name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=128)

class UserPatch(Input):
    active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=128)

class JobInput(Input):
    title: str = Field(min_length=1, max_length=160)
    company: str = Field(min_length=1, max_length=160)
    city: str = Field(min_length=1, max_length=80)
    education: Education = '不限'
    experience: Experience = '不限'
    major: str = Field(default='', max_length=200)
    salary_min: int | None = Field(default=None, ge=0, le=1000000)
    salary_max: int | None = Field(default=None, ge=0, le=1000000)
    description: str = Field(default='', max_length=10000)
    source: str = Field(default='', max_length=300)
    expires_on: date | None = None
    status: Literal['有效', '失效'] = '有效'

    @model_validator(mode='after')
    def salary_range(self):
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError('最低月薪不能高于最高月薪')
        return self

class StudentInput(Input):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(default='', max_length=40)
    school: str = Field(default='', max_length=200)
    education: Education = '本科'
    major: str = Field(default='', max_length=200)
    target_city: str = Field(default='', max_length=100)
    target_role: str = Field(default='', max_length=200)
    status: Literal['服务中', '已入职', '已结束'] = '服务中'
    notes: str = Field(default='', max_length=10000)
    owner_id: int | None = None

class ProfileChange(Input):
    field: Literal['name', 'phone', 'school', 'major', 'education']
    value: str = Field(min_length=1, max_length=200)
    expected: str = Field(max_length=200)

class ResumeApplyInput(Input):
    changes: list[ProfileChange] = Field(min_length=1, max_length=5)

class RecommendationInput(Input):
    job_id: int

class AIRecommendationInput(Input):
    resume_id: int = Field(gt=0)
    consent: Literal[True]

class FollowupInput(Input):
    recommendation_id: int | None = None
    stage: Literal['沟通', '已推荐', '已投递', '面试中', '已录用', '未通过', '已放弃'] = '沟通'
    content: str = Field(min_length=1, max_length=5000)
    next_date: date | None = None
