# 大厅透明哥特边框组件设计

**日期**: 2026-06-17
**范围**: 将用户提供的横向哥特边框图处理为透明、安全留边的可伸缩边框资产，并在 `/games` 大厅组局工作台的四个红框区域统一使用新的边框组件。

## 1. 结论

采用透明九宫格边框组件方案。图像素材只承担装饰边框，面板内部继续使用现有暗色大厅背景、滚动列表和业务内容。

本轮会新增一套轻量边框组件，用于：

- 规则选择栏。
- 组建阵容栏。
- 玩家卡牌库栏。
- 底部操作条。

实现重点是保留图一的四角蓝宝石、黑钢尖角和细边框质感，同时让中间完全透明、内容不被边框压住，并适配四块区域不同宽高。

## 2. 背景

当前大厅三栏组局台已经接近用户截图中的结构，但红框区域仍主要依靠 CSS 细线、内描边和暗色渐变。用户提供的新图是一张完整矩形边框图，视觉更接近目标效果。

源图是 `1672 x 941` RGB PNG，画面中有棋盘格背景但不是真透明。不能直接当成透明资源使用，也不适合整图 `background-size: 100% 100%` 拉伸，否则四角会变形，长条底部操作栏也会压扁角饰。

## 3. 目标

- 将源图处理为真实透明 PNG，去除棋盘格背景。
- 保留边框外侧安全边距，避免角饰贴边或被容器裁切。
- 生成适合 Web 组件使用的边框资产，放入 `apps/web/src/assets` 并由 Vite 打包。
- 新增可复用边框组件，不把装饰 DOM 和样式散落到业务组件中。
- 用同一组件覆盖大厅四块目标区域，保持标题、按钮、输入框、列表滚动和表单提交行为不变。
- 用自动化测试保护组件结构、资产引用和大厅套用范围。

## 4. 非目标

- 不重新设计大厅信息架构。
- 不改变规则选择、席位选择、玩家筛选、随机填充、清空阵容或发起对局逻辑。
- 不重做规则卡、玩家卡、按钮皮肤或全局背景。
- 不把现有 `GothicPanel` 或 `Container` 全站替换为新组件。
- 不引入 Canvas、SVG 动画或新的 UI 依赖。

## 5. 方案选择

### 5.1 采用方案：透明九宫格边框组件

从源图生成透明边框资产，并拆分为四角和四边。组件渲染独立装饰层和内容层：

```tsx
<GothicBorderFrame as="section" className="lobby-workbench-column">
  ...
</GothicBorderFrame>
```

选择理由：

- 四角独立显示，蓝宝石和尖角不会被拉伸。
- 横边只沿 X 轴延展，竖边只沿 Y 轴延展，更适合三栏面板和底部操作条这类不同宽高容器。
- 中间透明，不遮挡现有深色面板背景和内容层。
- 安全内距可通过 CSS 变量调节，避免边框压住标题、卡片或底部按钮。
- 与现有 `Container`、`GothicPanel` 的分层模式一致，便于测试和维护。

### 5.2 未采用方案

整图作为 `border-image` 使用代码更少，但安全边距、角饰比例和长条操作栏效果难以稳定控制。

复用现有 `GothicPanel` 代码最少，但它是厚重装饰面板，内容留白过大，会压缩大厅现有高密度操作界面。

## 6. 资产处理

新增生产资产目录：

```text
apps/web/src/assets/lobby-border-frame/
  source-transparent.png
  frame-corner-tl.png
  frame-corner-tr.png
  frame-corner-br.png
  frame-corner-bl.png
  frame-edge-top.png
  frame-edge-right.png
  frame-edge-bottom.png
  frame-edge-left.png
```

处理步骤：

1. 读取用户提供的源图。
2. 去除棋盘格和近白背景，保留黑钢、金属高光、蓝宝石和必要阴影。
3. 在成品图外侧保留透明安全边距。
4. 按边框结构切出四角和四边。
5. 确认分片均为 RGBA PNG，透明区域真实透明。

实现时可以保留 `source-transparent.png` 作为可审查的处理结果。组件实际引用分片，避免整图拉伸。

## 7. 组件设计

新增组件：

```text
apps/web/src/components/ui/GothicBorderFrame.tsx
apps/web/src/components/ui/GothicBorderFrame.test.tsx
```

