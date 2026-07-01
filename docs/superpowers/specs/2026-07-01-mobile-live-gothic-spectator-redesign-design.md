# 移动端哥特观战页改版设计

## 背景

移动端实时观战页已经具备完整的数据流和交互能力：读取实时对局、SSE 事件、导演播放控制、玩家席位、中央舞台、底部暂停/倍速/追最新/继续对局/复盘入口。当前页面的布局已经是竖屏剧场，但视觉仍偏“普通移动 Web 面板”，与用户提供的参考图中“暗黑古堡、金属圆框、左右席位、中央人物、底部发言条”的手游观战页风格存在明显差距。

本次只改 `apps/mobile-web` 的观战页体验。桌面端 `apps/web` 的 God View、回放页、后端实时事件、游戏逻辑、玩家头像资产解析方式都不在本次范围内。

用户选择的方向是“原图复刻剧场”：尽量贴近参考图的竖屏手游古堡感，而不是只做克制换肤。

## 目标

- 将移动端观战页改为更接近参考图的暗黑哥特手游观战界面。
- 保留现有实时观战能力、数据派生逻辑和控制按钮，不改变对局行为。
- 强化顶部规则匾额、中央月环轮次、左右玩家圆形席位、中央发言者肖像位、底部发言控制条。
- 复用现有移动端背景和玩家头像资产，避免引入新的网络依赖。
- 在窄屏和短屏上保持可读、可点击、不重叠。

## 非目标

- 不改桌面端 `apps/web`。
- 不改 `@werewolf-arena/game-client` 的 live state 派生逻辑。
- 不改 API、SSE、游戏引擎、角色规则、倒计时语义。
- 不新增真实 3D、Canvas 或复杂动画系统。
- 不把参考图逐像素还原；重点复刻布局和美术气质。

## 现有结构

入口文件为 `apps/mobile-web/src/pages/LivePage.tsx`：

- `LivePage` 负责读取 run、events、director、spectator/god view state。
- `LiveTheater` 组织顶部栏、轮次区、席位舞台和底部控制区。
- `LiveTheaterTopBar` 显示返回、规则名、连接状态。
- `LiveSkyBanner` 显示当前阶段和日夜轮次。
- `LiveSeatColumn` / `LiveSeatAvatar` 显示左右玩家席位。
- `LiveCenterStage` 显示当前行动/发言玩家。
- `LiveTheaterControls` 显示当前玩家、倒计时和播放控制。

主要样式在 `apps/mobile-web/src/styles/index.css` 的 `.mobile-live-*` 区段。现有测试会检查移动观战页渲染、头像 URL、隐藏底部 tab bar、短屏压缩、字体尺寸等行为。

## 设计方案

### 页面背景

`.mobile-live-page` 和 `.mobile-live-theater` 变成全屏沉浸式古堡剧场：

- 使用现有 `mobile-gothic-castle-background.png` 作为主要背景。
- 叠加顶部暗红帷幕感、左右暗角、底部阴影和冷色月光径向渐变。
- 保留 `min-height: 100svh`、`overflow: hidden` 和安全区 padding。
- 色彩以近黑、冷蓝灰、暗酒红、旧金为主，减少现有偏亮青色月球感。

### 顶部规则区

`LiveTheaterTopBar` 保持结构不大改，但视觉转为参考图顶部导航：

- 返回按钮变成圆形金属按钮，使用 `‹` 符号，尺寸保持可点。
- 中间规则名/状态显示为横向金属匾额，模拟参考图“规则提示”牌。
- 连接状态仍在右侧，使用小型圆章/胶囊徽章，状态文案不变。
- 文本都保持单行省略，避免规则名过长撑破布局。

### 月环轮次区

`LiveSkyBanner` 改造成页面视觉中心上半部分：

- 大型圆形月环放在中央，使用多层 `radial-gradient`、`double` border、内外阴影模拟金属框和月光。
- `phaseLabel` 作为小字放在横向铭牌中。
- `dayNightLabel` 作为大字放在月环中央，形成“第 N 天 / 夜晚”的主信息。
- 月环背后保留古堡尖塔和冷光背景，来自页面背景图与渐变叠层。

### 左右玩家席位

`LiveSeatColumn` / `LiveSeatAvatar` 保持 DOM 和 aria label，不改变数据来源：

