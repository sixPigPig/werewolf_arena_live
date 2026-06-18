# 狼人杀独立 mobile-web 设计

**日期**: 2026-06-19
**状态**: 已确认
**范围**: 新增独立移动端 Web 应用，共用现有 FastAPI API，并沿用当前 `apps/web` 的核心交互逻辑。

## 1. 结论

新增 `apps/mobile-web`，作为与 `apps/web` 平级的独立 Vite React 应用。移动端不复用桌面端页面组件、全局样式或路由，但页面结构和交互语义贴近当前 Web：大厅、玩家图鉴、历史、实时观战和复盘都进入第一版。

同时新增 `packages/game-client`，沉淀两个前端共同使用的 API client、类型、对局创建辅助、直播事件推导、导演节奏和上帝视角数据推导。这样 mobile-web 和现有 web 共用 API 与核心逻辑，UI 层仍各自独立。

移动端适配采用 px2rem，按 375px 设计基准配置 `rootValue: 37.5`。页面面向手机竖屏，超宽视口居中展示移动宽度。

## 2. 背景

当前仓库是 pnpm workspace：

- `apps/api`: FastAPI 后端，暴露 `/api/v1/...`。
- `apps/web`: Vite React 桌面 SPA，提供大厅、玩家库、历史、直播和复盘。

最近历史中曾存在 `apps/mobile-web`，后续整包删除。旧移动端应用证明独立 app 结构可行，但它的交互比当前 `apps/web` 简化，且样式直接使用 px，没有 px2rem 适配。本次新 mobile-web 不直接恢复旧实现，而是在当前 Web 逻辑基础上重新设计。

用户确认的方向：

- 第一版覆盖完整核心流程。
- px2rem 使用 375px 基准。
- 采用接近当前 Web 的轻量移植方案，而不是重新发明移动端任务流。
- 玩家库管理第一版只做浏览和开局选择，新建、编辑、删除、头像上传或生成后续补。

## 3. 目标

- 新增 `apps/mobile-web`，可独立开发、构建、测试和运行。
- 共用现有 `apps/api`，不新增移动端专属后端。
- 让 mobile-web 的交互逻辑与当前 `apps/web` 对齐：创建对局、规则选择、席位配置、随机补齐、收藏补齐、清空席位、最大轮数、种子、实时观战、暂停、倍速、追到最新、失败恢复、历史复盘。
- 抽出 `packages/game-client`，减少两个前端复制 API 和纯逻辑代码。
- 使用 px2rem 建立移动端自适应方案。
- 保持桌面端现有行为不变。

## 4. 非目标

- 不把桌面端 UI 组件直接搬到移动端。
- 不修改 FastAPI 合约，除非实现阶段发现前端无法可靠表达现有流程。
- 不在第一版实现玩家新建、编辑、删除、头像上传或头像生成。
- 不做 PWA、离线模式、推送通知或原生壳。
- 不优先适配横屏和平板复杂布局。大屏只居中展示移动端宽度。
- 不把调试面板做成移动端主流程。直播调试能力进入抽屉或折叠区。

## 5. 项目结构

新增 workspace package：

```text
packages/game-client/
  package.json
  tsconfig.json
  src/
    api/
    live/
    lineup/
    types.ts
    index.ts
```

新增移动端应用：

```text
apps/mobile-web/
  index.html
  package.json
  vite.config.ts
  postcss.config.js
  eslint.config.js
  tsconfig.json
  tsconfig.app.json
  tsconfig.node.json
  src/
    app/
    components/
    layout/
    pages/
    routes/
    styles/
    tests/
```

根目录补充脚本：

```json
{
  "dev:mobile": "pnpm --dir apps/mobile-web dev",
  "build:mobile": "pnpm --dir apps/mobile-web build",
  "lint:mobile": "pnpm --dir apps/mobile-web lint",
  "test:mobile": "pnpm --dir apps/mobile-web test -- --run"
}
```

`Makefile` 补充 `mobile-web` 目标，端口使用 `5174`。现有 `make web` 继续指向桌面端 `5173`。

## 6. 共享逻辑

`packages/game-client` 负责无 UI 依赖的代码：

- API client: `apiFetch`、游戏、规则集、模型、玩家档案、直播 run、复盘相关请求。
- API 类型: `RuleSetSummary`、`GameRun`、`LiveGameEvent`、`VirtualPlayerProfile`、`GameReplay` 等。
- 数据适配: replay normalizer、投票 tally、调试条目整理。
- 席位逻辑: `randomFillEmptySeats`、`resizeLineupForPlayerCount`、`removeInvalidProfileRefs`、`summarizeLineup` 等。
- 直播逻辑: `buildDirectorCues`、`useLiveDirector` 可拆成纯 duration/cue 逻辑和 React hook。
- 观战推导: `deriveLiveSpectatorState`、`deriveGodViewState`、直播标签和状态派生。

