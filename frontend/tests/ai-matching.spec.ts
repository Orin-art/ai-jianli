import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { delimiter, resolve } from 'node:path'

test('AI推荐页面：未配置提示、发送同意、失败重试、依据核对和手动推荐（模拟模型响应）', async ({ page }, testInfo) => {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  let configured = false, vectorReady = true, calls = 0
  await page.route('**/api/ai/status', route => route.fulfill({ json: { configured, provider: 'DeepSeek', model: 'deepseek-flash', max_results: 5, retrieval: { ready: vectorReady, engine: 'Qdrant', indexed_jobs: 120, message: '向量服务暂不可用' } } }))
  await page.goto('/')
  await page.getByLabel('账号', { exact: true }).fill('e2e-admin')
  await page.getByLabel('密码', { exact: true }).fill('E2e-Only-Password-123')
  await page.getByRole('button', { name: '进入工作台' }).click()
  await expect(page.getByRole('heading', { name: '工作概览', exact: true })).toBeVisible()
  const unique = Date.now().toString(), headers = { 'X-Requested-With': 'career-web' }
  const file = testInfo.outputPath('ai-jobs.xlsx')
  execFileSync(resolve('../.venv/Scripts/python.exe'), ['-c', `from openpyxl import Workbook; from app.imports import HEADERS; w=Workbook(); s=w.active; s.append(list(HEADERS)); s.append(['软件工程师-${unique}','AI测试公司','上海','大专','不限','计算机',8000,12000,'使用 Python 和 FastAPI 开发后端接口','测试来源']); w.save(${JSON.stringify(file)})`], { env: { ...process.env, PYTHONPATH: resolve('../backend') } })
  const batch = await (await page.request.post('/api/imports/preview', { headers, multipart: { file: { name: 'ai-jobs.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: readFileSync(file) } } })).json()
  expect((await page.request.post(`/api/imports/${batch.id}/commit`, { headers })).ok()).toBeTruthy()
  const job = (await (await page.request.get(`/api/jobs?q=${encodeURIComponent('软件工程师-' + unique)}`)).json()).items[0]
  const student = await (await page.request.post('/api/students', { headers, data: { name: `AI学员${unique}`, education: '本科', major: '计算机科学', target_city: '上海', target_role: '后端开发' } })).json()
  const resumeFile = testInfo.outputPath('ai-resume.docx')
  execFileSync(resolve('../.venv/Scripts/python.exe'), ['-c', `from pathlib import Path; from test_resume_parser import docx; Path(${JSON.stringify(resumeFile)}).write_bytes(docx(['专业技能：熟悉 Python 和 FastAPI，使用 PostgreSQL 构建后端接口。','项目经历：开发校园管理系统，实现登录权限和数据分页。']))`], { env: { ...process.env, PYTHONPATH: `${resolve('../backend')}${delimiter}${resolve('../backend/tests')}` } })
  const resume = await (await page.request.post(`/api/students/${student.id}/resumes`, { headers, multipart: { file: { name: 'ai-resume.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', buffer: readFileSync(resumeFile) } } })).json()
  await page.route(`**/api/students/${student.id}/ai-matched-jobs`, async route => {
    calls++
    expect(route.request().postDataJSON()).toEqual({ resume_id: resume.id, consent: true })
    if (calls === 1) { await route.fulfill({ status: 504, json: { detail: '连接 DeepSeek 超时，请重试' } }); return }
    await route.fulfill({ json: { provider: 'DeepSeek', model: 'deepseek-flash', configured: true, resume_id: resume.id, generated_at: '2026-10-26T09:00:00', considered: 1, retrieval: { engine: 'Qdrant', eligible_jobs: 100, retrieved_jobs: 1 },
      analysis: { summary: '具备 Python 后端项目经历', skills: [{ value: 'Python', evidence: '熟悉 Python 和 FastAPI' }], experience: [], education: null, major: null, target_roles: ['软件工程师'], warnings: ['未提供全职工作年限'] }, warnings: [], explanation: '按技能与职责匹配。',
      items: [{ ...job, job_id: job.id, reason: '项目技术与岗位职责相关', resume_evidence: '熟悉 Python 和 FastAPI', job_evidence: '使用 Python 和 FastAPI 开发后端接口', gaps: ['需核对专业要求'] }] } })
  })
  async function openProfile() {
    await page.getByRole('button', { name: '学员与跟进', exact: true }).click()
    await page.getByRole('button', { name: student.name, exact: true }).click()
  }
  await openProfile()
  const ai = page.getByRole('region', { name: 'AI简历岗位推荐' })
  await expect(ai).toContainText('AI 服务尚未配置')
  await expect(ai.getByRole('button', { name: '分析简历并推荐岗位' })).toBeDisabled()
  expect(calls).toBe(0)
  configured = true
  vectorReady = false
  await page.reload()
  await openProfile()
  await expect(ai).toContainText('向量服务暂不可用')
  await expect(ai.getByRole('button', { name: '分析简历并推荐岗位' })).toBeDisabled()
  vectorReady = true
  await ai.getByRole('button', { name: '刷新检索状态' }).click()
  await expect(ai).toContainText('已索引 120 个岗位')
  await expect(ai.getByRole('button', { name: '分析简历并推荐岗位' })).toBeDisabled()
  await ai.getByText('同意将上述内容发送给 DeepSeek 分析', { exact: true }).click()
  await expect(ai.getByRole('checkbox', { name: '同意将上述内容发送给 DeepSeek 分析' })).toBeChecked()
  await ai.getByRole('button', { name: '分析简历并推荐岗位' }).click()
  await expect(ai.getByRole('alert')).toContainText('连接 DeepSeek 超时')
  await ai.getByRole('button', { name: '分析简历并推荐岗位' }).click()
  await expect(ai.locator('.ai-card')).toHaveCount(1)
  await expect(ai).toContainText('从 100 个符合基本条件的岗位中召回 1 个')
  await ai.getByText('查看简历分析依据', { exact: true }).click()
  await expect(ai).toContainText('熟悉 Python 和 FastAPI')
  const before = await (await page.request.get(`/api/students/${student.id}`)).json()
  expect(before.recommendations).toHaveLength(0)
  await ai.locator('.ai-card').getByRole('button', { name: '不采用', exact: true }).click()
  await expect(ai.locator('.ai-card')).toHaveCount(0)
  await expect(ai).toContainText('本次已不采用 1 个岗位')
  expect((await (await page.request.get(`/api/students/${student.id}`)).json()).recommendations).toHaveLength(0)
  expect(calls).toBe(2)
  await ai.getByRole('button', { name: '撤销上一次', exact: true }).click()
  await expect(ai.locator('.ai-card')).toHaveCount(1)
  await page.screenshot({ path: '../artifacts/ai-matched-jobs-mock.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await ai.evaluate(el => el.scrollWidth > el.clientWidth + 1)).toBeFalsy()
  await ai.getByRole('button', { name: '核对 AI 推荐' }).click()
  const dialog = page.getByRole('dialog', { name: '核对 AI 推荐', exact: true })
  await expect(dialog).toContainText('使用 Python 和 FastAPI 开发后端接口')
  await dialog.getByRole('button', { name: '不采用', exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(ai.locator('.ai-card')).toHaveCount(0)
  await ai.getByRole('button', { name: '撤销上一次', exact: true }).click()
  await ai.getByRole('button', { name: '核对 AI 推荐' }).click()
  await dialog.getByRole('button', { name: `确认推荐给${student.name}`, exact: true }).click()
  await expect(dialog).not.toBeVisible()
  await expect(ai).toContainText('当前没有可确认的 AI 候选')
  const after = await (await page.request.get(`/api/students/${student.id}`)).json()
  expect(after.recommendations).toHaveLength(1)
  expect(after.recommendations[0].job_id).toBe(job.id)
  expect(calls).toBe(2)
  expect(errors).toEqual([])
})
