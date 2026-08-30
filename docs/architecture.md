# Architecture Overview

## Applications

- `apps/api`: FastAPI service exposing `/api/v1/...` (共享产品模块：大厅、玩家、规则、Admin) 和 `/api/v2/...` (Live V2 直播)
- `apps/mobile-web`: the only C-end surface, supporting 320–480 CSS px mobile portrait browsers
- `apps/admin-web`: independent Vite React admin SPA with a fail-closed auth/session boundary
- `packages/game-client`: shared frontend API client, types, lineup helpers, and player-profile helpers

## Local runtime

- PostgreSQL runs in Docker via `docker-compose.yml`
- The API runs locally on `http://localhost:8000`
- The mobile SPA runs locally on `http://localhost:5174`
- The admin SPA runs locally on `http://localhost:5175`

## Request flow

1. The browser loads the SPA from Vite.
2. React Router renders the selected client shell.
3. Admin authenticated development mode first calls `/api/v1/admin/me` with cookie credentials; preview mode makes no API request.
4. The API resolves the server-side Admin session, active user and fixed-role permissions before returning the Admin shell.
5. Mobile 玩家目录使用 `/api/v1/public/player-profiles*`，设备级收藏使用独立 Public Session 与 `/api/v1/public/me/favorite-player-profiles*`。大厅的规则目录与阵容预检使用 `/api/v1/games/rule-sets` 和 `/lineup-preview`（独立 lobby 路由）；新对局的创建、观战与上帝视角走 `/api/v2/*`。
6. Admin 对局列表与详情只调用 `/api/v1/admin/v2/games*`，前端路由 `v2/operations/games`。
7. Admin 法官语音资产只调用 `/api/v1/admin/judge-voice-lines*`；列表返回安全元数据，音频通过同权限的受认证 endpoint 按需读取。
8. 授权运营人员从 Admin“内容资产 → 游戏规则”调用 `/api/v1/admin/rule-sets*` 管理结构化草稿、修订和生命周期；发布、设为默认和归档携带版本锁与操作原因，服务端校验并记录审计。

## Live V2 runtime

Live V2 是当前唯一对局路径，代码集中在 `apps/api/app/match/`（前端 `apps/mobile-web/src/match/`、`apps/admin-web/src/match/`）。V1 引擎已于 2026-08-20 整包退场：`app/werewolf/`、V1 路由与 live/replay client、reaper / materializer / quality-evaluator 已删除，Alembic `20260820_58` 已 drop V1 live/replay/quality 表。历史对局数据不保留。`/api/v2`、`LIVE_V2_*` 与 `v2_*` 表名未改。

- 创建对局 `POST /api/v2/games`；创建只冻结规则、玩家、身份与能力快照，状态停在 `waiting_to_start`，不产生模型或 TTS 请求。
- 直播 `WS /api/v2/live/games/{game_id}/ws`，上帝视角 `WS /api/v2/god-view/games/{game_id}/ws`，导播 `WS /api/v2/director/games/{game_id}/ws`。字幕与语音共用同一条连接。
- 首个观众完成音频解锁并发送受众 ready 后，服务端才原子写入 `game_started` 并启动法官流程。
- 所有可展示内容由服务器的单调 `presentation_seq` 驱动。进入页面读一次快照，之后只消费当下与未来的事件，不补播历史字幕与语音。
- 运行时数据在独立的 `v2_*` 表；语音资产以文件形式落在 `live_v2_voice_storage_dir`。
- V2 自带进程内运行租约与心跳。
- Admin 侧对局面在 `/api/v1/admin/v2/games*`，前端路由 `v2/operations/games`。
- Live V2 暂无 Replay。

边界由 `apps/api/tests/test_v2_import_boundary.py` 与 `test_v2_import_boundaries.py` 守卫，禁止 `app/match/` 导入已退场的 V1 引擎模块以及大厅路由。攻击结算常量来自 `app.rule_sets.types`；TTS session 请求由 `app/match/tts_client.py` 自行构造。

## Versioned rule catalog and recovery

- PostgreSQL `rule_sets` 保存稳定规则身份，`rule_set_revisions` 保存不可变的已发布修订。生产使用 `RULE_SET_CATALOG_SOURCE=database`，数据库失败时关闭失败并返回 503，不回退到当前静态规则。`static` 仅允许 staging 紧急兼容，不是 fallback 链。
- Admin 规则管理入口位于“内容资产 → 游戏规则”。浏览器只编辑结构化字段；服务端仍是发布校验、并发版本、生命周期约束和审计的最终边界。
- 公开目录只返回 published、未归档修订。revision-aware Mobile 在开局时提交 `expected_rule_revision_id`；API 在事务内重新读取并精确匹配修订，冲突时返回当前目录项且不启动 worker。
- 成功开局将稳定 ID、revision ID/number、content hash 和完整 snapshot 固定到 V2 对局。引擎和 prompt 只使用该快照；后续发布、归档、改名或默认切换不会改变历史局。
- `rule_sets/snapshots.py` 的 legacy snapshot 解析同时服务旧 revision 行与回填路径。
- 迁移 `20260712_15` 创建目录并写入四个官方 revision 1；`20260712_16` 为 Live/game 增加 nullable 规则来源列，且仅对 canonical hash 精确匹配的快照回填 revision。迁移 15 的 downgrade 会删除整个规则目录，用户规则存在时未先导出不得执行。
- `/api/v1/metrics` 的规则 counter 是进程本地的有界序列，Prometheus 必须直接抓取每个 API Pod，并在查询中聚合 counter。`werewolf_rule_games`、`werewolf_rule_game_failure_ratio_delta` 和 `werewolf_rule_published_defaults` 是每个 Pod 都会渲染的数据库 gauge；delta 表示当前数字修订相对同一稳定规则前一个可用修订的失败率变化。跨 Pod 查询必须去重，不能直接求和。标签和日志只允许稳定 ID、revision number、schema version 和 12 位 hash 前缀，不记录快照、description、玩家、SQL 或原始错误。

