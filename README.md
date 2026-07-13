# 狼人杀实时观战工作台

## 仓库结构

- `apps/api`：FastAPI 后端
- `apps/mobile-web`：唯一 C 端移动 React SPA
- `apps/admin-web`：独立运营与诊断后台
- `packages/game-client`：共享前端 API client、类型与对局状态辅助逻辑
- `docs`：架构与规划文档

## 快速开始

复制环境变量文件：

```bash
cp apps/api/.env.example apps/api/.env
cp apps/admin-web/.env.example apps/admin-web/.env
```

安装依赖：

```bash
cd apps/api && uv sync
pnpm install
```

`uv` 只用于首次同步 Python 依赖。如果本机没有 `uv`，请先安装 `uv`，或者使用已经存在的 `apps/api/.venv` 运行后端；`make api` 会直接调用项目内的 `.venv/bin/python`。

PostgreSQL 是虚拟玩家档案和生产规则目录的唯一运行时数据源。使用玩家库或发起对局前，启动数据库并执行迁移：

```bash
docker compose up -d db
cd apps/api && uv run alembic upgrade head
```

数据库不可用时，玩家档案 CRUD、公开规则目录和依赖这些数据的开局请求会返回 `503`，不会回退到本地 JSON 或静态规则表。生产必须显式设置 `RULE_SET_CATALOG_SOURCE=database`；`static` 仅是 staging 紧急兼容模式，不是自动 fallback。

实时观战 run、SSE 事件、语音 utterance 和语音音频 chunk 也会写入 PostgreSQL。语音和实时事件相关表由
`apps/api/alembic/versions/20260708_01_create_live_voice_tables.py` 创建；如果刚拉到新代码，务必先执行
`alembic upgrade head`，否则发起对局和语音补播会缺少持久化表。

Admin 服务端会话、固定角色和审计基础表由
`apps/api/alembic/versions/20260710_01_create_admin_auth_tables.py` 创建。Admin 联调前同样必须先执行
`alembic upgrade head`。

拥有规则权限的运营人员在 Admin 的“内容资产 → 游戏规则”通过结构化表单管理规则。发布、设为默认和归档操作继续携带版本锁和操作原因，由服务端完成权限、状态与规则校验并写入审计。

玩家草稿、发布、归档、推荐位和乐观锁字段由
`apps/api/alembic/versions/20260710_02_expand_virtual_player_profile_lifecycle.py` 创建。迁移会把历史档案回填为已发布，
并把原 `favorite` 同步到后台 `featured`；上线 API 前必须先完成该迁移。

Mobile 的设备级 Guest Session 与个人玩家收藏关系由
`apps/api/alembic/versions/20260710_03_create_public_sessions_and_favorites.py` 创建。Public Session 与 Admin Session
完全隔离，数据库只保存会话和 CSRF secret 的哈希；该迁移不会把无法确认归属的历史全局 `favorite` 回填给 Guest。

Admin 对局分页检索使用的查询索引由
`apps/api/alembic/versions/20260710_04_add_admin_game_query_indexes.py` 创建；`make api` 会随其他迁移一起应用。

Admin 运行监控使用的四个查询索引由
`apps/api/alembic/versions/20260711_05_add_admin_live_run_query_indexes.py` 创建，分别覆盖运行更新时间分页
`(updated_at DESC, run_id DESC)`、运行创建时间分页 `(created_at DESC, run_id DESC)`、状态加更新时间分页
`(status, updated_at DESC, run_id DESC)` 和语音状态聚合 `(run_id, status)`；`make api` 会随其他迁移一起应用。

版本化规则目录由 `20260712_15_create_rule_set_catalog.py` 创建，并写入四个官方规则的 published revision 1；`20260712_16_add_rule_revision_references.py` 为 Live run 和 game session 增加稳定规则 ID、revision 和 hash，且只对精确匹配的历史快照回填 revision。应用上线前必须先迁移至少 `20260712_16`；精确发布、验证与回滚步骤见 `docs/admin-deployment-runbook.md`。

如果旧版本曾在 `apps/api/logs/player_profiles.json` 写入玩家档案，可在数据库迁移完成后执行一次幂等导入：

