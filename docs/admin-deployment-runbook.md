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
ADMIN_OIDC_REDIRECT_URI=https://admin.example.com/api/v1/admin/oidc/callback
ADMIN_OIDC_WEB_BASE_URL=https://admin.example.com
ADMIN_OIDC_CLIENT_AUTH_METHOD=client_secret_basic
JUDGE_VOICE_WORKER_POLL_SECONDS=2
LIVE_RUN_REAPER_POLL_SECONDS=5
LIVE_RUN_REAPER_STALE_GRACE_SECONDS=30
LIVE_RUN_REAPER_BACKOFF_SECONDS=30
LIVE_RUN_REAPER_MAX_ATTEMPTS=3
LIVE_RUN_REAPER_HEARTBEAT_SECONDS=10
LIVE_RUN_REAPER_PROBE_MAX_AGE_SECONDS=45
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

CLI 用于首位超级管理员引导和后台不可用时的恢复。首位超级管理员登录后，应使用 `/system/users` 管理后续账号：创建操作带幂等键，修改操作带数据库版本，停用会立即撤销该账号的全部活动会话。`/system/audit` 用于核对成功和被拒绝的账号操作；普通 DTO 不包含审计 before/after、IP、OIDC subject、Cookie 或 token。

## 发布门禁

在已安装依赖且连接到已迁移测试数据库的工作区执行：

```bash
make release-check
cd apps/api
.venv/bin/alembic current
.venv/bin/alembic heads
```

`current` 必须与 `heads` 一致。CI 会在全新 PostgreSQL 上执行 `upgrade head`、`alembic check`、全量测试和前端生产构建。

## 容器制品

API、迁移任务、语音 worker 和 live-run reaper 共用 `apps/api/Dockerfile`；Admin 使用 `apps/admin-web/Dockerfile` 的 `runtime` 阶段。镜像构建不会写入 `.env`、密钥、日志、虚拟环境或 `node_modules`：

```bash
docker build -f apps/api/Dockerfile -t ghcr.io/sixpigpig/werewolf-api:<git-sha> .
docker build -f apps/admin-web/Dockerfile --target runtime \
  -t ghcr.io/sixpigpig/werewolf-admin-web:<git-sha> .
```

Admin 正式镜像固定启用认证、关闭 fixture preview 和开发登录；浏览器使用同源 `/api`，Nginx 通过 `API_UPSTREAM` 连接 API。OIDC、数据库和 TTS 密钥只能在运行时注入 API 镜像，不可放入 Admin 构建参数。

本地完整联调栈使用 Admin Dockerfile 的 `development` 阶段，提供开发身份登录，不代表生产认证验收：

```bash
make stack-up
docker compose --profile app ps
curl --fail http://127.0.0.1:8080/
curl --fail http://127.0.0.1:8000/api/v1/health/ready
```

访问 `http://127.0.0.1:8080`。启动监控或语音 worker 时使用：

```bash
docker compose --profile app --profile monitoring up --build -d
docker compose --profile app --profile voice up --build -d
```

Prometheus 位于 `http://127.0.0.1:19090`（可通过 `PROMETHEUS_PORT` 修改）。`API_ENV_FILE` 可指向额外的本地环境文件；Compose 中显式的数据库和本地认证设置会覆盖同名值。

### CI 镜像发布

`.github/workflows/ci.yml` 在 API、Admin、Mobile、旧 Web 和部署清单全部通过后构建两个正式镜像。Pull Request 只构建不推送；`main` 和 `v*` tag 会使用 `GITHUB_TOKEN` 推送到 GHCR，并生成 provenance 与 SBOM：

- `ghcr.io/sixpigpig/werewolf-api:sha-<40位提交SHA>`
- `ghcr.io/sixpigpig/werewolf-admin-web:sha-<40位提交SHA>`
- `main` 是便于观察的移动标签，`v*` 是发布别名；部署脚本只接受完整提交 SHA 标签，拒绝 `main`、`latest` 和其他可变标签。

