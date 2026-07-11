# 狼人杀实时观战工作台

## 仓库结构

- `apps/api`：FastAPI 后端
- `apps/web`：React SPA 前端
- `apps/mobile-web`：移动端 React SPA 前端
- `apps/admin-web`：独立运营与诊断后台
- `packages/game-client`：共享前端 API client、类型与对局状态辅助逻辑
- `docs`：架构与规划文档

## 快速开始

复制环境变量文件：

```bash
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env
cp apps/admin-web/.env.example apps/admin-web/.env
```

安装依赖：

```bash
cd apps/api && uv sync
pnpm install
```

`uv` 只用于首次同步 Python 依赖。如果本机没有 `uv`，请先安装 `uv`，或者使用已经存在的 `apps/api/.venv` 运行后端；`make api` 会直接调用项目内的 `.venv/bin/python`。

PostgreSQL 是虚拟玩家档案的唯一运行时数据源。使用玩家库或发起对局前，启动数据库并执行迁移：

```bash
docker compose up -d db
cd apps/api && uv run alembic upgrade head
```

数据库不可用时，玩家档案 CRUD 和依赖玩家库的开局请求会返回 `503`，不会回退到本地 JSON 文件。

实时观战 run、SSE 事件、语音 utterance 和语音音频 chunk 也会写入 PostgreSQL。语音和实时事件相关表由
`apps/api/alembic/versions/20260708_01_create_live_voice_tables.py` 创建；如果刚拉到新代码，务必先执行
`alembic upgrade head`，否则发起对局和语音补播会缺少持久化表。

Admin 服务端会话、固定角色和审计基础表由
`apps/api/alembic/versions/20260710_01_create_admin_auth_tables.py` 创建。Admin 联调前同样必须先执行
`alembic upgrade head`。

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

如果旧版本曾在 `apps/api/logs/player_profiles.json` 写入玩家档案，可在数据库迁移完成后执行一次幂等导入：

```bash
cd apps/api
.venv/bin/python -m app.cli import-player-profiles --source logs/player_profiles.json
```

命令按档案 ID 导入，数据库中已存在的 ID 会跳过且不会覆盖。确认导入统计后可自行归档旧 JSON 文件；运行时不再读取或写入该文件。

## 本地运行

后端、旧桌面端、移动端和管理后台可分别在独立终端运行。

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

终端 2，启动 Vite 前端：

```bash
make web
```

等价直接命令：

```bash
cd apps/web
pnpm dev --host 0.0.0.0 --port 5173
```

前端地址：

```text
http://127.0.0.1:5173
```

同一局域网内的手机或其他电脑也可以访问：

```text
http://<你的电脑局域网 IP>:5173
```

开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`，因此前端页面中的 `/api/v1/...` 请求会自动转发到 FastAPI。

终端 3，启动移动端 Web：

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

移动端和桌面端共用 `/api/v1/...`，开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`。

终端 4，启动管理后台：

```bash
make admin-web
```

管理后台地址：

```text
http://127.0.0.1:5175
```

`admin-web` 已接入 `/api/v1/admin/me`、服务端会话、权限路由、403、会话过期和安全登出，并完成玩家资料管理以及真实 API 驱动的“对局记录”“运行监控”和“法官语音资产”只读模块。对局列表使用 `/api/v1/admin/games` 做服务端分页筛选；详情只显示终局玩家/角色结果、公开轮次摘要、运行和无 payload 的事件元数据白名单。partial/resumable 对局还会隐藏胜方、玩家及运行模型、死亡原因/来源、事件元数据和未完成轮次。错误摘要必须具备 `games.debug.read`，且由操作者显式点击后才请求独立 `/debug` 接口并写入审计。

