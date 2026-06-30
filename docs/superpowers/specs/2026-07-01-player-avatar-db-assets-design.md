# 玩家头像数据库资产设计

## 目标

让玩家卡牌库、移动端 Web、桌面端 Web、直播和复盘都使用同一套由后端 API 服务的玩家图片。头像图片本体进入 PostgreSQL，玩家资料只引用头像资产 ID，不再把某个前端应用的静态路径当成跨端数据。

本次修复针对当前问题：数据库中的玩家资料保存了 `/player-avatars/gothic-*.png`，但这些文件只存在于 `apps/web/public/player-avatars`，`apps/mobile-web` 无法正确加载。

## 方案

### 数据所有权

PostgreSQL 成为虚拟玩家档案和头像资产的运行时权威数据源。

新增 `player_avatar_assets` 表：

- `id`: 字符串主键。系统头像使用稳定 ID，例如 `system-gothic-male-1`；上传头像使用 UUID。
- `source`: `system`、`uploaded` 或 `migrated`。
- `content_type`: `image/png`、`image/jpeg` 或 `image/webp`。
- `data`: 图片二进制。
- `sha256`: 图片内容哈希，用于幂等导入和排查重复资产。
- `size_bytes`: 图片大小。
- `created_at`: 创建时间。

`virtual_player_profiles` 新增 `avatar_asset_id`，可空，外键指向 `player_avatar_assets.id`。

保留现有字段 `avatar_image_url`、`avatar_image_path`、`avatar_image_mime` 做兼容。新逻辑中：

- 有 `avatar_asset_id` 时，API 响应的 `avatar_image_url` 由后端生成。
- `avatar_image_mime` 来自关联资产的 `content_type`。
- `avatar_image_path` 不再用于新数据。
- 没有 `avatar_asset_id` 的旧数据继续按旧字段返回，直到迁移命令能补齐。

### 系统头像资产

四张系统头像从桌面端 public 静态目录迁到后端包内的 seed 资产目录，例如：

```text
apps/api/app/assets/player_avatars/
  gothic-male-1.png
  gothic-male-2.png
  gothic-female-1.png
  gothic-female-2.png
```

这些文件只作为数据库初始化输入。运行时图片读取只经过数据库和 API，不依赖前端静态目录。

系统头像映射：

```text
appearance_id=gothic-male-1   -> avatar_asset_id=system-gothic-male-1
appearance_id=gothic-male-2   -> avatar_asset_id=system-gothic-male-2
appearance_id=gothic-female-1 -> avatar_asset_id=system-gothic-female-1
appearance_id=gothic-female-2 -> avatar_asset_id=system-gothic-female-2
```

当前系统头像文件中有超过 2MB 的图片。系统 seed 流程允许导入这些已审核的内置资产；用户上传限制继续单独控制，默认仍保持当前 2MB 上限，避免意外扩大外部输入面。

### API 合约

新增读取接口：

```text
GET /api/v1/player-profiles/avatar-assets/{asset_id}
```

行为：

- 找不到资产返回 `404`。
- 找到资产时返回原始图片 bytes。
- `Content-Type` 使用资产的 `content_type`。
- 响应可设置长缓存头；系统头像和 UUID 上传头像都使用不可变 ID，适合 `Cache-Control: public, max-age=31536000, immutable`。

上传接口继续保留原路径：

```text
POST /api/v1/player-profiles/avatar
```

响应扩展为：

```json
{
  "avatar_asset_id": "uploaded-...",
  "avatar_image_url": "/api/v1/player-profiles/avatar-assets/uploaded-...",
  "avatar_image_mime": "image/png"
}
```

创建和更新玩家接口新增可选 `avatar_asset_id`。解析优先级：

