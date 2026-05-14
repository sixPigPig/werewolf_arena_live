# Gothic Button Design Spec

**日期**: 2026-05-13
**范围**: 为 `apps/web` 的通用 `Button` 增加哥特按钮皮肤，基于用户提供的六张按钮底图，形成可复用、可伸缩、保留现有 API 兼容性的按钮组件设计。

## 1. 背景

当前 `apps/web/src/components/ui/index.tsx` 已有通用 `Button`，支持 `asChild`、`color`、`variant`、`size`、`loading`、`disabled` 等能力。历史页里还有 `history-top-button`、`history-resume-button` 等手写哥特风样式，但这些样式是局部的，无法被大厅、直播页、复盘页复用。

用户提供的六张图片分别代表同一按钮结构的六种语义色：

- `gothic-button-default.png`: 默认黑钢灰。
- `gothic-button-info.png`: 信息冷灰。
- `gothic-button-primary.png`: 主操作深蓝。
- `gothic-button-danger.png`: 危险红。
- `gothic-button-success.png`: 成功绿。
- `gothic-button-warning.png`: 警告金棕。

图片尺寸均为 `849 x 306`、RGBA 透明背景。视觉特征是长条石质内底、金属边框、复杂四角、左右尖刺装饰和上下细线高光。核心挑战是：不能把整图简单 `background-size: 100% 100%` 拉伸，否则短按钮会压扁装饰，长按钮会拉花边框。

## 2. 目标

- 在现有 `Button` 上新增一套可选的哥特皮肤，不破坏当前按钮调用。
- 将六张图片抽象成同一组件的六种 `intent`，用于语义化表达操作等级。
- 支持不同按钮宽度、现有三个尺寸、中文文本、链接式按钮和 loading/disabled 状态。
- 保留图片里的金属角、尖刺、边框和中心纹理，不做低保真纯 CSS 复刻。
- 让历史页现有局部按钮样式可以逐步迁移到通用 `Button`。

## 3. 非目标

- 不重做全站所有按钮的视觉体系；默认按钮继续保持现有样式。
- 不引入新的 UI 库或图标库。
- 不把按钮做成 Canvas、SVG 动画或逐帧贴图。
- 不在本次按钮组件中实现声音、粒子、复杂动画。
- 不改变业务路由、数据流或后端接口。

## 4. 推荐方案

扩展现有 `Button`，增加 `skin` 和 `intent`：

```tsx
<Button skin="gothic">默认按钮</Button>
<Button skin="gothic" intent="primary">开始游戏</Button>
<Button skin="gothic" intent="danger" loading>处决玩家</Button>
<Button skin="gothic" intent="success" asChild>
  <Link to="/games">返回大厅</Link>
</Button>
```

建议类型：

```ts
type ButtonSkin = "default" | "gothic";

type ButtonIntent =
  | "default"
  | "info"
  | "primary"
  | "danger"
  | "success"
  | "warning";
```

兼容策略：

- `skin` 默认值为 `"default"`，现有调用不需要改动。
- `intent` 只在 `skin="gothic"` 时生效，默认 `"default"`。
- 原有 `color` 和 `variant` 继续服务现有按钮。为了减少迁移风险，先不强行废弃 `color`。
- 如果调用方同时传入 `skin="gothic"` 和 `color`，优先使用 `intent`；没有 `intent` 时可按 `color` 做向后映射。

推荐映射：

```ts
const gothicIntentFromColor = {
  amber: "warning",
  cyan: "info",
  gray: "default",
  green: "success",
  orange: "warning",
  pink: "primary",
  red: "danger",
  violet: "primary",
};
```

## 5. 资源策略

将六张图片复制到：

```text
apps/web/src/assets/gothic-buttons/
  gothic-button-default.png
  gothic-button-info.png
  gothic-button-primary.png
  gothic-button-danger.png
  gothic-button-success.png
  gothic-button-warning.png
```

在 `apps/web/src/styles/index.css` 中通过相对路径引用：

```css
.gothic-button[data-intent="primary"] {
  --gothic-button-image: url("../assets/gothic-buttons/gothic-button-primary.png");
}
```

这样资源会被 Vite 打包、哈希和缓存管理，不依赖用户本地 `Documents/Codex/...` 路径。

## 6. 渲染结构

按钮仍然是原生 `button` 或 `asChild` 克隆出来的可交互元素。哥特皮肤只改变 class 和内部视觉层：

```tsx
<button className="gothic-button" data-intent="primary">
  <span className="gothic-button-label">开始游戏</span>
</button>
```

CSS 层次：

- `.gothic-button`: 定义布局、尺寸、文字、状态和 CSS 变量。
- `.gothic-button::before`: 使用九宫格 `border-image` 绘制图片边框和中心填充。
- `.gothic-button::after`: 绘制 hover、active、disabled 的内发光或暗角，不承担主体图形。
- `.gothic-button-label`: 确保文字在最上层，支持省略和 loading 文案。

## 7. 九宫格拉伸方案

使用 `border-image` 而不是整图拉伸：

```css
.gothic-button::before {
  position: absolute;
  inset: 0;
  border: var(--gothic-button-border) solid transparent;
  border-image-source: var(--gothic-button-image);
  border-image-slice: var(--gothic-button-slice) fill;
  border-image-width: var(--gothic-button-border);
  border-image-repeat: stretch;
  content: "";
  pointer-events: none;
}
```

初始校准值：

```css
--gothic-button-slice: 92 150 72 150;
--gothic-button-border: 18px;
```

实现时需要用浏览器截图微调这两个值。原则是：