组件属性：

```ts
type GothicBorderFrameProps = HTMLAttributes<HTMLElement> & {
  as?: "article" | "aside" | "div" | "footer" | "section";
  contentClassName?: string;
  density?: "default" | "compact";
};
```

渲染层次：

- 根元素：承载调用方 class、ARIA 和布局角色。
- 装饰层：8 个 frame piece，全部 `aria-hidden`。
- 内容层：包裹 children，保证业务内容在最上层。

组件不处理业务滚动、不发起状态变更、不注入标题文案，只负责边框装饰和安全内距。

## 8. CSS 设计

新增 `.gothic-border-frame` 样式，定义：

- `--gothic-border-frame-corner-inline`
- `--gothic-border-frame-corner-block`
- `--gothic-border-frame-edge-thickness`
- `--gothic-border-frame-content-inset-block`
- `--gothic-border-frame-content-inset-inline`

四角使用 `background-size: contain`，四边分别使用 `repeat-x` 或 `repeat-y`。根元素保持 `isolation: isolate`，装饰层 `pointer-events: none`，内容层 `position: relative; z-index: 1`。

`density="compact"` 用于底部操作条，减少上下内容内距，但仍保留角饰安全区域。

## 9. 大厅套用

`LobbyRuleSelector`、`LobbyLineupWorkbench` 和 `LobbyActionBar` 会从通用 UI 导入新组件。

套用方式：

- `LobbyRuleSelector` 的根 `section` 改为 `GothicBorderFrame as="section"`。
- `LobbyLineupWorkbench` 内部的组建阵容栏改为 `GothicBorderFrame`。
- `LobbyLineupWorkbench` 内部的玩家卡牌库栏改为 `GothicBorderFrame`。
- `LobbyActionBar` 根 `footer` 改为 `GothicBorderFrame as="footer" density="compact"`。

保留现有业务 class，例如 `lobby-workbench-column`、`lobby-lineup-column`、`lobby-player-column` 和 `lobby-action-bar`，使现有布局、滚动和媒体查询继续生效。CSS 中这些 class 的旧边框和内描边会收敛为背景、阴影和布局职责，边框装饰交给新组件。

## 10. 响应式要求

- 桌面端三栏和底部操作条保持图二红框结构。
- 平板端沿用现有断点，边框不改变单栏或双栏切换规则。
- 手机端四块区域仍按文档流排列，边框角饰允许缩小，但内容不能被遮挡。
- 规则列表、阵容栏和玩家列表的滚动区域不能因为新增内容层而失效。

## 11. 测试与验证

自动化测试：

- `GothicBorderFrame.test.tsx` 覆盖根 class、内容层、8 个装饰分片、`aria-hidden` 和 `density` class。
- CSS 资产测试确认 `index.css` 引用了 `apps/web/src/assets/lobby-border-frame` 分片，且没有对源整图做 `100% 100%` 拉伸。
- `GamesPage.test.tsx` 确认四块目标区域都带有 `gothic-border-frame` 结构，同时保留原有可访问名称和 `data-testid`。

本地验证：

- 运行相关 Vitest。
- 运行前端 build 或至少 TypeScript/Vite 构建。
- 启动本地前端并截图检查桌面和移动视口，确认边框透明、角饰完整、内容无重叠、滚动区域可用。

## 12. 风险与缓解

- 透明抠图可能残留棋盘格：用脚本输出处理图，并在截图中放大检查边缘。
- 底部操作条高度较低，角饰可能抢空间：使用 `density="compact"` 和更小的 CSS 变量。
- 新增内容层可能影响 flex/grid 子项：组件内容层需要显式 `min-width: 0`、`min-height: 0`，大厅列继续由原 class 控制布局。
- 图片分片路径或尺寸变化可能破坏样式：用测试锁定资产引用和组件结构。

## 13. 实施顺序

1. 写组件和大厅套用测试，先观察失败。
2. 处理源图，生成透明源图和九宫格分片。
3. 实现 `GothicBorderFrame` 并导出。
4. 添加 CSS 资产引用、布局变量和响应式调整。
5. 将四个大厅区域改为使用新组件。
6. 跑测试、构建和浏览器截图验证。
