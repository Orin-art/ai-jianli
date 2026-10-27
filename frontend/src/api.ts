export async function api(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers)
  headers.set('X-Requested-With', 'career-web')
  headers.set('ngrok-skip-browser-warning', '1')
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'same-origin' })
  if (!response.ok) {
    let message = '请求失败，请稍后重试'
    try {
      const data = await response.json()
      message = Array.isArray(data.detail) ? data.detail.map((e: any) => `${e.loc?.slice(1).join('.') || '数据'}：${e.msg}`).join('；') : data.detail || message
    } catch { /* A proxy may return a non-JSON error. */ }
    if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') window.dispatchEvent(new Event('session-expired'))
    throw new Error(message)
  }
  return response.status === 204 ? null : response.json()
}
export async function download(path: string, name: string) {
  const response = await fetch(`/api${path}`, { credentials: 'same-origin', headers: { 'ngrok-skip-browser-warning': '1' } })
  if (!response.ok) throw new Error('下载失败，请确认登录状态和访问权限')
  const url = URL.createObjectURL(await response.blob())
  const a = document.createElement('a')
  a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url)
}
export const educations = ['不限', '高中及以下', '中专', '大专', '本科', '硕士', '博士']
export const experiences = ['不限', '应届生', '1年以下', '1-3年', '3-5年', '5年以上']
export const stages = ['已推荐', '已投递', '面试中', '已录用', '未通过', '已放弃']
export function salary(j: any) {
  if (j.salary_min == null && j.salary_max == null) return '薪资待确认'
  if (j.salary_min == null) return `最高 ¥${j.salary_max.toLocaleString()}`
  if (j.salary_max == null) return `最低 ¥${j.salary_min.toLocaleString()}`
  return `¥${j.salary_min.toLocaleString()} – ${j.salary_max.toLocaleString()}`
}
export function time(value: string) { return value ? new Date(value + (value.endsWith('Z') ? '' : 'Z')).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—' }
