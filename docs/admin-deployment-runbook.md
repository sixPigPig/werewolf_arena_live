# Admin Web 发布与回滚 Runbook

本文覆盖 API、`admin-web` 和持久语音 worker 的生产发布。`mobile-web` 是唯一 C 端；旧 `apps/web` 只保留迁移期兼容能力。

## 发布前置条件

1. OIDC 提供商已注册 confidential client，允许 Authorization Code、PKCE S256，并精确登记 callback；在真实账号验收完成前不要开放 production Admin 入口。
2. PostgreSQL 已创建独立数据库和最小权限账号，数据库与对象备份已验证可恢复。
3. API、Admin 和 Mobile 使用 HTTPS 同源或明确的 HTTPS allowlist；反向代理保留 Cookie、Origin 和 WebSocket/SSE 语义。
4. `apps/web/public/judge-voice` 至少保留两个发布周期，作为数据库语音资产的回滚输入。

生产配置必须显式设置：

```dotenv
APP_ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/<database>
CORS_ORIGINS=https://admin.example.com,https://m.example.com
PUBLIC_CORS_ORIGINS=https://m.example.com
ADMIN_DEV_AUTH_ENABLED=false
ADMIN_SESSION_COOKIE_SECURE=true
PUBLIC_SESSION_COOKIE_SECURE=true
ADMIN_OIDC_ENABLED=true
ADMIN_OIDC_ISSUER_URL=https://identity.example.com/realms/werewolf
ADMIN_OIDC_CLIENT_ID=werewolf-admin
ADMIN_OIDC_CLIENT_SECRET=<secret-manager-reference>
ADMIN_OIDC_REDIRECT_URI=https://api.example.com/api/v1/admin/oidc/callback
ADMIN_OIDC_WEB_BASE_URL=https://admin.example.com
ADMIN_OIDC_CLIENT_AUTH_METHOD=client_secret_basic
JUDGE_VOICE_WORKER_POLL_SECONDS=2
```

不要把密钥写入仓库、镜像或前端 `VITE_*` 变量。正式 TTS 密钥只注入 API 与 worker 运行环境。

提供商必须在 ID Token 中返回 `iss`、`sub`、`aud`、`iat`、`exp`、`nonce`、`email` 和布尔值 `email_verified=true`。API 只接受 RS/ES 非对称签名算法，并在未知 `kid` 时刷新 JWKS。后台角色完全来自本地预配置，不读取 OIDC group/role claim。

每个后台人员首次登录前执行：

```bash
cd apps/api
.venv/bin/python -m app.cli provision-admin-user \
  --email operator@example.com \
  --display-name "Operations User" \
  --role operator
```

邮箱必须与提供商验证后的 claim 一致。首次成功登录会绑定 issuer/sub；更换身份租户或 subject 时不得直接复用旧绑定，应先进行独立身份迁移评审。

## 发布门禁

在已安装依赖且连接到已迁移测试数据库的工作区执行：

```bash
make release-check
cd apps/api
.venv/bin/alembic current
.venv/bin/alembic heads
```

`current` 必须与 `heads` 一致。CI 会在全新 PostgreSQL 上执行 `upgrade head`、`alembic check`、全量测试和前端生产构建。

## 数据库与资产展开

先备份，再执行可向前兼容迁移：

```bash
cd apps/api
.venv/bin/alembic upgrade head
.venv/bin/alembic check
.venv/bin/python -m app.cli import-judge-voice-assets \
  --source ../web/public/judge-voice
```

资产导入幂等，可重复运行。确认导入数量、缺失数与字节数后再切换应用版本。不要在已有新版本写入后直接执行 Alembic downgrade。

## 进程拓扑

当前实时对局注册表仍在 API 进程内，因此生产只运行一个 API worker：

```bash
cd apps/api
.venv/bin/python -m app.cli serve --host 0.0.0.0 --port 8000
```

语音生成使用独立、由进程管理器自动拉起的持续进程：

```bash
cd apps/api
.venv/bin/python -m app.cli run-judge-voice-worker
```

发布停止时先从负载均衡摘除 API，再发送 SIGTERM；worker 收到 SIGTERM 后不会领取新任务，并在当前任务返回后退出。进程管理器应使用有限退避重启，避免数据库故障时形成快速重启循环。

Admin 静态产物由 `pnpm --dir apps/admin-web build` 生成到 `apps/admin-web/dist`。Web 服务器必须把未知页面路由回退到 `index.html`，把 `/api` 反向代理至 API，并禁止缓存 Admin HTML；带哈希的静态资源可长期缓存。

## 健康探针与发布冒烟

- 存活探针：`GET /api/v1/health/live`，期望 200 `{"status":"ok"}`。
- 就绪探针：`GET /api/v1/health/ready`，只在数据库可连接且位于 Alembic head 时返回 200；其他情况返回 503。
- 旧 `/api/v1/health` 只为兼容保留，不能用于接流量判断。

发布后检查：

1. 未登录访问 Admin 受保护路由会跳转登录，不出现 fixture 数据，并显示“使用企业账号登录”。
2. 使用已预配置的正式低权限账号完成提供商跳转、callback 和 `/admin/me`，导航和深链权限一致；未预配置账号必须被拒绝。
3. 玩家列表、对局记录、运行监控和语音资产均读取真实 API。
4. 使用有权限账号排队一个“生成缺失”任务，确认 worker 日志出现 job ID、页面进入终态且审计只有一次。
5. Mobile 大厅、玩家图鉴、收藏、开局和观战走 `mobile-web`；不要把旧 Web 暴露为新 C 端入口。

## 回滚

优先回滚应用，不回滚数据库：

1. 从负载均衡摘除新 API，停止新 worker，保留 queued/running 任务记录。
2. 恢复上一版 API、Admin 和 Mobile 制品；上一版必须在发布前验证可读取扩展后的 schema。
3. 检查 `/health/ready`，再逐步恢复流量。
4. 语音数据库读取异常时保留新表，恢复上一版应用并使用旧静态目录；不要删除资产表或旧文件。
5. 只有在确认没有新版本写入且备份可恢复时，才单独评审数据库 downgrade。

若数据库不可用或迁移落后，保持 readiness 为 503 并停止发布；若 worker 不可用，API 可继续提供只读资产和排队能力，但必须告警 queued 任务积压，恢复 worker 后由持久队列继续处理。