运行监控使用 `/api/v1/admin/live-runs*` 读取 PostgreSQL 持久化摘要：列表第 1 页存在 queued/running 记录时每 5 秒轮询，无活跃运行时每 30 秒发现新记录，其他页仅手动刷新。`last_activity_at` 和 `is_stale` 仅描述数据库中最近持久化活动的新鲜度，不是进程心跳或健康检查。普通列表/详情严格使用字段白名单；只有 completed 且关联对局已安全终局时才显示胜方、模型和事件 actor/action。脱敏错误分类必须具备 `runs.debug.read` 并由操作者显式请求独立 `/debug`，读取会写入审计；当前页面没有停止、恢复或重试控制。Admin 只调用 `/api/v1/admin/*`，不调用旧匿名内容写接口；`mobile-web` 仍是唯一继续演进的 C 端。

法官语音资产使用 `/api/v1/admin/judge-voice-lines*` 提供 `voice.read` 保护的覆盖率、分类筛选、缺失项和受认证试听；普通 DTO 不返回文件路径、旧 public URL、manifest、字幕内容或音频字节。迁移 `20260711_06` 建立 PostgreSQL 独立资产表，`.venv/bin/python -m app.cli import-judge-voice-assets` 可幂等导入旧静态文件；Admin、实时法官语音和回放均数据库优先、旧目录回退。旧文件暂留作回滚输入。旧 Web 匿名生成 POST 默认关闭，production 禁止重新开启。

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

开发登录不接收浏览器提供的身份或角色，且在 production 环境会被后端拒绝。生产前端只有显式注入 `VITE_ADMIN_AUTH_ENABLED=true` 才进入真实认证边界，否则 fail closed；正式身份源仍需单独接入。

旧 `/api/v1/player-profiles` 内容和全局收藏写入均默认关闭；如旧 Web 仍需短期联调，可仅在非 production 环境分别显式设置：

```dotenv
LEGACY_PLAYER_PROFILE_CONTENT_WRITES_ENABLED=true
LEGACY_PLAYER_PROFILE_FAVORITE_WRITES_ENABLED=true
```

production 会拒绝启用这两个开关。Mobile 已使用 `/api/v1/public/player-profiles*`、独立 Public Session 和
`/api/v1/public/me/favorite-player-profiles*`，不会回退匿名 PATCH。Guest 收藏按当前浏览器 Cookie 隔离；清除 Cookie 或更换设备后无法找回，跨设备同步需要后续接入正式 C 端身份源。
`mobile-web` 是唯一继续演进的 C 端页面；`apps/web` 仅作为迁移期兼容端保留，不向 Admin 搬运大厅、观战剧场或普通回放 UI。

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

1. 打开 `http://127.0.0.1:5173/games`。
2. 点击“发起对局”。
3. 页面会进入 `/games/live/<run_id>`。
4. 实时观战页会展示玩家列表、当前聚焦玩家、原始事件侧栏。
5. 对局结束后点击“查看完整复盘”进入 `/games/<session_id>`。

新对局的历史记录、完整复盘和恢复检查点保存在 PostgreSQL。旧版 `apps/api/logs/game_*` 文件记录不会再被读取；完成迁移后可执行：

```bash
cd apps/api
.venv/bin/python -m app.cli purge-legacy-game-records --logs-dir logs --yes
```

实时 run 和 SSE 事件会写入 PostgreSQL，同时活动订阅、正在运行的模型任务和内存队列仍由当前 API
进程管理，当前部署应使用单个 API worker。同一进程内重复恢复同一对局会复用已有活动 run，不会重复启动模型任务；跨进程排他需要后续引入共享任务存储。

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

API 和桌面端 Web 检查：

- `make lint`
- `make test`
- `cd apps/web && pnpm build`

完整前端/共享包检查：

```bash
cd apps/api && .venv/bin/python -m pytest
cd apps/web && pnpm test -- --run
cd apps/web && pnpm build
pnpm --dir packages/game-client test -- --run
pnpm --dir apps/mobile-web test -- --run
pnpm --dir apps/mobile-web build
pnpm --dir apps/admin-web lint
pnpm --dir apps/admin-web test -- --run
pnpm --dir apps/admin-web build
```

如需精确筛选 Vitest 文件，可使用 `pnpm --dir apps/mobile-web exec vitest run <files>`；当前 workspace 中 `pnpm test -- --run <files>` 会运行较宽的测试集合。
