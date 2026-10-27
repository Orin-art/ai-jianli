import { test, expect } from '@playwright/test'

test('唯一主账号创建顾问、查看团队情况并交接学员，顾问权限隔离', async ({ page }, testInfo) => {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  const unique = Date.now().toString(), first = `advisor-a-${unique}`, second = `advisor-b-${unique}`
  const firstName = `顾问甲-${unique}`, secondName = `顾问乙-${unique}`, studentName = `团队学员-${unique}`
  const password = 'E2e-Advisor-Password-123'
  const headers = { 'X-Requested-With': 'career-web' }
  const login = async (username: string, secret: string) => {
    await page.getByLabel('账号', { exact: true }).fill(username)
    await page.getByLabel('密码', { exact: true }).fill(secret)
    await page.getByRole('button', { name: '进入工作台' }).click()
    await expect(page.getByRole('heading', { name: '工作概览', exact: true })).toBeVisible()
  }
  await page.goto('/')
  await login('e2e-admin', 'E2e-Only-Password-123')
  await expect(page.locator('.user-block')).toContainText('主账号')
  await page.getByRole('button', { name: '顾问管理', exact: true }).click()
  for (const [username, name] of [[first, firstName], [second, secondName]]) {
    await page.getByRole('button', { name: '新增顾问', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '新增顾问账号' })
    await dialog.getByLabel('姓名', { exact: true }).fill(name)
    await dialog.getByLabel('账号（3～64 位字母、数字、点、横线或下划线）').fill(username)
    await dialog.getByLabel('初始密码（至少 10 位）').fill(password)
    await dialog.getByRole('button', { name: '创建账号', exact: true }).click()
    await expect(dialog).not.toBeVisible()
    await expect(page.getByRole('row').filter({ hasText: username })).toContainText('求职顾问')
  }
  const accounts = await (await page.request.get('/api/users')).json()
  const firstId = accounts.find((u: any) => u.username === first).id
  const secondId = accounts.find((u: any) => u.username === second).id
  const primaryId = accounts.find((u: any) => u.role === 'admin').id
  expect(accounts.filter((u: any) => u.role === 'admin')).toHaveLength(1)
  const studentResponse = await page.request.post('/api/students', { headers, data: { name: studentName, school: '交接验证大学', owner_id: firstId } })
  expect(studentResponse.ok()).toBeTruthy()
  const sid = (await studentResponse.json()).id
  expect((await page.request.post(`/api/students/${sid}/followups`, { headers, data: { content: '交接历史记录', next_date: '2020-01-01' } })).ok()).toBeTruthy()
  await page.getByRole('button', { name: '刷新数据' }).click()
  const firstRow = page.getByRole('row').filter({ hasText: first })
  await expect(firstRow.locator('td').nth(4)).toHaveText('1')
  await expect(firstRow.locator('td').nth(6)).toHaveText('1')
  await page.screenshot({ path: testInfo.outputPath('team-overview.png'), fullPage: true })
  await firstRow.getByRole('button', { name: '查看学员', exact: true }).click()
  const studentRow = page.getByRole('row').filter({ hasText: studentName })
  await expect(studentRow).toContainText(firstName)
  await studentRow.getByRole('button', { name: '分配顾问' }).click()
  const assignment = page.getByRole('dialog', { name: '分配负责顾问' })
  await assignment.locator('.el-select').click()
  await page.getByRole('option', { name: `${secondName}（${second}）`, exact: true }).click()
  await assignment.getByRole('button', { name: '确认分配' }).click()
  await expect(assignment).not.toBeVisible()
  await expect(studentRow).toHaveCount(0)
  await page.getByRole('button', { name: '退出登录' }).click()
  await login(first, password)
  await expect(page.getByRole('button', { name: '顾问管理', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '学员与跟进', exact: true }).click()
  await expect(studentRow).toHaveCount(0)
  expect((await page.request.get(`/api/students/${sid}`)).status()).toBe(404)
  expect((await page.request.post('/api/users', { headers, data: { username: `blocked-${unique}`, name: '越权', password } })).status()).toBe(403)
  expect((await page.request.patch(`/api/students/${sid}/owner`, { headers, data: { owner_id: firstId, expected_owner_id: secondId } })).status()).toBe(403)
  await page.getByRole('button', { name: '退出登录' }).click()
  await login(second, password)
  await page.getByRole('button', { name: '学员与跟进', exact: true }).click()
  await expect(studentRow).toContainText('交接验证大学')
  await expect(studentRow.getByRole('button', { name: '分配顾问' })).toHaveCount(0)
  await studentRow.getByRole('button', { name: '查看档案' }).click()
  await expect(page.locator('.timeline-card')).toContainText('交接历史记录')
  await page.locator('.el-drawer:visible .el-drawer__close-btn').click()
  await page.getByRole('button', { name: '退出登录' }).click()
  await login('e2e-admin', 'E2e-Only-Password-123')
  expect((await page.request.get(`/api/students/${sid}`)).ok()).toBeTruthy()
  expect((await page.request.patch(`/api/users/${primaryId}`, { headers, data: { active: false } })).status()).toBe(400)
  expect(errors).toEqual([])
})
