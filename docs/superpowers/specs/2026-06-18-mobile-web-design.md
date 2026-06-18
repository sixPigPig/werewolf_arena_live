# 狼人杀独立手机版 Web 设计

**日期**: 2026-06-18
**范围**: 新增一个完全独立于现有 `apps/web` 的手机版 Web 项目，面向手机竖屏完整操作狼人杀竞技场，并复用现有 FastAPI 后端。

## 1. 结论

采用独立移动前端应用方案：新增 `apps/mobile-web`，与现有 `apps/web` 平级纳入 pnpm workspace。移动端共享 `apps/api` 的 `/api/v1/...` 接口，但不共享桌面端路由、页面组件、全局 CSS 或视觉框架。

第一版定位为手机竖屏完整操作体验：

- 手机竖屏优先，目标宽度 `360px` 到 `480px`。
- 使用弹性布局作为基础布局方式，页面以纵向 flex shell、内容弹性滚动区和底部安全区导航组成。
- 底部 Tab 作为主导航。
- 视觉延续现有哥特竞技场风格，但降低装饰密度，避免手机屏幕拥挤。
- “对局”首页同时提供一键开局和自定义开局。
- 直播页采用舞台优先布局，突出当前发言或行动。

## 2. 背景

当前仓库是 pnpm workspace，已有：

- `apps/api`: FastAPI 服务，暴露 `/api/v1/...`。
- `apps/web`: Vite React 桌面 SPA，承载当前大厅、玩家库、直播和复盘页面。

现有桌面端页面有大量面向宽屏工作台的视觉和布局，包括哥特舞台、三栏大厅、历史和直播模块。手机版如果直接塞进 `apps/web`，会持续受到桌面路由、全局样式和组件假设影响，不符合“完全独立于现在的 web”的目标。

## 3. 目标

- 新建 `apps/mobile-web`，可以独立开发、构建、测试和运行。
- 共享现有 API，不重复建设后端。
- 支持手机端完整操作：开局、选玩家、自定义规则、直播观战、历史复盘和基础设置。
- 采用弹性布局，保证手机竖屏下首屏稳定、内容可滚动、底部操作不遮挡内容。
- 建立移动端自己的组件边界和样式系统，避免引入桌面端 CSS 负担。
- 第一版即具备错误态、加载态、空状态和基础测试，不只做静态外壳。

## 4. 非目标

- 不修改 `apps/web` 的桌面路由和页面结构。
- 不把现有桌面端组件抽成公共包作为第一步。
- 不新增后端服务或移动端专属 API。
- 不优先优化横屏、小平板或桌面宽度。大于 `480px` 的开发视口可居中展示手机壳宽度，但不作为完整桌面体验。
- 不在第一版重做复杂玩家编辑器。玩家页优先支持浏览、选择和组合，已有创建/编辑 API 可作为二级表单逐步接入。
- 不做离线模式、推送通知、安装型 PWA 或原生壳。

## 5. 项目边界

新增应用目录：

```text
apps/mobile-web/
  index.html
  package.json
  vite.config.ts
  tsconfig.json
  tsconfig.app.json
  tsconfig.node.json
  eslint.config.js
  src/
```

根目录新增脚本：

```json
{
  "dev:mobile": "pnpm --dir apps/mobile-web dev",
  "build:mobile": "pnpm --dir apps/mobile-web build",
  "lint:mobile": "pnpm --dir apps/mobile-web lint",
  "test:mobile": "pnpm --dir apps/mobile-web test -- --run"
}
```

本地开发端口使用 `5174`，Vite 代理保持 `/api` 到 `http://localhost:8000`。这样可以同时运行：

- 桌面端: `http://127.0.0.1:5173`
- 移动端: `http://127.0.0.1:5174`
- 后端: `http://127.0.0.1:8000`

`Makefile` 可补充 `mobile-web` 目标，但不改变现有 `make web` 行为。

## 6. 技术栈

移动端使用与桌面端相近但独立配置的技术栈：

- React + TypeScript + Vite。
- React Router 管理移动端路由。
- TanStack Query 管理 API 数据、缓存和 mutation。
- Vitest + Testing Library 做组件和路由测试。
- Tailwind 可继续使用，但移动端需要自己的入口 CSS 和 token，不导入 `apps/web/src/styles/index.css`。

第一版不建立 `packages/api-client`。API 封装先放在 `apps/mobile-web/src/api/`，等桌面端和移动端都稳定后，再基于真实重复度决定是否抽公共包。

## 7. 信息架构

底部 Tab 使用 4 个主入口：

1. **对局**: 默认首页。展示当前或最近对局状态、一键开局、自定义开局入口和最近对局摘要。
2. **玩家**: 移动端玩家库。用于浏览虚拟玩家、查看状态、挑选自定义开局阵容。
3. **历史**: 历史对局列表与复盘入口，使用手机竖屏卡片流。
4. **设置**: API 连接状态、默认规则、默认玩家池、模型选项和移动端偏好。

