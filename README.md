# 狼人杀实时观战工作台

## 仓库结构

- `apps/api`：FastAPI 后端
- `apps/mobile-web`：唯一 C 端移动 React SPA
- `apps/admin-web`：独立运营与诊断后台
- `packages/game-client`：共享前端 API client、类型、阵容与玩家档案辅助逻辑
- `docs`：架构与规划文档

## 当前状态

**V1 已于 2026-08-20 整包退场，目录改名也已完成。** 当前没有进行中的退场或改名事项。

唯一对局路径是 Live V2：大厅创建后进入 `/v2/games/<game_id>/live`，经 `/api/v2` WebSocket 直播。代码在 `apps/api/app/match/`、`apps/mobile-web/src/match/`、`apps/admin-web/src/match/`。

已删除：`app/werewolf/`、V1 路由与 live/replay client、reaper / materializer / quality-evaluator、15 张 V1 live/replay/quality 表。历史对局数据不保留。大厅规则目录、玩家库、TTS 与法官语音等共享代码在 `apps/api/app/shared/`。大厅 `rule-sets` / `lineup-preview` 仍走 `/api/v1/games/*`。

未改：`/api/v2`、`LIVE_V2_*`、`v2_*` 表与 `v2_game_xxx` game_id。

### 整理进度

以本文件为任务板。做完一步就改这里，不要另开一份会过期的计划。

| 状态 | 事项 | 2026-08-20 结果 |
|---|---|---|
| 已完成 | 文档收敛 | README 新增「当前状态」；过时 V1 specs/plans 归档到 `docs/archive/` |
| 已完成 | 导入边界 | 对局代码不得 import `app.werewolf` / `app.v2`；TTS session 由 `app/match/tts_client.py` 自建 |
| 已完成 | CI 预存失败 | `test_v2_day_speech_pipeline_orchestration.py` 假仓储补上 `at_or_before_record_seq` |
| 已完成 | 死代码 | 见下一节 |
| 已完成 | V1 退场 | 第 1–6 步全部落地，见下一节 |
| 已完成 | 目录改名 | `app/v2` → `app/match`，前端 `src/v2` → `src/match`，`V2Xxx` 去前缀 |

### 已清理的死代码

这些已经不在当前路径上，不要再加回来：

- `packages/game-client` 的 `createGameRun` / `CreateGameRunRequest`：大厅走 `POST /api/v2/games`
- `packages/game-client` 的 `listModelOptions`：无调用方。后端 `GET /api/v1/games/model-options` 已随 V1 路由删除
- `QwenProvider`、`QWEN_CONFIG`、`DASHSCOPE_*`：从未注册进默认路由，V2 也没有对应 provider
- `QUALITY_EVALUATION_RETENTION_DAYS`：配置存在但从未读取

Mobile e2e 的开局 mock 已改为拦截 `POST /api/v2/games`，并补上大厅实际会打的 `lineup-preview`。

### 已完成：V1 退场与目录改名

2026-08-20 已按固定顺序做完，不要再开新的退场步骤。

1. `rule-sets` 与 `lineup-preview` 迁到 `app/api/routes/lobby.py`，URL 仍是 `/api/v1/games/*`。
2. Mobile 去掉对局记录 Tab 与 V1 观战、回放；Admin 去掉对局记录与运行监控；`game-client` 删除 live/replay。
3. `/ready` 只检查数据库与 Alembic head。
4. 停用 live-run-reaper、live-voice-materializer、quality-evaluator；保留 judge-voice-worker。
5. 删除 `app/werewolf/`、V1 路由、V1 测试；共享代码在 `app/shared/`。
6. Alembic `20260820_58` drop 15 张 V1 live/replay/quality 表。
7. `app/v2` → `app/match`，前端 `src/v2` → `src/match`，`V2Xxx` 去前缀。改名未与退场混在同一次提交里。

以下三项刻意保持不变：`/api/v2` 路由前缀、`LIVE_V2_*` 环境变量、`v2_*` 表与 `v2_game_xxx` game_id。

若再给 `app/match/` 平铺文件分子目录，边界测试必须继续 `rglob`，否则会漏扫子目录。

### 导入边界

对局代码不得导入已退场的 V1 引擎，也不得导入大厅路由。2026-08-20 已清掉历史违规；边界测试扫描 `app/match/`，并继续禁止 `app.werewolf`、`app.v2`、`app.models.live`、`app.models.game_session` 和 `app.api.routes.games`。

- 攻击结算常量定义在 `app.rule_sets.types`，对局运行时与规则目录都从这里读。
- TTS session 请求由 `app/match/tts_client.py` 自行构造，不调用 `app.shared.volcengine_tts`。

边界测试 `test_v2_import_boundary.py` 与 `test_v2_import_boundaries.py` 必须保持绿色。

### 文档采信顺序

代码是唯一事实来源。文档之间冲突时按此顺序采信：本文件 → `docs/live-v2-refactor-guidelines.md` → `docs/superpowers/specs/` 下 2026-08 之后的 Live V2 设计 → 其余文档。`docs/archive/` 里的内容描述 V1 行为，仅供历史查阅，不适用于当前路径。

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

Live V2 使用独立的 `v2_*` 表，语音资产落在文件系统。大厅规则目录、玩家档案、Admin 会话与法官语音资产使用共享表，不依赖已退场的 V1 live/replay 表。

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

版本化规则目录由 `20260712_15_create_rule_set_catalog.py` 创建，并写入四个官方规则的 published revision 1。应用上线前必须先完成规则目录迁移；精确发布、验证与回滚步骤见 `docs/admin-deployment-runbook.md`。

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

