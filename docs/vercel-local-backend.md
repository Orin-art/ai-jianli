# Vercel 前端与本机 Docker 后端

前端在 Vercel 构建，`/api/*` 通过 `frontend/vercel.json` 转发到 ngrok，再进入本机 Docker 后端的 8000 端口。前端保持相对地址和同源 Cookie，不需要配置跨域直连。

## 本机

1. 保持 Docker Compose 运行，确认 `http://127.0.0.1:8000/api/health` 返回 `{"status":"ok"}`。
2. 在项目根目录已有的 `.env` 中设置 `COOKIE_SECURE=true`（不要覆盖其他配置），运行 `docker compose up -d --no-deps --force-recreate backend`。启用后请通过 HTTPS 入口登录，本机 HTTP 页面不适合继续测试登录。
3. 保持 `ngrok http 8000` 运行。当前公网入口为 `https://repose-dyslexic-expand.ngrok-free.dev`。

前端 API 请求与附件下载均发送 `ngrok-skip-browser-warning: 1`，避免 ngrok 免费版返回浏览器提示页。地址变更时更新 `frontend/vercel.json` 并重新部署。

## Vercel

将本地改动提交并推送到 GitHub 后，导入 `Orin-art/ai-jianli`：

- Root Directory：`frontend`
- Framework Preset：Vite
- Build Command：`npm run build`
- Output Directory：`dist`

数据库地址与 DeepSeek 密钥继续留在本机后端，不填入前端或 Vite 环境变量。

部署后检查 `/api/health`，然后使用已有账号测试登录、刷新后保持登录、退出、附件上传下载与 AI 推荐。当前只验证了本地构建与隧道连通；Vercel 转发和 Cookie 需要实际部署后验证。长时间 AI 请求也需要实际验证平台代理超时。

电脑关机、休眠、Docker 或 ngrok 停止后，线上前端的业务接口会不可用。