若 GHCR package 不公开，集群必须通过 ServiceAccount 或 `imagePullSecrets` 获得只读拉取权限。不要把 GHCR PAT 写入应用 Secret。

### Kubernetes 发布顺序

`deploy/kubernetes/base` 包含 API、单副本 reaper、Admin、Service、生产配置与探针。`overlays/staging` 使用单副本，`overlays/production` 使用三副本并增加 PodDisruptionBudget；两个 overlay 都固定 GHCR 镜像 SHA，并提供 HTTPS Ingress。

首次部署前必须完成：

1. 把对应 overlay 的 `api.env`、`ingress.yaml` 中所有 `example.com` 替换为真实域名；脚本检测到示例域名会拒绝部署。
2. 创建 Ingress 引用的 TLS Secret，或按集群证书控制器修改 Ingress 注解和 Secret 名。
3. 通过 External Secrets、Sealed Secrets 或云密钥服务，在目标 Namespace 创建 `werewolf-api-secrets`；字段示例见 `deploy/kubernetes/secret.example.yaml`，不得原样应用。
4. 确认 Nginx IngressClass 名为 `nginx`，不一致时修改 overlay。

发布脚本先创建 Namespace 和非密 ConfigMap，确认外部 Secret 存在，然后执行并等待迁移；只有迁移成功才更新应用和执行冒烟：

```bash
scripts/deploy-kubernetes.sh staging sha-<40位提交SHA> \
  --render-dir /tmp/werewolf-staging

ADMIN_BASE_URL=https://admin.staging.example.com \
  scripts/deploy-kubernetes.sh staging sha-<40位提交SHA>
```

GitHub Actions 的 `deploy` workflow 提供相同流程。仓库管理员需要创建 `staging`、`production` Environments：各环境保存 Base64 编码的 `KUBE_CONFIG_B64` Secret 和 `ADMIN_BASE_URL` Variable；如集群需要其他客户端版本，可再设置 `KUBECTL_VERSION`，默认固定为 `v1.34.1`。production 应配置必需审核人和受保护分支。workflow 只接受 `sha-<40位提交SHA>`，不会修改数据库回退版本。若要在 `main` 全部门禁和镜像发布完成后自动部署 staging，再创建仓库级 Variable `AUTO_DEPLOY_STAGING=true`；未显式开启时不会连接任何集群。

迁移 Job 名称固定；脚本会先删除上一份已完成 Job，再创建新 Job并等待。入口网关只把 Admin 域名转发到 `werewolf-admin-web:8080`，它会同源代理业务 `/api`，但明确阻断外部 `/api/v1/metrics`；Prometheus 仍从集群内部 API Service 抓取。Mobile 域名和 API 暴露策略由 C 端部署独立管理。

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

直播运行、事件、租约、控制版本和 fencing token 已持久化到 PostgreSQL，可运行多个 API 副本；每个副本只执行自己持有有效租约的模型任务：

```bash
cd apps/api
.venv/bin/python -m app.cli serve --host 0.0.0.0 --port 8000
```

语音生成使用独立、由进程管理器自动拉起的持续进程：

```bash
cd apps/api
.venv/bin/python -m app.cli run-judge-voice-worker
```

直播 orphan 恢复同样使用独立持续进程，不要在每个 API 副本内重复启动：

```bash
cd apps/api
.venv/bin/python -m app.cli run-live-run-reaper
```

systemd 模板见 `deploy/systemd/werewolf-live-run-reaper.service.example`。部署时把路径、用户和 `EnvironmentFile` 替换为实际值；进程收到 SIGTERM 后停止领取新 orphan，并等待当前恢复边界退出。

发布停止时先从负载均衡摘除 API，再发送 SIGTERM；worker 收到 SIGTERM 后不会领取新任务，并在当前任务返回后退出。进程管理器应使用有限退避重启，避免数据库故障时形成快速重启循环。

