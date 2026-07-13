# Architecture Overview

## Applications

- `apps/api`: FastAPI service exposing `/api/v1/...`
- `apps/mobile-web`: the only C-end surface, supporting 320–480 CSS px mobile portrait browsers
- `apps/admin-web`: independent Vite React admin SPA with a fail-closed auth/session boundary
- `packages/game-client`: shared frontend API client, types, lineup helpers, replay adapters, and live-state derivation

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
5. Mobile 玩家目录使用 `/api/v1/public/player-profiles*`，设备级收藏使用独立 Public Session 与 `/api/v1/public/me/favorite-player-profiles*`；大厅、对局、观战和回放使用 `/api/v1/games*`。
6. Admin 对局列表与详情只调用 `/api/v1/admin/games*`；普通详情返回白名单诊断摘要，受限错误摘要必须在 `games.debug.read` 下由用户显式请求独立 `/debug`。
7. Admin 运行监控只调用 `/api/v1/admin/live-runs*` 读取 PostgreSQL 持久化摘要；第 1 页存在 queued/running 记录时每 5 秒轮询，否则每 30 秒发现新记录，其他页不自动轮询。
8. Admin 法官语音资产只调用 `/api/v1/admin/judge-voice-lines*`；列表返回安全元数据，音频通过同权限的受认证 endpoint 按需读取。
9. 授权运营人员从 Admin“内容资产 → 游戏规则”调用 `/api/v1/admin/rule-sets*` 管理结构化草稿、修订和生命周期；发布、设为默认和归档携带版本锁与操作原因，服务端校验并记录审计。

## Versioned rule catalog and recovery

- PostgreSQL `rule_sets` 保存稳定规则身份，`rule_set_revisions` 保存不可变的已发布修订。生产使用 `RULE_SET_CATALOG_SOURCE=database`，数据库失败时关闭失败并返回 503，不回退到当前静态规则。`static` 仅允许 staging 紧急兼容，不是 fallback 链。
- Admin 规则管理入口位于“内容资产 → 游戏规则”。浏览器只编辑结构化字段；服务端仍是发布校验、并发版本、生命周期约束和审计的最终边界。
- 公开目录只返回 published、未归档修订。revision-aware Mobile 在开局时提交 `expected_rule_revision_id`；API 在事务内重新读取并精确匹配修订，冲突时返回当前目录项且不启动 worker。
- 成功开局将稳定 ID、revision ID/number、content hash 和完整 snapshot 同时固定到 Live run、game session 和 checkpoint。引擎和 prompt 只使用该快照；后续发布、归档、改名或默认切换不会改变历史局。
- checkpoint-v2 验证 revision/schema/hash 和运行来源；checkpoint-v1 仍必须携带可完整解析的旧 snapshot。legacy snapshot parser 与 checkpoint-v1 reader 是永久历史数据合约，不随 revision-aware 客户端切换而删除。
- 迁移 `20260712_15` 创建目录并写入四个官方 revision 1；`20260712_16` 为 Live/game 增加 nullable 规则来源列，且仅对 canonical hash 精确匹配的快照回填 revision。迁移 15 的 downgrade 会删除整个规则目录，用户规则存在时未先导出不得执行。
- `/api/v1/metrics` 的规则 counter 是进程本地的有界序列，Prometheus 必须直接抓取每个 API Pod，并在查询中聚合 counter。`werewolf_rule_games`、`werewolf_rule_game_failure_ratio_delta` 和 `werewolf_rule_published_defaults` 是每个 Pod 都会渲染的数据库 gauge；delta 表示当前数字修订相对同一稳定规则前一个可用修订的失败率变化。跨 Pod 查询必须去重，不能直接求和。标签和日志只允许稳定 ID、revision number、schema version 和 12 位 hash 前缀，不记录快照、description、玩家、SQL 或原始错误。

## Admin security boundary