```bash
cd apps/api
.venv/bin/python -m app.cli import-player-profiles --source logs/player_profiles.json
```

命令按档案 ID 导入，数据库中已存在的 ID 会跳过且不会覆盖。确认导入统计后可自行归档旧 JSON 文件；运行时不再读取或写入该文件。

## 本地运行

后端、移动端和管理后台可分别在独立终端运行。

终端 1，启动 FastAPI：

```bash
make api
```

`make api` 会先执行 `alembic upgrade head`，并注入仅用于本地 HTTP
联调的开发认证与 Cookie 配置。如果手动启动，需先自行完成迁移并提供等价环境变量：

```bash
cd apps/api
APP_ENVIRONMENT=development \
ADMIN_DEV_AUTH_ENABLED=true \
ADMIN_SESSION_COOKIE_SECURE=false \
PUBLIC_SESSION_COOKIE_SECURE=false \
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

后端地址：

```text
http://127.0.0.1:8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

终端 2，启动移动端 Web：

```bash
make mobile-web
```

移动端地址：

```text
http://127.0.0.1:5174
```

同一局域网内的手机或其他电脑也可以访问：

```text
http://<你的电脑局域网 IP>:5174
```

开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`。C 端正式支持 320～480 CSS px 的移动设备竖屏；桌面端、平板和横屏不在验收范围内。

终端 3，启动管理后台：

```bash
make admin-web
```

浏览器级 Admin 验收可在安装 Chromium 后执行：

```bash
pnpm --dir apps/admin-web exec playwright install chromium
make admin-e2e
管理后台地址：

```text
http://127.0.0.1:5175
```

`admin-web` 已接入 `/api/v1/admin/me`、服务端会话、权限路由、403、会话过期和安全登出，并完成运营总览、全局 ID 搜索、持久任务中心、只读安全设置、玩家资料与受控 AI 草稿、后台账号、审计日志，以及真实 API 驱动的“对局记录”“运行监控”和“法官语音资产”模块。总览和顶栏异常提醒读取真实数据库与 reaper 健康状态；设置接口只返回非敏感运行参数。对局详情只显示终局玩家/角色结果、公开轮次摘要、运行和无 payload 的事件元数据白名单；错误摘要必须具备 `games.debug.read`，并由操作者显式请求独立 `/debug` 接口后写入审计。

运行监控使用 `/api/v1/admin/live-runs*` 读取 PostgreSQL 持久化摘要：列表第 1 页存在 queued/running 记录时每 5 秒轮询，无活跃运行时每 30 秒发现新记录，其他页仅手动刷新。Worker 在线状态来自数据库租约心跳，`last_activity_at` 同时保留持久化事件的新鲜度。普通列表/详情严格使用字段白名单；只有 completed 且关联对局已安全终局时才显示胜方、模型和事件 actor/action。脱敏错误分类必须具备 `runs.debug.read` 并由操作者显式请求独立 `/debug`，读取会写入审计。具备 `runs.control` 的操作者可以提交幂等停止或检查点恢复；过期租约通过单调递增的 fencing token 接管，旧 Worker 的事件、checkpoint、回放和终态写入会被数据库拒绝。Admin 只调用 `/api/v1/admin/*`，不调用旧匿名内容写接口；`mobile-web` 仍是唯一继续演进的 C 端。

直播 orphan 自动恢复由独立进程 `.venv/bin/python -m app.cli run-live-run-reaper`（本地可用 `make live-run-reaper`）执行，不随每个 API 副本重复启动。它在租约过期并超过宽限期后原子认领运行：有停止请求则取消，有有效 checkpoint 则恢复，否则标记失败；认领使用指数退避并受最大次数限制。`--once` 可做单次部署验收。恢复次数、最近认领时间、退避截止时间和“自动恢复已耗尽”告警会显示在 Admin 运行监控中。

法官语音资产使用 `/api/v1/admin/judge-voice-lines*` 提供 `voice.read` 保护的覆盖率、分类筛选、缺失项和受认证试听；普通 DTO 不返回文件路径、public URL、manifest、字幕内容或音频字节。迁移 `20260711_06` 建立 PostgreSQL 独立资产表，`.venv/bin/python -m app.cli import-judge-voice-assets` 可从 `apps/api/resources/judge-voice-seed` 幂等导入种子资产；Admin、实时法官语音和回放均数据库优先、API 自有种子目录回退。