Admin 静态产物由 `pnpm --dir apps/admin-web build` 生成到 `apps/admin-web/dist`。Web 服务器必须把未知页面路由回退到 `index.html`，把 `/api` 反向代理至 API，并禁止缓存 Admin HTML；带哈希的静态资源可长期缓存。

## 健康探针与发布冒烟

- 存活探针：`GET /api/v1/health/live`，期望 200 `{"status":"ok"}`。
- 就绪探针：`GET /api/v1/health/ready`，只在数据库可连接且位于 Alembic head 时返回 200；其他情况返回 503。
- Reaper 存活探针：`python -m app.cli check-live-run-reaper`，数据库中存在新鲜心跳时退出 0，否则退出 1；数据库/参数错误退出 2。
- Prometheus：抓取 `GET /api/v1/metrics`。该端点只有聚合计数，不含运行、会话或 Worker ID，但仍应仅在内部监控网络开放。
- 旧 `/api/v1/health` 只为兼容保留，不能用于接流量判断。

Prometheus 的 Compose 采集配置见 `deploy/prometheus/prometheus.yml`，告警规则见 `deploy/prometheus/live-run-alerts.yml`，覆盖 reaper 无心跳、stale orphan 积压、自动恢复耗尽和扫描错误。Kubernetes API Pod 已带标准 `prometheus.io` 注解；集群 Prometheus 必须启用对应的 Pod discovery，或在平台侧建立等价的 PodMonitor/ServiceMonitor。发布后先运行 `python -m app.cli run-live-run-reaper --once`，再启动持续进程；持续进程启动后 `check-live-run-reaper` 必须返回 `reaper=ok`。

`scripts/smoke-admin-deployment.sh` 自动检查 Admin 健康、API live/ready、数据库迁移、未登录权限边界、metrics 外部阻断和 SPA 深链。它不代替真实 OIDC 账号验收；OIDC 登录、角色绑定和高风险后台操作仍按下方清单人工验收。

发布后检查：

1. 未登录访问 Admin 受保护路由会跳转登录，不出现 fixture 数据，并显示“使用企业账号登录”。
2. 使用已预配置的正式低权限账号完成提供商跳转、callback 和 `/admin/me`，导航和深链权限一致；未预配置账号必须被拒绝。
3. 使用超级管理员在“后台账号”开通一个测试账号，重复提交不应创建重复用户；修改角色、停用和撤销会话后，目标账号权限应立即变化。
4. 在“审计日志”按 `admin.user.create` / `admin.user.update` 筛选，确认操作者、资源、结果和请求编号存在，且响应不包含 OIDC subject、IP、before/after 或凭据。
5. 玩家列表、对局记录、运行监控和语音资产均读取真实 API。
6. 使用有权限账号排队一个“生成缺失”任务，确认 worker 日志出现 job ID、页面进入终态且审计只有一次。
7. 检查 `/metrics` 中 `werewolf_live_run_reaper_up 1`，并确认 Admin 对 stale/退避/耗尽状态的展示与数据库一致。
8. Mobile 大厅、玩家图鉴、收藏、开局和观战走 `mobile-web`；不要把旧 Web 暴露为新 C 端入口。

## 回滚

优先回滚应用，不回滚数据库：

1. 从负载均衡摘除新 API，停止新 worker，保留 queued/running 任务记录。
2. 恢复上一版 API、Admin 和 Mobile 制品；上一版必须在发布前验证可读取扩展后的 schema。
3. 检查 `/health/ready`，再逐步恢复流量。
4. 语音数据库读取异常时保留新表，恢复上一版应用并使用旧静态目录；不要删除资产表或旧文件。
5. 只有在确认没有新版本写入且备份可恢复时，才单独评审数据库 downgrade。

若数据库不可用或迁移落后，保持 readiness 为 503 并停止发布；若 worker 不可用，API 可继续提供只读资产和排队能力，但必须告警 queued 任务积压，恢复 worker 后由持久队列继续处理。
