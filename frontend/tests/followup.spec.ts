import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { readFileSync } from 'node:fs'

test('跟进时间线展示岗位，档案和首页处理后到期提醒持续隐藏', async ({ page }, testInfo) => {
  const headers = { 'X-Requested-With': 'career-web' }
  expect((await page.request.post('/api/auth/login', { headers, data: { username: 'e2e-admin', password: 'E2e-Only-Password-123' } })).ok()).toBeTruthy()
  const unique = Date.now().toString(), name = `跟进验证-${unique}`, title = `推荐岗位-${unique}`
  const file = testInfo.outputPath('followup-jobs.xlsx')
  execFileSync(resolve('../.venv/Scripts/python.exe'), ['-c', `from openpyxl import Workbook; from app.imports import HEADERS; w=Workbook(); s=w.active; s.append(list(HEADERS)); s.append(['${title}','跟进测试公司','上海']); w.save(${JSON.stringify(file)})`], { env: { ...process.env, PYTHONPATH: resolve('../backend') } })
  const batch = await (await page.request.post('/api/imports/preview', { headers, multipart: { file: { name: 'followup-jobs.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: readFileSync(file) } } })).json()
  expect((await page.request.post(`/api/imports/${batch.id}/commit`, { headers })).ok()).toBeTruthy()
  const job = (await (await page.request.get(`/api/jobs?q=${encodeURIComponent(title)}`)).json()).items[0]
  const student = await (await page.request.post('/api/students', { headers, data: { name } })).json()
  const url = `/api/students/${student.id}`
  const rec = await (await page.request.post(url + '/recommendations', { headers, data: { job_id: job.id } })).json()
  const followup = async (content: string) => {
    const response = await page.request.post(url + '/followups', { headers, data: { recommendation_id: rec.id, stage: '面试中', content, next_date: '2020-01-01' } })
    expect(response.ok()).toBeTruthy()
  }
  await followup('旧事件')
  await followup('档案处理的事件')
  await page.goto('/')
  const row = page.getByRole('row').filter({ hasText: name })
  await expect(row).toContainText(title)
  await row.getByRole('button', { name: '去跟进' }).click()
  const card = page.locator('.timeline-card').filter({ hasText: '档案处理的事件' })
  await expect(card).toContainText(title)
  await expect(card).toContainText('跟进测试公司')
  await card.getByRole('button', { name: '已处理', exact: true }).click()
  await expect(card.locator('.el-tag--success')).toHaveText('已处理')
  await expect(card.getByRole('button', { name: '已处理', exact: true })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('timeline-handled.png'), fullPage: true })
  await page.locator('.el-drawer:visible .el-drawer__close-btn').click()
  await expect(row).toHaveCount(0)
  await page.reload()
  await expect(row).toHaveCount(0)
  await followup('首页处理的事件')
  await page.reload()
  await expect(row).toContainText('首页处理的事件')
  await row.getByRole('button', { name: '已处理', exact: true }).click()
  await expect(row).toHaveCount(0)
  await page.reload()
  await expect(row).toHaveCount(0)
  await page.getByRole('button', { name: '学员与跟进', exact: true }).click()
  await page.getByRole('button', { name, exact: true }).click()
  await expect(page.locator('.timeline-card').filter({ hasText: '首页处理的事件' }).locator('.el-tag--success')).toHaveText('已处理')
  await expect(page.locator('.timeline-card').filter({ hasText: '旧事件' }).getByRole('button', { name: '已处理', exact: true })).toBeVisible()
})
