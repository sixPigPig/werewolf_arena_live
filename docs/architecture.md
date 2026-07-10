# Architecture Overview

## Applications

- `apps/api`: FastAPI service exposing `/api/v1/...`
- `apps/web`: legacy compatibility SPA retained during C-end migration
- `apps/mobile-web`: independent Vite React mobile SPA and the only C-end surface that continues to evolve
- `apps/admin-web`: independent Vite React admin SPA with a fail-closed auth/session boundary
- `packages/game-client`: shared frontend API client, types, lineup helpers, replay adapters, and live-state derivation

## Local runtime

- PostgreSQL runs in Docker via `docker-compose.yml`
- The API runs locally on `http://localhost:8000`
- The desktop SPA runs locally on `http://localhost:5173`
- The mobile SPA runs locally on `http://localhost:5174`
- The admin SPA runs locally on `http://localhost:5175`

## Request flow

1. The browser loads the SPA from Vite.
2. React Router renders the selected client shell.
3. Admin authenticated development mode first calls `/api/v1/admin/me` with cookie credentials; preview mode makes no API request.
4. The API resolves the server-side Admin session, active user and fixed-role permissions before returning the Admin shell.
5. Mobile 玩家目录使用 `/api/v1/public/player-profiles*`，设备级收藏使用独立 Public Session 与 `/api/v1/public/me/favorite-player-profiles*`；其他游戏流量仍按后续切片迁移。
6. Admin 对局列表与详情只调用 `/api/v1/admin/games*`；普通详情返回白名单诊断摘要，受限错误摘要必须在 `games.debug.read` 下由用户显式请求独立 `/debug`。

## Admin security boundary

- Production `admin-web` builds are currently unconditionally fail closed while the formal identity provider is undecided.
- Local development login requires explicit frontend and backend flags, is limited to development/test, and takes identity and role only from server configuration.
- The browser receives an HttpOnly session cookie; PostgreSQL stores only SHA-256 hashes of session and CSRF secrets.
- `/api/v1/admin/me` returns the current user, permission set, CSRF token and expiry. Admin writes must use the server-side permission dependency and CSRF dependency.
- Admin errors use Problem Details with stable codes and request IDs. Auth responses are `no-store`.
- `audit_events` provides a redacted, bounded audit foundation. 玩家创建、更新、发布、归档和恢复已经记录成功/失败事件，后续 Admin 业务写入必须复用同一入口。
- Admin 对局 API 使用 `games.read` 强制只读访问并返回 `no-store`；列表服务端分页筛选，详情不返回 replay state/log/checkpoint、event payload、prompt、raw response 或私有角色知识。partial/resumable 对局进一步隐藏角色、玩家与运行模型、死亡原因/来源、事件元数据和未完成轮次。
- `games.debug.read` 不扩展普通详情 DTO。前端只有在用户显式点击后才调用独立 debug endpoint；该读取返回分类脱敏、限长限量的错误摘要并记录审计。

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
- Admin sessions and redacted audit events are persisted in PostgreSQL; raw session and CSRF secrets are never stored in the database.
- Public Guest sessions and per-user player favorites are persisted in PostgreSQL. Guest Cookie 丢失后不能跨设备恢复。
- Avatar image assets and legacy avatar migration inputs may still use `WEREWOLF_LOGS_DIR`.
- Active live subscriptions and in-flight model tasks are still coordinated by the in-process `LiveRunRegistry`; production currently assumes one API worker.
- Resume requests are idempotent per active `session_id` within that process.