1. 请求显式传入 `avatar_asset_id` 时，校验资产存在并绑定。
2. 请求没有 `avatar_asset_id`，但 `appearance_id` 是已知系统头像时，绑定对应系统头像。
3. 请求传入旧 `/player-avatars/gothic-*.png` 时，解析为对应系统头像资产。
4. 请求传入旧 `/api/v1/player-profiles/avatar/{filename}` 时，若旧文件仍存在于 `WEREWOLF_LOGS_DIR/player_profile_assets`，导入为 `migrated` 资产并绑定；若文件不存在，返回 `422`，防止继续写入不可访问的新数据。
5. 请求没有头像信息时，保持无头像。

玩家资料响应新增 `avatar_asset_id` 字段，并继续返回 `avatar_image_url` 和 `avatar_image_mime`，以兼容现有前端和对局日志适配器。

### 后端实现边界

新增集中式头像资产模块，负责：

- 系统头像元数据和旧 URL 映射。
- 资产 ID 到 API URL 的生成。
- 图片 bytes、MIME、hash 和大小的校验。
- 上传图片保存到数据库。
- 从旧文件系统资产导入到数据库。
- 玩家创建、更新、导入时的头像引用归一化。

玩家资料路由不直接拼旧静态路径；所有头像字段都通过该模块解析。

对局创建继续从 `VirtualPlayerProfile` 生成 `PlayerConfig`。当 profile 有 `avatar_asset_id` 时，`player_config_from_profile` 看到的 `avatar_image_url` 必须是后端生成的 API URL。这样直播事件、回放日志和移动端现场页都自然使用跨端可访问图片。

### 数据迁移

Alembic 新增迁移：

1. 创建 `player_avatar_assets`。
2. 给 `virtual_player_profiles` 添加 `avatar_asset_id`。
3. 导入四个系统头像资产，使用固定 ID，重复执行时按 ID 幂等。
4. 回填已有 profile：
   - `avatar_image_url` 是 `/player-avatars/gothic-*.png` 时，设置对应 `avatar_asset_id`。
   - `appearance_id` 是已知系统头像且没有头像资产时，也设置对应 `avatar_asset_id`。

旧上传文件迁移需要读取 `WEREWOLF_LOGS_DIR`，不放在 Alembic 中做。新增 CLI：

```text
python -m app.cli migrate-player-avatar-assets
```

该命令：

- 扫描数据库中没有 `avatar_asset_id` 的玩家资料。
- 识别 `/api/v1/player-profiles/avatar/{filename}`。
- 从 `WEREWOLF_LOGS_DIR/player_profile_assets/{filename}` 读取文件。
- 写入 `player_avatar_assets`，按 sha256 复用已有 migrated 资产。
- 回填 profile 的 `avatar_asset_id`。
- 输出扫描数、导入数、复用数、缺失文件数和回填数。
- 单事务提交；数据库错误时回滚并返回非零退出码。

旧 `import-player-profiles --source logs/player_profiles.json` 同步升级：导入 JSON 档案时先解析头像字段，能映射系统头像或旧上传文件的，直接写入 `avatar_asset_id`。

### 前端适配

`packages/game-client` 类型新增：

- `VirtualPlayerProfile.avatar_asset_id`
- `PlayerProfileRequest.avatar_asset_id`
- `PlayerAvatarUploadResponse.avatar_asset_id`

新增共享 helper：

```ts
resolveAvatarImageUrl(value: {
  avatar_asset_id?: string | null;
  avatar_image_url?: string | null;
}): string
```

行为：

- 有 `avatar_asset_id` 时，返回 API asset URL，并使用 `VITE_API_BASE_URL` 拼成当前环境可访问地址。
- `avatar_image_url` 是 `/api/...` 时，同样拼 `VITE_API_BASE_URL`。
- `avatar_image_url` 是旧 `/player-avatars/gothic-*.png` 时，临时映射到对应系统 asset URL。
- 空值返回空字符串。

桌面端和移动端所有头像渲染点改用该 helper，不再直接把 `profile.avatar_image_url` 塞进 `<img src>`。

`SYSTEM_PLAYER_AVATARS` 改为暴露 `assetId`，例如：