## Admin security boundary

- Production `admin-web` 只有显式启用认证并完成通用 OIDC Authorization Code + PKCE 配置后才开放登录；OIDC 未启用或 issuer、callback、Web base URL 不满足 HTTPS 约束时，生产 API 启动即关闭失败。正式租户与真实账号验收完成前不得开放外网入口。
- Local development login requires explicit frontend and backend flags, is limited to development/test, and takes identity and role only from server configuration.
- The browser receives an HttpOnly session cookie; PostgreSQL stores only SHA-256 hashes of session and CSRF secrets.
- `/api/v1/admin/me` returns the current user, permission set, CSRF token and expiry. Admin writes must use the server-side permission dependency and CSRF dependency.
- Admin errors use Problem Details with stable codes and request IDs. Auth responses are `no-store`.
- `audit_events` provides a redacted, bounded audit foundation. 玩家创建、更新、发布、归档和恢复已经记录成功/失败事件，后续 Admin 业务写入必须复用同一入口。
- Admin 对局 API 使用 `v2_games.read` 只读访问 V2 对局记录并返回 `no-store`。
- `runs.control` 提供 V2 对局的幂等停止。
- Admin 法官语音 API 使用 `voice.read`，返回 `no-store` 且不暴露服务器文件路径、旧 public URL、manifest、字幕内容或音频块；试听 URL 仍由 API 再次鉴权。旧匿名生成 endpoint 默认关闭且 production 不能开启。
- Migration `20260711_06` adds `judge_voice_assets`; the idempotent import command copies audio bytes, checksums and normalized subtitle timings into PostgreSQL. Admin inventory, live static-judge playback and replay use database-first/legacy-file fallback during the expand period.
- Migration `20260711_07` adds persistent judge-voice generation jobs. Admin enqueue requires CSRF, mode-specific permission and an idempotency key; an independent CLI worker claims queued jobs with row locking, while stale running jobs are recoverable.
- Migration `20260711_09` adds optimistic versions for Admin accounts and persistent provisioning idempotency. Account creation, role/status changes and session revocation use fixed RBAC, CSRF, conflict protection and audit records; audit list DTOs exclude payloads, network identity and authentication secrets.

## Player profile boundaries

- `virtual_player_profiles` 使用 `draft -> published -> archived` 生命周期、软归档、`featured` 后台推荐位和整数版本乐观锁。
- `/api/v1/admin/player-profiles*` 使用服务端 session、固定权限、CSRF、Admin DTO 和审计；状态转换必须提交原因。
- `/api/v1/public/player-profiles*` 是非个性化、可共享缓存的 Catalog，只返回 published、未归档档案的字段白名单和受管同源头像，不暴露 owner、prompt、内部路径或管理字段。
- Public Guest Session 使用独立 HttpOnly Cookie、CSRF 和 Mobile 专用 Origin allowlist；数据库只存 secret 哈希，不能由 body/header/path 指定用户。
- `user_favorite_player_profiles` 按服务端解析的 Guest User 隔离收藏；个性化响应 `private, no-store`，不修改全局 `favorite`、`featured`、`display_order` 或 Profile `version`。
- legacy `/api/v1/player-profiles*` 由同一个 service 层提供兼容；匿名内容与 favorite 写入默认关闭且 production 禁止启用。
- 对局显式选择和自动补位只会解析 published、未归档档案。
- 从 Profile 创建的新对局不再回退 legacy 外链头像。

## Runtime data ownership

- PostgreSQL is the only runtime source for virtual player profiles. Profile API operations return `503` when the database is unavailable.
- Legacy `player_profiles.json` files are migration inputs only and can be imported with `python -m app.cli import-player-profiles --source <path>`.
- Live V2 对局写入独立的 `v2_*` 表；语音资产以文件形式落在 `live_v2_voice_storage_dir`。
- Versioned rule parents and immutable revisions are persisted in `rule_sets` and `rule_set_revisions`; production catalog reads never fall back to static definitions.
- Admin sessions and redacted audit events are persisted in PostgreSQL; raw session and CSRF secrets are never stored in the database.
- Public Guest sessions and per-user player favorites are persisted in PostgreSQL. Guest Cookie 丢失后不能跨设备恢复。
- Avatar image assets and legacy avatar migration inputs may still use `WEREWOLF_LOGS_DIR`.
