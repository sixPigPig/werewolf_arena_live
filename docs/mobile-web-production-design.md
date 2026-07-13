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

## 实时观战剧场契约

实时观战与直播回放共用同一套 `MobileLiveTheater` 呈现层。剧场在单一视口网格中依次渲染顶栏、夜空横幅、玩家席位、相位感知中央舞台、本轮战报事件栏与控制栏。

- **相位感知行动焦点**：中央舞台根据 `currentEvent` 与 `GodViewState` 派生出行动/投票/结算/技能/终局等焦点卡片，展示行动者或阵营、动作、目标或“未使用”、进度与结果。发言状态保持原有头像与麦克风呈现不变。
- **狼人刀票与最终目标**：每只狼的 `action_parsed/werewolf_kill_vote` 按事件顺序展示行动者、目标与复投轮次；共识形成后再用独立的 `action_parsed/remove` 展示“狼人最终目标”。公开事件只携带行动者、目标、轮次和安全结果，不公开狼人讨论、提示词、推理或模型原始响应。
- **夜间行动法官语音**：夜间用 `judge_cue` 串联狼人、守卫、预言家、女巫的睁眼与闭眼静态语音，角色的 `action_requested` 继续播放选择/技能询问音频。女巫睁眼后、解药询问前额外播放对应座位的 `witch_death_seat_01…12`，明确“今晚被狼人袭击的玩家是 X 号玩家”；公开提示只携带座位引用，不包含狼人候选人、队内讨论或模型内容。
- **上警前置语音**：第一天警长竞选报名开始前发布 `judge_cue/sheriff_raise_hands`，播放语音管理中的 `sheriff_raise_hands` 静态音频“想要竞选警长的玩家请举手”，随后再依次展示玩家是否上警。
- **本轮战报事件栏**：在席位舞台与控制栏之间渲染一行可横向滚动的关键事件芯片，仅消费 `director.currentEventId` 之前的 `eventLines`，不读取未来事件。`全部` 打开分组底部战报抽屉，选择某行调用 `director.seekToEventId`。
- **可访问事件抽屉**：抽屉使用 `role="dialog"`、`aria-modal`、焦点陷阱、Escape 关闭、背景 inert 与触发焦点恢复，遵循 `LobbyModal` 既有语义但不复用大厅组件。
- **导演可见事件边界**：所有行动与战报内容均派生自 `director.currentEventId` 截断后的 `stageEvents`，SSE 追赶与暂停期间不泄露未来行动或票型。
- **关键结算时长**：投票票型更新、放逐、平安夜与夜晚死亡等 `state_updated` 仍为 6000ms 不可压缩关键导播提示，2× 时缩短为 3000ms，不引入第二套 UI 计时器。
- **不依赖语音回放**：行动焦点与事件栏派生自保存事件，即使回放无语音也可阅读。

## 发布门禁

1. API、game-client、mobile-web、admin-web lint/test/build 全部通过。
2. Mobile Playwright 三个视口通过。
3. API 与 Mobile/Admin 容器能够独立构建。
4. staging/production Kustomize 输出包含 Mobile Deployment、Service、Ingress 和不可变镜像 SHA。
5. 数据库迁移完成后导入 `apps/api/resources/judge-voice-seed`，再启动 API、worker、reaper 和 Web 应用。