建议路由：

```text
/                         -> 对局首页
/players                  -> 玩家
/history                  -> 历史
/settings                 -> 设置
/custom-game              -> 自定义开局流程
/live/:runId              -> 实时直播
/playback/:sessionId      -> 手机复盘
```

直播页可以保留底部 Tab，但主要操作放在页面内固定行动区或抽屉中，避免用户必须跳出直播上下文。

## 8. 弹性布局规划

移动端布局使用 `MobileAppShell` 作为唯一顶层页面壳：

- 根节点使用 `min-height: 100svh`，避免移动浏览器地址栏变化导致跳动。
- 页面主体采用 `display: flex; flex-direction: column`。
- 顶部状态区、内容区和底部导航分层明确。
- 内容区使用 `flex: 1 1 auto; min-height: 0; overflow: auto`，保证列表、直播事件和表单可以独立滚动。
- 底部 Tab 使用固定高度加 `env(safe-area-inset-bottom)`，避免 iPhone 底部手势区域遮挡。
- 固定主按钮使用页面内 sticky action bar，底部留出导航和安全区空间。
- 卡片、席位条、事件摘要等固定格式组件使用 `minmax(0, 1fr)`、`aspect-ratio`、固定触控高度和 `min-width: 0`，避免动态文本撑坏布局。
- 目标触控区域不小于 `44px`。
- 页面最大内容宽度为 `480px`。大于 `480px` 的视口中，应用居中展示移动宽度，周围使用深色背景。

核心组件：

```text
src/layout/MobileAppShell.tsx
src/layout/MobileTabBar.tsx
src/layout/MobileTopBar.tsx
src/components/FixedActionBar.tsx
src/components/StageCard.tsx
src/components/PlayerSeatStrip.tsx
src/components/EventSummary.tsx
src/components/StatusBanner.tsx
```

## 9. 视觉方向

采用哥特竞技场延续方案，但针对手机做减法：

- 使用深色背景、暖金边线、红色危险状态和冷灰信息层。
- 保留“舞台”“席位”“夜晚/白天”这类品牌语言。
- 避免桌面端厚重边框、过多内描边和密集装饰。
- 页面标题使用更克制的 serif 或中文衬线，仅用于关键标题，不滥用大字。
- 普通操作、表单和列表保持高可读性，文本字号稳定，不随视口宽度缩放。
- 按钮和图标使用明确语义。若引入图标库，优先使用 lucide 图标。

移动端不是桌面端缩放版，而是同品牌下的竖屏操作界面。

## 10. 对局首页

“对局”首页的首屏顺序：

1. 当前或最近对局状态。
2. 醒目的一键开局按钮。
3. 自定义开局入口。
4. 最近历史摘要。
5. API 或数据库状态提示。

一键开局使用默认规则和默认玩家池，调用现有创建 run 接口。失败时必须解释原因，例如：

- 后端不可用。
- 玩家档案数据库不可用。
- 玩家库数量不足。
- 模型配置缺失。
- 规则集不可用。

成功后直接进入 `/live/:runId`。

## 11. 自定义开局

自定义开局采用分步流程：

1. 规则预设: 从规则集接口读取可用规则。
2. 玩家选择: 从玩家库选择或自动补齐玩家。
3. 模型和轮数: 使用现有模型选项和默认轮数。
4. 确认开局: 汇总规则、玩家、模型、警告和开始按钮。

每一步使用竖屏弹性布局：

- 内容区滚动。
- 底部固定主按钮推进。
- 返回按钮回到上一步。
- 当前步骤的错误就近展示。

创建 run 请求使用现有 `POST /api/v1/games/runs`，请求体包含 `rule_set_id`、`player_configs`、`villager_model`、`werewolf_model`、`seed` 和 `max_rounds`。

## 12. 直播页

直播页采用舞台优先：

- 顶部: 阶段、昼夜、轮次、连接状态。
- 主体: 当前发言或行动舞台。
- 辅助: 玩家快捷席位条，展示存活、当前行动者、关键标记。
- 摘要: 最近关键事件 2 到 3 条。
- 行动区: 重连、查看完整事件、结束后查看复盘、再开一局。

完整事件流、全部席位、调试细节和较长说明放入抽屉或二级面板。直播连接使用 `GET /api/v1/games/runs/{run_id}/events` 的 SSE 流，并支持 `Last-Event-ID` 或 `after_id` 恢复。

直播页需要处理这些状态：

- run 创建后等待后台线程启动。
- SSE 已连接。
- SSE 心跳中。
- 连接断开，正在重连。
- 对局完成。
- 对局失败。
- run 不存在或已不可恢复。

## 13. 玩家页

玩家页第一版目标是支持完整开局所需的玩家管理能力，而不是完整桌面编辑器复刻。

主能力：