`apps/web` 改为引用 `packages/game-client`，保持页面结构和视觉不变。`apps/mobile-web` 也从同一包引用 API 和纯逻辑。

React hook 的处理原则：

- 与 UI 无关且两个应用都会用的 hook 可以放入 `packages/game-client`，例如 SSE 事件 hook。
- 依赖导航、页面状态或移动端抽屉的 hook 留在对应 app。
- 共享包不导入 `react-router-dom` 页面组件，不导入 CSS，不导入桌面端组件。

## 7. 移动端路由

移动端采用与当前 Web 语义接近的路由：

```text
/                         -> 重定向到 /games
/games                    -> 移动大厅和创建对局
/players                  -> 玩家图鉴
/games/history            -> 对局历史
/games/live/:runId        -> 实时观战
/games/playback/:sessionId -> 移动复盘
/games/:sessionId         -> 对局详情摘要，可复用移动复盘入口或跳转到 playback
```

这样手机端 URL 与桌面端核心路径保持接近，减少用户和代码理解成本。

## 8. 移动大厅

`/games` 保留当前 Web 创建对局工作台的核心行为：

- 加载规则集和玩家档案。
- 默认选择 `classic_8` 或后端返回的首个规则集。
- 规则切换后按玩家数调整席位，移除超出席位并展示提示。
- 展示席位条和当前席位详情。
- 支持从玩家库选择 profile 到席位。
- 支持随机补齐空席位。
- 支持只从收藏玩家补齐。
- 支持清空席位。
- 支持最大轮数输入，范围 1 到 20。
- 支持 seed 输入。
- 发起对局前自动补齐空席位。
- 玩家库不足时提示需要的玩家数和当前可用数，并引导到玩家页。
- 创建成功后进入 `/games/live/:runId`。

手机承载方式：

- 顶部为品牌和当前大厅操作。
- 规则选择使用卡片或横向分段列表。
- 席位工作台从桌面三栏改为上下分区：席位条、当前席位、玩家选择列表。
- 操作区使用底部 sticky bar，包含最大轮数、seed 和发起对局按钮。
- 次要操作使用折叠区或工具栏，避免挤压主按钮。

## 9. 玩家图鉴

`/players` 第一版只读浏览玩家库，服务于开局选择：

- 加载玩家档案列表。
- 展示头像、昵称、模型、标签、收藏状态和短描述。
- 支持搜索或简单筛选，具体实现以现有数据字段为准。
- 支持查看玩家详情摘要。
- 当玩家 API 返回 `503` 时展示数据库不可用提示。

不包含：

- 新建虚拟玩家。
- 编辑玩家资料。
- 删除玩家。
- 上传头像。
- AI 生成头像或档案草稿。

页面可以预留“编辑能力后续补”的非主流程提示，但不阻塞浏览和开局选择。

## 10. 对局历史与复盘

`/games/history` 保留当前 Web 历史页语义：

- 加载对局列表。
- 支持刷新。
- 按手机卡片流展示 session id、规则、状态、胜方、轮数、创建时间。
- 对未完成或失败且可恢复的对局展示“继续对局”。
- 恢复成功后进入 `/games/live/:runId`。
- 完成对局进入移动复盘。

移动复盘第一版聚焦摘要和阶段列表：

- 展示对局基础信息、胜方、玩家身份和轮次摘要。
- 按夜晚、警长竞选、白天发言、投票、总结等阶段折叠展示。
- 调试原始动作和 LLM 日志默认折叠，不作为移动端首屏内容。

## 11. 实时观战

`/games/live/:runId` 复用当前 Web 的直播数据逻辑：

- 查询 run 详情。
- 连接 `GET /api/v1/games/runs/{runId}/events` SSE。
- 接收并排序事件。
- 使用导演节奏控制当前展示事件。
- 推导 spectator state 和 god view state。
- 处理 completed 和 failed terminal event。
- terminal 后刷新历史列表和 run query。
- 对 failed run 支持恢复，恢复成功进入新的 live run。

移动端布局：

- 顶部显示规则名、session、连接状态、暂停、倍速、追到最新。
- 主区域显示当前行动者、阶段、发言或结算信息。
- 席位概览显示存活、身份组、警长、当前发言者、投票状态。
- 最近事件展示 2 到 3 条关键事件。
- 完整事件、调试追踪、恢复对局等放入抽屉或折叠面板。
- 完成后展示“查看复盘”。

