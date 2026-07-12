# Mobile Web 唯一 C 端设计

状态：已实施。旧 `apps/web` 已退役，`apps/mobile-web` 是唯一 C 端。

## 产品边界

- 正式支持 iOS Safari 与 Android Chrome 最近两个主要版本。
- 正式支持 320～480 CSS px 的移动设备竖屏。
- 横屏、平板和桌面浏览器不进入发布验收，也不通过 User-Agent 主动封禁。
- Admin 继续独立部署，不在 C 端暴露内容编辑、运行控制和诊断数据。

## 页面与数据边界

| 页面 | 路由 | 主要 API |
|---|---|---|
| 对局大厅 | `/games` | Rule Sets、Public Profiles、Guest Favorites、Create Run |
| 实时观战 | `/games/:runId/live` | Run、SSE Events、Voice Stream |
| 直播回放 | `/games/:sessionId/live-replay` | Playback、Persisted Events/Voice |
| 普通复盘 | `/games/:sessionId/replay` | Playback |
| 玩家图鉴 | `/players`、`/players/:profileId` | Public Profiles、Guest Favorites |
| 对局记录 | `/history` | Games、Resume Run |

Public Profile 和收藏保持 `/api/v1/public/*` 会话边界。现有 `/api/v1/games*` 被定义为 C 端对局契约；后续如迁移到 `/public/games*`，必须先在 `game-client` 内完成，不允许页面直接拼接第二套地址。

## 运行拓扑

```text
Mobile browser
  -> Mobile Ingress
  -> werewolf-mobile-web:8080
       -> hashed static assets
       -> /api/* same-origin proxy
            -> werewolf-api:8000
                 -> PostgreSQL
                 -> model/TTS providers
```

Mobile Nginx 负责 SPA fallback、同源 API/WebSocket/SSE 代理、安全响应头与缓存策略。`index.html` 不缓存，hash 资源使用一年 immutable 缓存，`/api/v1/metrics` 不允许从公网入口访问。

## 性能与交互门禁

- 初始 JavaScript gzip 总量不超过 200 KiB。
- 单张图片不超过 3.2 MiB；规则卡和非首屏图片使用延迟解码/加载。
- 页面按路由拆包，大厅、观战、回放和玩家页不进入同一个业务 chunk。
- 触摸目标至少 44px，固定底栏兼容 `safe-area-inset-bottom`。
- 320px、390px、412px 三种视口不得产生页面级横向滚动。
- 首次开启声音必须由用户手势触发，弱网断线后从持久事件继续播放。

`scripts/check-mobile-bundle.mjs` 在生产构建后执行静态预算检查。Playwright 使用三个 Chromium 移动视口验证主导航和横向溢出；业务状态仍由 Vitest 覆盖，真实模型和 TTS 不进入浏览器测试。

## 发布门禁

1. API、game-client、mobile-web、admin-web lint/test/build 全部通过。
2. Mobile Playwright 三个视口通过。
3. API 与 Mobile/Admin 容器能够独立构建。
4. staging/production Kustomize 输出包含 Mobile Deployment、Service、Ingress 和不可变镜像 SHA。
5. 数据库迁移完成后导入 `apps/api/resources/judge-voice-seed`，再启动 API、worker、reaper 和 Web 应用。