```ts
{
  id: "gothic-male-1",
  assetId: "system-gothic-male-1",
  label: "夜甲行者",
  gender: "male",
  mime: "image/png"
}
```

桌面端选择系统头像时保存 `appearance_id` 和 `avatar_asset_id`，预览图片通过 helper 生成。移动端第一版仍只读浏览和开局选择，不新增编辑能力。

### 兼容与回滚

兼容策略：

- API 响应继续包含 `avatar_image_url`，现有消费者不会因为新增 `avatar_asset_id` 立刻失效。
- 旧 `/player-avatars/gothic-*.png` 在前端 helper 和后端写入解析中都有临时兼容。
- 已有对局日志中的旧 URL 不做批量改写；回放渲染时前端 helper 会把已知旧系统头像 URL 映射到 API asset URL。

回滚边界：

- 数据库迁移回滚会移除 `avatar_asset_id` 和 `player_avatar_assets`。
- 旧字段仍保留，所以回滚后玩家资料文字数据不丢。
- 回滚后新上传头像若只存在于 DB 资产表，会随表删除而失去图片。因此上线前需要数据库备份；这是把图片本体纳入数据库后的正常数据保护要求。

### 安全与性能

- 上传继续限制 MIME 类型和大小。
- 上传内容需要计算 sha256；相同内容可以复用已有 uploaded/migrated 资产，减少重复存储。
- 图片接口只按资产 ID 读取，不接受任意文件路径。
- 固定资产 ID 不包含用户输入路径，避免路径穿越。
- PostgreSQL 存储四张系统图和少量玩家头像可以接受；若未来头像量增长到需要对象存储，再把资产表作为元数据表迁移到对象存储，不在本次范围。

## 测试与验收

后端测试：

- 创建玩家只传 `appearance_id=gothic-female-2` 时，响应包含 `avatar_asset_id=system-gothic-female-2` 和 `/api/v1/player-profiles/avatar-assets/system-gothic-female-2`。
- 创建玩家传旧 `/player-avatars/gothic-female-2.png` 时，后端归一化为系统资产。
- `GET /api/v1/player-profiles/avatar-assets/system-gothic-female-2` 返回 `200`、`image/png` 和非空 bytes。
- 上传头像写入数据库资产表，响应包含 `avatar_asset_id`，读取接口返回原始 bytes。
- 旧文件不存在时，新写入旧 `/api/v1/player-profiles/avatar/{filename}` 返回 `422`。
- `migrate-player-avatar-assets` 能把旧文件系统头像导入 DB，重复运行幂等。
- `import-player-profiles` 导入旧 JSON 时能回填系统头像 asset id。
- 创建对局返回的 `player_configs[*].avatar_image_url` 是 API asset URL。

前端测试：

- `resolveAvatarImageUrl` 对 `avatar_asset_id`、`/api/...`、旧 `/player-avatars/...` 和空值分别返回正确结果。
- mobile-web 玩家图鉴使用 helper 渲染头像。
- mobile-web 玩家卡牌库和座位头像使用 helper 渲染头像。
- desktop web 系统头像选择保存 `avatar_asset_id`，预览使用 API asset URL。
- 现有 live/replay 组件遇到旧系统头像 URL 时仍能显示。

验收命令：

```bash
cd apps/api && uv run pytest
pnpm --dir packages/game-client test -- --run
pnpm --dir apps/mobile-web test -- --run
pnpm --dir apps/web test -- --run
pnpm --dir apps/mobile-web build
pnpm --dir apps/web build
```

## 非目标

- 不为移动端新增玩家编辑、删除或头像上传 UI。
- 不把所有历史对局日志批量重写。
- 不引入对象存储、CDN 或图片转码服务。
- 不改变实时 run registry、游戏检查点或完成对局日志的存储方式。
- 不删除旧 `avatar_image_url` 字段；本次先兼容保留，未来可以单独做契约清理。