连接状态：

- idle: 尚未连接。
- connecting: 正在连接。
- open: 已连接。
- error 或 reconnecting: 连接异常，允许重连或等待自动恢复。
- closed: terminal event 后关闭。

如实现阶段继续沿用当前 `useGameRunEvents` 的单次 EventSource 行为，移动端需要明确展示错误状态；若要恢复旧 mobile 的自动重连和 `after_id`，应放入共享 hook 并用单测覆盖。

## 12. px2rem 适配

移动端使用 375px 设计基准：

- `rootValue: 37.5`。
- 设计稿中的 `37.5px` 转为 `1rem`。
- 普通样式可按 px 编写，由 PostCSS 转换为 rem。
- 1px 边框、第三方样式或不适合转换的值使用忽略规则。
- 根字号根据视口宽度计算，并设置最大宽度约束。
- 目标移动内容宽度为 320px 到 480px。
- 大于 480px 的视口居中展示移动端容器。

建议基础策略：

```text
html font-size = min(viewportWidth, 480) / 10
px2rem rootValue = 37.5
```

CSS 关键要求：

- 使用 `100svh` 减少移动浏览器地址栏影响。
- 使用 `env(safe-area-inset-bottom)` 保护底部导航和 sticky action bar。
- 主内容区使用 `flex: 1 1 auto; min-height: 0; overflow: auto`。
- 固定格式组件使用稳定尺寸、`min-width: 0` 和 `overflow-wrap`，避免长文本撑坏布局。
- 触控目标不小于 44px 对应的 rem 尺寸。

## 13. 视觉原则

mobile-web 延续狼人杀竞技场的暗色、暖金、红色危险态和舞台语言，但降低桌面端装饰密度。

设计原则：

- 移动端优先可读性和操作效率。
- 不做桌面端缩放版。
- 避免多层卡片嵌套。
- 关键信息不依赖 hover。
- 顶部和底部导航稳定，内容滚动不遮挡主操作。
- 按钮、输入、分段控件、抽屉和列表使用移动端自己的组件。

## 14. 错误处理

第一版需要覆盖这些错误态：

- API 不可用。
- 玩家档案数据库不可用。
- 规则集加载失败。
- 玩家库数量不足。
- 创建对局失败。
- run 不存在或读取失败。
- SSE 连接失败。
- 恢复对局失败。
- 复盘读取失败。

错误信息应就近展示，并提供可执行动作：刷新、返回大厅、去玩家页、重试恢复或查看历史。

## 15. 测试策略

共享包测试：

- API adapter 和 replay normalizer。
- lineup 工具：随机补齐、收藏补齐、规则切换 resize、非法 profile 清理、重复选择。
- live director：cue 构建、暂停、倍速、追到最新、terminal 起点。
- live spectator 和 god view 推导。

桌面端回归：

- 迁移到 `packages/game-client` 后运行现有 `apps/web` 单测。
- 运行 `pnpm --dir apps/web build`，确保行为和类型不变。

移动端测试：

- 路由默认跳转到 `/games`。
- 大厅加载规则和玩家，发起对局成功后进入 live。
- 最大轮数校验。
- 玩家不足提示。
- 随机补齐和收藏补齐调用共享 lineup 逻辑。
- 直播页显示连接状态、事件摘要、terminal 后复盘入口。
- 历史页刷新、恢复对局和复盘跳转。
- 玩家页 API 错误和空列表状态。

构建检查：

- `pnpm --dir packages/game-client test` 或对应 workspace 测试命令。
- `pnpm --dir apps/web test -- --run`。
- `pnpm --dir apps/mobile-web test -- --run`。
- `pnpm --dir apps/web build`。
- `pnpm --dir apps/mobile-web build`。

## 16. 实施顺序

建议按这个顺序实施：

1. 建立 `packages/game-client`，迁移纯逻辑并保持 `apps/web` 测试通过。
2. 创建 `apps/mobile-web` 基础 Vite app、路由、QueryClient、px2rem 配置和移动 shell。
3. 实现移动大厅和创建对局。
4. 实现玩家图鉴只读列表。
5. 实现历史列表和恢复对局。
6. 实现实时观战页。
7. 实现移动复盘摘要。
8. 补齐 README、Makefile、根 package 脚本和验证命令。

每一步都应保持桌面端测试和构建可运行，避免共享逻辑迁移破坏现有 Web。