- `GET /api/v1/player-profiles` 列出玩家。
- 展示头像、昵称、模型、标签、常用状态和更新时间。
- 支持搜索、标签或收藏筛选。
- 支持从玩家页进入自定义开局选择。
- 若接入编辑能力，使用二级页面或底部抽屉承载 `POST /api/v1/player-profiles`、`PATCH /api/v1/player-profiles/{profile_id}` 和头像上传。

如果数据库不可用，页面显示明确 `503` 状态和重试入口。

## 14. 历史与复盘

历史页使用 `GET /api/v1/games` 列出 session，手机端用卡片流展示：

- 对局时间。
- 胜利阵营。
- 规则集。
- 玩家数量。
- 是否可恢复。
- 进入复盘或恢复对局的操作。

复盘页使用：

- `GET /api/v1/games/{session_id}/playback`
- 必要时使用 `GET /api/v1/games/{session_id}`
- 可恢复对局使用 `POST /api/v1/games/{session_id}/resume`

手机复盘以时间线为主，先保证可读和可跳转，不追求桌面端完整工作台密度。

## 15. 设置页

设置页第一版包含：

- API 健康检查: `GET /api/v1/health`。
- 当前后端地址说明。
- 规则集列表: `GET /api/v1/games/rule-sets`。
- 模型选项: `GET /api/v1/games/model-options`。
- 默认开局偏好: 默认规则、默认轮数、是否自动补齐玩家。
- 本地 UI 偏好: 是否压缩事件、是否自动滚动直播。

偏好先保存在浏览器本地存储，不要求后端持久化。

## 16. API 封装

移动端内部 API 模块：

```text
src/api/client.ts
src/api/healthApi.ts
src/api/gamesApi.ts
src/api/liveApi.ts
src/api/playerProfilesApi.ts
src/api/types.ts
```

`client.ts` 负责：

- API base path。
- JSON 请求。
- 统一错误解析。
- `AbortSignal` 支持。

页面不直接写 `fetch`。mutation 成功后由页面负责导航，API 层只返回数据。

## 17. 错误处理

错误处理分三层：

1. 全局状态: API 不可用、连接断开、数据库不可用。
2. 页面状态: 加载、空列表、权限或资源不存在。
3. 操作状态: 一键开局失败、保存失败、重连失败。

错误文案必须面向用户解释下一步，而不是只展示后端 detail。后端 detail 保留在开发信息或可展开区域中。

关键要求：

- 一键开局失败必须说明具体原因。
- 直播断线不直接跳回首页，而是显示重连状态。
- 玩家库和历史加载失败提供重试。
- run 404 时引导用户回到历史或重新开局。

## 18. 测试与验证

自动化测试至少覆盖：

- 移动路由渲染和底部 Tab active 状态。
- 对局首页一键开局成功后导航到 `/live/:runId`。
- 一键开局失败的错误展示。
- 自定义开局玩家选择和确认请求体。
- 直播页主要状态: loading、connected、completed、failed、reconnecting。
- 玩家库加载、空状态和数据库不可用状态。
- 历史页列表和复盘入口。

验证命令：

```bash
pnpm --dir apps/mobile-web test -- --run
pnpm --dir apps/mobile-web lint
pnpm --dir apps/mobile-web build
```

视觉验证：

- 启动 `make api`。
- 启动 `pnpm --dir apps/mobile-web dev --host 127.0.0.1 --port 5174`。
- 使用手机竖屏视口检查 `360px`、`390px`、`430px`、`480px`。
- 检查底部导航不遮挡内容，固定按钮不遮挡表单，直播页事件流可滚动，长昵称不会撑破席位条。

## 19. 风险与缓解

- **现有 API 形状偏桌面**: 第一版只封装当前已存在接口，移动端用适配层整理数据，不要求后端变更。
- **SSE 在移动浏览器中断线频繁**: 直播 hook 记录最后事件 ID，重连时使用 `Last-Event-ID` 或 `after_id`。
- **手机首屏拥挤**: 主页面只放当前最重要的信息，长列表和调试内容进入抽屉或二级页。
- **和桌面端视觉漂移**: 使用同一品牌语言和色彩意图，但移动端独立 token，避免直接复制桌面 CSS。
- **后续公共代码重复**: 第一版接受少量重复，等移动端稳定后再抽 `packages/api-client` 或 `packages/ui-core`。

## 20. 实施顺序

1. 搭建 `apps/mobile-web` Vite React TypeScript 应用和根脚本。
2. 建立移动端 CSS token、`MobileAppShell`、底部 Tab 和基础路由。
3. 封装 API client、health、games、player profiles 和 live SSE hook。
4. 实现对局首页和一键开局。
5. 实现自定义开局流程。
6. 实现舞台优先直播页。
7. 实现玩家、历史、复盘和设置的第一版页面。
8. 补齐错误态、加载态、空状态和测试。
9. 运行 lint、test、build，并用手机竖屏视口做视觉验证。