迁移 `20260711_07` 建立持久语音生成任务。Admin 使用 CSRF、`voice.generate_missing` / `voice.regenerate_all` 和 `Idempotency-Key` 排队，独立 worker 通过 `.venv/bin/python -m app.cli run-judge-voice-worker` 持续领取任务；`--once` 仅用于单次运维检查，API 或 worker 重启不会丢失 queued job。

默认本地模式连接真实 Admin API；`make api` 和 `make admin-web` 会启用开发会话，打开 `http://127.0.0.1:5175` 后点击“使用开发身份登录”即可进入真实玩家数据。手动启动时，API 环境需要配置：

```dotenv
APP_ENVIRONMENT=development
ADMIN_DEV_AUTH_ENABLED=true
ADMIN_SESSION_COOKIE_SECURE=false
ADMIN_DEV_AUTH_EMAIL=admin@example.test
ADMIN_DEV_AUTH_DISPLAY_NAME=Development Admin
ADMIN_DEV_AUTH_ROLE=super_admin
```

并在 `apps/admin-web/.env` 中设置：

```dotenv
VITE_ADMIN_AUTH_ENABLED=true
VITE_ADMIN_DEV_LOGIN_ENABLED=true
VITE_ADMIN_PREVIEW_MODE=false
```

开发登录不接收浏览器提供的身份或角色，且在 production 环境会被后端拒绝。生产前端只有显式注入 `VITE_ADMIN_AUTH_ENABLED=true` 才进入真实认证边界，否则 fail closed。正式后台登录使用通用 OIDC Authorization Code + PKCE；production 配置会拒绝在 OIDC 未启用或 issuer/callback 不是 HTTPS 时启动。

正式账号不会从 OIDC claims 自动获得角色。先由受控运维环境预配置账号：

```bash
cd apps/api
.venv/bin/python -m app.cli provision-admin-user \
  --email admin@example.com \
  --display-name "Arena Admin" \
  --role operator
```

完成首位超级管理员引导后，可在 Admin 的“系统安全 → 后台账号”中继续开通账号、调整固定角色、停用账号或撤销其全部会话；写操作强制 CSRF、版本冲突检查、幂等键和审计。系统禁止当前操作者停用或降级自己，并确保至少保留一个启用的超级管理员。“审计日志”页面只返回操作者、动作、资源、结果、原因、请求编号和时间，不返回 before/after payload、IP、OIDC subject 或会话信息。

再配置 `ADMIN_OIDC_ISSUER_URL`、`ADMIN_OIDC_CLIENT_ID`、`ADMIN_OIDC_CLIENT_SECRET`、`ADMIN_OIDC_REDIRECT_URI` 和 `ADMIN_OIDC_WEB_BASE_URL`。首次登录只接受提供商签名且 `email_verified=true` 的 ID Token，并把预配置账号永久绑定到 issuer/sub；后续不会按浏览器输入或 OIDC role claim 提权。登录事务、state、浏览器绑定、PKCE verifier 和 nonce 均在服务端校验，回调失败只返回稳定错误分类。

Mobile 使用 `/api/v1/public/player-profiles*`、独立 Public Session 和
`/api/v1/public/me/favorite-player-profiles*`，不会回退匿名 PATCH。Guest 收藏按当前浏览器 Cookie 隔离；清除 Cookie 或更换设备后无法找回，跨设备同步需要后续接入正式 C 端身份源。
`mobile-web` 是唯一 C 端页面；Admin 不承载大厅、观战剧场或普通回放 UI。

本地 HTTP 联调还需要：

```dotenv
PUBLIC_SESSION_COOKIE_SECURE=false
PUBLIC_CORS_ORIGINS=http://localhost:5174,http://127.0.0.1:5174
```

Public Catalog 只返回 published、未归档档案的白名单字段和受管同源头像；Guest Session、`/public/me` 与收藏响应均禁止共享缓存。

## 实时语音

实时语音默认关闭。要启用火山方舟 TTS，在 `apps/api/.env` 中配置：