- 左右 `150px` 切片保留尖刺、侧边装饰和四角弧形。
- 上 `92px`、下 `72px` 保留上下金属边框和底部高光。
- 中心区域允许横向拉伸，用图片本身的石纹填充。
- 按钮最小宽度需要大于左右切片视觉占位，避免装饰互相挤压。

## 8. 尺寸规则

哥特按钮比普通按钮需要更大的最小尺寸，以容纳左右装饰：

```text
size="1": height 32px, min-width 128px, padding-inline 28px
size="2": height 40px, min-width 156px, padding-inline 34px
size="3": height 48px, min-width 190px, padding-inline 42px
```

移动端规则：

- 保持 `min-width`，但允许调用方通过 `className="w-full"` 做整行按钮。
- 文本默认 `white-space: nowrap`、`overflow: hidden`、`text-overflow: ellipsis`。
- 顶部导航等窄区域优先使用 `size="1"`。
- 不为哥特按钮设计极小图标按钮；图标按钮应继续使用普通按钮或单独的 icon button。

## 9. 状态设计

基础状态：

- 默认：显示对应 intent 的图片、暖色文字、轻微文字阴影。
- Hover：提高亮度和下沿辉光，`transform: translateY(-1px)`。
- Active：轻微下压，降低辉光，模拟金属按钮被按下。
- Focus-visible：使用清晰外环，不只依赖图片高光。
- Disabled：降低饱和度和透明度，移除 hover 位移，显示不可点击光标。
- Loading：沿用现有 `loading` 行为，按钮 disabled，文案为 `处理中...`。

每个 intent 的文字和 focus 色：

```text
default: 文字 #f4e3cd, focus #d8b58a
info:    文字 #d9e7f3, focus #9bc6e8
primary: 文字 #d7ecff, focus #67b7ff
danger:  文字 #ffd1c8, focus #ff765f
success: 文字 #d8f2d2, focus #7edb7a
warning: 文字 #f7dfad, focus #e2b765
```

## 10. 组件边界

`Button` 负责：

- 根据 `skin` 分流普通按钮和哥特按钮 class。
- 保持原有 `asChild`、`loading`、`disabled`、`type`、`size` 行为。
- 把 `data-intent` 输出给 CSS。
- 保持 `className` 可追加，供页面控制宽度或间距。

CSS 负责：

- 图片资源绑定。
- 九宫格边框。
- 不同 intent 的文字、focus 和状态光效。
- 响应式尺寸。

页面组件负责：

- 选择合适的 `intent`。
- 在窄布局中决定是否 `w-full`。
- 不再为常规哥特按钮复制局部 CSS。

## 11. 迁移计划

第一步只实现通用能力，并替换最明显的现有局部按钮：

- `GameHistoryPage` 顶部 `返回大厅`: `skin="gothic" intent="default" size="1"`。
- `GameHistoryPage` 顶部 `刷新列表`: `skin="gothic" intent="danger" size="1"`。
- `SessionList` 里的 `继续对局`: `skin="gothic" intent="warning"` 或 `intent="success"`。推荐 `success`，因为它表示继续进行中的正向操作。

局部类可以保留布局职责，但移除重复的按钮绘制职责：

- `history-top-button` 只保留最小宽度或导航布局相关样式。
- `history-refresh-button` 不再承担红色视觉。
- `history-resume-button` 不再承担金属按钮视觉。

后续页面可按需迁移：

- 大厅主 CTA: `primary`。
- 危险或重试操作: `danger`。
- 状态性辅助操作: `info`。

## 12. 测试策略

组件测试：

- 默认 `Button` 不传 `skin` 时保持现有 class 和 disabled/loading 行为。
- `skin="gothic"` 时输出 `gothic-button` 和正确 `data-intent`。
- `asChild` 模式下，`Link` 能获得 gothic class。
- `loading` 时按钮 disabled，并显示现有 loading 文案。

页面测试：

- 历史页仍能渲染 `返回大厅`、`刷新列表`、`继续对局`。
- resume loading 时按钮不可点击。

构建验证：

```bash
cd apps/web && pnpm test -- --run
cd apps/web && pnpm build
```

视觉验证：

- 在桌面宽度查看历史页顶部导航和历史列表。
- 在 `760px`、`520px` 附近检查文本不溢出、不遮挡。
- 检查六种 intent 的 hover、active、focus-visible、disabled。
- 确认图片透明外沿没有黑底硬边，边框切片没有明显错位。

## 13. 风险与缓解

- 风险：`border-image` 切片不准导致角和边错位。
  缓解：先以历史页三个按钮为样本微调切片，再检查所有 intent。

- 风险：哥特按钮最小宽度过大，挤压顶部导航。
  缓解：导航使用 `size="1"`，移动端隐藏非核心操作或使用普通图标按钮。

- 风险：图片资源体积增加。
  缓解：六张 PNG 总量可接受；若后续体积明显影响首屏，再考虑压缩或 WebP 版本。

- 风险：语义色和现有 `color` 并存导致 API 混乱。
  缓解：文档中推荐新代码使用 `intent`，旧代码保留 `color`。实现时让 `skin="gothic"` 的分支清晰独立。

## 14. 验收标准

- `Button` 可用 `skin="gothic"` 渲染六种 intent。
- 哥特按钮在不同宽度下不明显扭曲四角和左右装饰。
- 现有普通按钮视觉和行为不回归。
- 历史页至少三个按钮迁移到通用哥特按钮。
- 前端测试和构建通过。
- 浏览器视觉检查确认桌面和移动端没有文字溢出、按钮重叠或空白图片。