`make api` 会先执行 `alembic upgrade head`，再启动 FastAPI。`/ready` 只检查数据库可连接且位于 Alembic head，不再依赖任何语音 worker。
开发态进程的启动、信号转发和退出清理由 `scripts/run-api-dev.sh` 统一管理。该命令还会注入仅用于
本地 HTTP 联调的开发认证与 Cookie 配置。如果手动启动，需先自行完成迁移，
并提供等价环境变量：

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
```

管理后台地址：

```text
http://127.0.0.1:5175
```

`admin-web` 已接入 `/api/v1/admin/me`、服务端会话、权限路由、403、会话过期和安全登出，并完成运营总览、全局 ID 搜索、持久任务中心、只读安全设置、玩家资料与受控 AI 草稿、后台账号、审计日志、V2 对局记录和法官语音资产。总览关注玩家内容与语音任务告警；设置接口只返回非敏感运行参数。Admin 只调用 `/api/v1/admin/*`；`mobile-web` 仍是唯一继续演进的 C 端。V1 的对局记录与运行监控已下线。具备 `runs.control` 的操作者仍可在 V2 对局详情停止对局。

法官语音资产使用 `/api/v1/admin/judge-voice-lines*` 提供 `voice.read` 保护的覆盖率、分类筛选、运行时使用状态、缺失项和受认证试听；普通 DTO 不返回文件路径、public URL、manifest、字幕内容或音频字节。迁移 `20260711_06` 建立 PostgreSQL 独立资产表，`.venv/bin/python -m app.cli import-judge-voice-assets` 可从 `apps/api/resources/judge-voice-seed` 幂等导入种子资产。

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
LIVE_V2_TTS_ENABLED=true
LIVE_V2_TTS_API_KEY=<your-api-key>
LIVE_V2_TTS_RESOURCE_ID=seed-tts-2.0
LIVE_V2_TTS_SAMPLE_RATE=24000
```

`ARK_TTS_*` 是这些变量的兼容别名，两套名字读的是同一份配置。

Live V2 的语音和字幕走同一条直播 WebSocket，没有独立的语音连接。TTS 产生的同一份有序 PCM 会同时交给实时广播和语音保存器，保存为全新的 V2 语音资产（默认落在 `data/live-v2/voices`），既不会为了保存再请求一次 TTS，也不会让直播改读保存文件。保存完成时校验 sample 数、时长和 PCM 哈希，不一致则本次动作失败。

按准则第 4.1 节，**Live V2 不补播历史语音**。晚连或断线重连的观众直接跳到服务器当前直播状态，断线期间错过的语音不进入播放队列。移动端首次开启语音需要先完成浏览器音频解锁。

## 实时观战流程

1. 打开 `http://127.0.0.1:5174/games`。
2. 点击“发起对局”。此时只冻结规则、玩家、身份和能力快照，对局状态是 `waiting_to_start`，不产生任何模型或 TTS 请求。
3. 页面进入 `/v2/games/<game_id>/live`。上帝视角是 `/v2/games/<game_id>/live/god`。
4. 首个观众点击实时观赛并完成音频解锁后，受众 ready 才会原子写入 `game_started` 并启动法官流程。这是正式开局的唯一触发点。
5. 观战页展示玩家、阶段、字幕和语音状态，直播由服务器的 `presentation_seq` 单调驱动。

Live V2 目前没有 Replay。准则第 4.2 节要求 Replay 与直播完全分离、不共享任何业务组件，该能力尚未开发。

revision-aware 客户端在开局时提交 `expected_rule_revision_id`。服务端在同一数据库事务中选定 published revision，将完整 snapshot 固定到对局；后续发布或归档不会改变旧局规则。`rule_sets/snapshots.py` 的 legacy snapshot 解析仍服务旧 revision 行和回填路径，不专属已退场的 V1。

V1 对局表已删除。若本地还留着不会再被读取的 `apps/api/logs/game_*` 文件，可执行：

```bash
cd apps/api
.venv/bin/python -m app.cli purge-legacy-game-records --logs-dir logs --yes
```

Live V2 使用进程内运行租约与心跳，不再使用 V1 reaper。

运行真实模型对局前，请确认 `apps/api/.env` 中模型服务相关配置已经填写。生产 Live V2
对局应使用允许应用服务调用的火山方舟标准推理 API：配置 `ARK_STANDARD_API_KEY`、
`ARK_STANDARD_BASE_URL=https://ark.cn-beijing.volces.com/api/v3`，并把已部署的
Endpoint/模型 ID 写入 `ARK_STANDARD_MODELS`。Admin 模型管理会把这些模型列在
“火山方舟标准推理 API”下。

旧的 Agent Plan 兼容配置仍可读取历史冻结记录，但官方套餐使用范围不适合作为游戏后端
生产 API。旧配置使用 `ARK_AGENT_PLAN_API_KEY` 和
`https://ark.cn-beijing.volces.com/api/plan/v3`，可见模型包括：

- `doubao-seed-2-0-lite-260215`
- `glm-5-2-260617`
- `minimax-m3`

如果 `WEREWOLF_DEFAULT_MODEL` 为空且配置了 Agent Plan Key，默认模型为
`doubao-seed-2-0-lite-260215`。项目不读取 `MINIMAX_API_KEY`，也不请求 MiniMax
官方接口。

DeepSeek 默认模型为 `deepseek-v4-flash`。

Live V2 只有三条 provider 路由：`agent_plan`、`ark` 和 `deepseek`，默认 `agent_plan`。GLM、Doubao、MiniMax 与 Agent Plan 共用同一个并发槽位，DeepSeek 独立。新增厂商请在 `apps/api/app/match/model_client.py` 增加路由。未注册的 `DASHSCOPE_*` / Qwen 配置已删除，当前对局路径不会读取它们。

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