```dotenv
ARK_TTS_ENABLED=true
ARK_TTS_API_KEY=<your-api-key>
ARK_TTS_RESOURCE_ID=seed-tts-2.0
ARK_TTS_AUDIO_FORMAT=pcm
ARK_TTS_SAMPLE_RATE=24000
```

后端通过 `/api/v1/games/runs/<run_id>/voice-stream` WebSocket 推送语音。协议会先发送
`voice_start`，随后边收到 TTS 音频边发送多个 `audio_chunk`，最后发送 `voice_end`；前端对
`pcm` 音频会使用 Web Audio 边收边排播，不再等待整段音频完成才播放。非 PCM 格式仍保留
Blob 播放兜底。

语音 utterance 元数据和 chunk 会持久化到 PostgreSQL。客户端连接语音流时会带上当前事件
`current_event_id`；如果用户晚连或短暂断线，后端会从数据库补播最近一条已完成且有音频
chunk 的 utterance，然后再订阅后续实时事件。移动端首次开启语音会先执行浏览器音频解锁；
如果浏览器不支持 Web Audio，会在页面上显示语音不可用/播放失败状态。

## 实时观战流程

1. 打开 `http://127.0.0.1:5174/games`。
2. 点击“发起对局”。
3. 页面会进入 `/games/<run_id>/live`。
4. 实时观战页会展示玩家、阶段、字幕和语音状态。
5. 对局结束后进入 `/games/<session_id>/replay` 查看完整复盘。

revision-aware 客户端在开局时提交 `expected_rule_revision_id`。服务端在同一数据库事务中选定 published revision，将完整 snapshot 固定到 run、game 和 checkpoint；后续发布或归档不会改变旧局规则。未提交 revision 的兼容客户端会被计量，但 legacy snapshot parser 和 checkpoint-v1 reader 会永久保留，保证历史局可恢复。

新对局的历史记录、完整复盘和恢复检查点保存在 PostgreSQL。旧版 `apps/api/logs/game_*` 文件记录不会再被读取；完成迁移后可执行：

```bash
cd apps/api
.venv/bin/python -m app.cli purge-legacy-game-records --logs-dir logs --yes
```

实时 run、SSE 事件、运行租约、fencing token 和控制信号会写入 PostgreSQL。可运行多个 API 副本；每个副本只执行自己持有有效租约的模型任务，丢失租约的写入会被 fence 拒绝。独立 reaper 从数据库原子认领 orphan，不依赖 API 单副本部署。

运行真实模型对局前，请确认 `apps/api/.env` 中模型服务相关配置已经填写。当前内置
DeepSeek 和 MiniMax；如果 `WEREWOLF_DEFAULT_MODEL` 为空，后端会从已配置 API key 的
provider 中选择默认模型。只配置 MiniMax key 时，默认对局模型会自动使用
`MINIMAX_MODEL`，也可以在 CLI 或 API 请求中显式传入 `MiniMax-M2.7` 这类模型名。
DeepSeek 默认模型为 `deepseek-v4-flash`。
MiniMax key 需要和 host 区域匹配：大陆 key 使用 `https://api.minimaxi.com/v1`，Global
key 使用 `https://api.minimax.io/v1`。Qwen 使用阿里云百炼 DashScope OpenAI 兼容接口，
默认模型为 `qwen3.6-plus`，也支持在对局参数中传入 `Qwen3.6-Plus`；北京地域默认
base URL 为 `https://dashscope.aliyuncs.com/compatible-mode/v1`。新增 OpenAI-compatible
厂商时，优先在 `apps/api/app/werewolf/providers.py` 增加 provider config。

## 质量检查

完整质量检查：

- `make lint`
- `make test`

完整前端/共享包检查：

```bash
cd apps/api && .venv/bin/python -m pytest
pnpm --dir packages/game-client test -- --run
pnpm --dir apps/mobile-web test -- --run
pnpm --dir apps/mobile-web build
pnpm --dir apps/mobile-web test:e2e
pnpm --dir apps/admin-web lint
pnpm --dir apps/admin-web test -- --run
pnpm --dir apps/admin-web build
```

如需精确筛选 Vitest 文件，可使用 `pnpm --dir apps/mobile-web exec vitest run <files>`；当前 workspace 中 `pnpm test -- --run <files>` 会运行较宽的测试集合。