- 每个玩家席位从简洁圆头像改为“座位号圆牌 + 圆形肖像框 + 角色短标徽章 + 名称/状态”。
- 左右两列纵向贴边排布，靠近参考图的 1-6 / 7-9 与锁位排列感。
- 角色短标保留现有 `roleShortLabel` 逻辑；狼人、女巫、预言家等使用不同色调圆章，但不依赖新增数据。
- 当前发言玩家使用旧金/红光高亮；出局玩家降低亮度、灰度和透明度。
- 没有头像时继续显示姓名首字。

### 中央发言舞台

`LiveCenterStage` 继续显示当前玩家、状态、事件类型和 action，但视觉变为参考图中央人物区域：

- 中央肖像位使用当前玩家头像；没有头像时用首字占位。
- 肖像容器做成高挑哥特框，带尖拱和金属边缘。
- 玩家编号、名称、阶段状态在肖像下方，用较短的金色文字展示。
- 事件类型和 action 保留，但压缩成底部小字，避免抢主视觉。

需要在 `LiveCenterStage` 中同样解析 `currentPlayer.avatarImageUrl`，目前只在席位头像里解析。该逻辑应复用 `resolveAvatarImageUrl`，不新增 URL 拼接。

### 底部控制条

`LiveTheaterControls` 保留按钮行为：

- 当前玩家、名称和倒计时改成参考图底部发言条：左侧大座位数字，中间玩家名/阶段，右侧倒计时。
- 播放控制按钮改成小型金属按钮，仍保留文字，避免图标改造扩大范围。
- `继续对局`、`复盘` 仍按现有条件显示。
- 按钮保持最小触控高度，不因视觉压缩影响可点性。

## 响应式约束

- 360px 以下宽度：左右席位列收窄，名称和状态继续省略，按钮 gap 缩小。
- 700px 以下高度：月环、头像、中央肖像、底部条继续压缩；席位状态小字可以隐藏。
- 页面不允许纵向滚动作为主要解决方案；观战页应保持一屏沉浸式。
- 文本不能依赖 viewport font scaling，继续使用固定或 clamp 尺寸。
- 长玩家名、长规则名、连接状态都必须省略而不是撑开布局。

## 数据流

数据流保持现状：

1. `LivePage` 读取 run 与事件流。
2. `useLiveDirector` 决定当前播放事件。
3. `deriveLiveSpectatorState` 和 `deriveGodViewState` 派生玩家、阶段、轮次、倒计时等展示状态。
4. `LiveTheater` 将派生状态传给顶部、轮次、席位、中央舞台和底部控制组件。
5. 新视觉只消费已有字段：玩家名、座位号、角色、头像 URL、是否存活、是否发言、阶段状态、倒计时、事件类型、action。

## 错误处理

- 读取失败和继续失败沿用现有 `.mobile-status-banner`，只确保它在沉浸式页面上仍有足够 z-index 和可读背景。
- 无 run 的加载状态仍显示顶部剧场壳，避免空白。
- 无头像时使用首字占位。
- 无当前玩家时中央舞台显示“等待玩家行动”，底部显示“等待行动”和当前倒计时文本。

## 测试策略

更新或保留现有移动端测试：

- `apps/mobile-web/src/pages/LivePage.test.tsx`
  - 观战页仍渲染玩家席位区域。
  - 席位 aria label 不变。
  - 玩家头像仍使用 API 资产 URL。
  - 短屏压缩规则继续存在，但预期值按新尺寸更新。
- `apps/mobile-web/src/app/App.test.tsx`
  - 移动端观战页仍隐藏底部 tab bar。
  - 字体尺寸检查按新中央舞台标题样式保持紧凑。

手工验证：

- 启动移动端 dev server。
- 打开移动端观战路由或测试可访问的 live 页面。
- 在 390x844、360x640、430x932 三类尺寸下检查：背景、顶部、月环、左右席位、中央肖像、底部控制条都不重叠。

## 实施边界

预计只修改：

- `apps/mobile-web/src/pages/LivePage.tsx`
- `apps/mobile-web/src/styles/index.css`
- 必要时更新 `apps/mobile-web/src/pages/LivePage.test.tsx`
- 必要时更新 `apps/mobile-web/src/app/App.test.tsx`

不会修改：

- `apps/web`
- `packages/game-client`
- `apps/api`
- 现有头像资产文件