- Production `admin-web` 只有显式启用认证并完成通用 OIDC Authorization Code + PKCE 配置后才开放登录；OIDC 未启用或 issuer、callback、Web base URL 不满足 HTTPS 约束时，生产 API 启动即关闭失败。正式租户与真实账号验收完成前不得开放外网入口。
- Local development login requires explicit frontend and backend flags, is limited to development/test, and takes identity and role only from server configuration.
- The browser receives an HttpOnly session cookie; PostgreSQL stores only SHA-256 hashes of session and CSRF secrets.
- `/api/v1/admin/me` returns the current user, permission set, CSRF token and expiry. Admin writes must use the server-side permission dependency and CSRF dependency.
- Admin errors use Problem Details with stable codes and request IDs. Auth responses are `no-store`.
- `audit_events` provides a redacted, bounded audit foundation. 玩家创建、更新、发布、归档和恢复已经记录成功/失败事件，后续 Admin 业务写入必须复用同一入口。
- Admin 对局 API 使用 `games.read` 强制只读访问并返回 `no-store`；列表服务端分页筛选，详情不返回 replay state/log/checkpoint、event payload、prompt、raw response 或私有角色知识。partial/resumable 对局进一步隐藏角色、玩家与运行模型、死亡原因/来源、事件元数据和未完成轮次。
- `games.debug.read` 不扩展普通详情 DTO。前端只有在用户显式点击后才调用独立 debug endpoint；该读取返回分类脱敏、限长限量的错误摘要并记录审计。
- Admin 运行 API 使用 `runs.read` 强制只读访问并返回 `no-store`。普通 DTO 仅投影运行、规则、计数、关联对局和最多 50 条无 payload 事件元数据，不读取或返回 seed、player configs、lineup warnings、prompt、raw error、语音文本或音频。
- 只有 completed 且关联对局为 complete、不可恢复时，普通运行 DTO 才公开胜方、模型和事件 actor/action；其他状态只返回归类后的生命周期、活动和运行告警。
- `last_activity_at` 来源于最近持久化事件，无事件时回退到运行创建时间；Worker 在线状态使用数据库租约心跳，orphan reaper 使用独立的 `runtime_workers` 心跳。
- `runs.debug.read` 使用独立 `/debug` endpoint。前端只在用户显式点击后请求脱敏、限长限量的错误分类，并记录读取审计；`runs.control` 提供幂等停止和 checkpoint 恢复，自动恢复耗尽后仍允许人工接管。
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
- 从 Profile 创建的新对局不再回退 legacy 外链头像；历史 Replay 载荷保持不可变。

## Runtime data ownership

- PostgreSQL is the only runtime source for virtual player profiles. Profile API operations return `503` when the database is unavailable.
- Legacy `player_profiles.json` files are migration inputs only and can be imported with `python -m app.cli import-player-profiles --source <path>`.
- Game checkpoints and completed replays are stored in PostgreSQL in `game_sessions` and `game_replay_payloads`.
- Live runs, live SSE events, voice utterances, and voice audio chunks are persisted in PostgreSQL for replay/recovery support.
- Versioned rule parents and immutable revisions are persisted in `rule_sets` and `rule_set_revisions`; production catalog reads never fall back to static definitions.
- Live runs and game sessions retain scalar rule revision provenance plus the pinned snapshot. NULL revision identifies compatible legacy history and is never remapped to the current revision at read time.
- Migration `20260711_05` adds four Admin monitoring indexes: live-run updated pagination, created pagination, status plus updated pagination, and voice counts by run/status.
- Admin sessions and redacted audit events are persisted in PostgreSQL; raw session and CSRF secrets are never stored in the database.
- Public Guest sessions and per-user player favorites are persisted in PostgreSQL. Guest Cookie 丢失后不能跨设备恢复。
- Avatar image assets and legacy avatar migration inputs may still use `WEREWOLF_LOGS_DIR`.
- Active live subscriptions 使用本地队列加 PostgreSQL 事件轮询；运行租约、fencing token、控制信号和单 session 活跃唯一约束允许多 API 副本安全协作。
- 独立 live-run reaper 通过 PostgreSQL 原子认领 orphan，持久化心跳与聚合计数由 `/api/v1/metrics` 暴露给内部 Prometheus。
