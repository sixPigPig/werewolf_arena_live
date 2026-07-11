# Admin Web

独立的狼人杀竞技场运营与诊断后台。

## 当前状态

当前开放后台 Shell、真实服务端认证，以及第一条玩家管理业务闭环：服务端分页筛选、草稿创建与编辑、发布、归档、恢复、权限控制、CSRF、乐观锁冲突和结构化字段错误。未接入 API 的规划模块不进入导航和路由。

生产构建只有显式设置 `VITE_ADMIN_AUTH_ENABLED=true` 才会连接认证链，否则 fail closed。固定角色、服务端权限依赖以及玩家创建、更新、发布、归档、恢复的成功/失败审计已经落地；正式身份源和部署安全验收完成前，不提供生产登录入口。

正式容器由仓库根目录执行 `docker build -f apps/admin-web/Dockerfile --target runtime .` 构建。镜像内 Nginx 提供 SPA fallback、静态资源缓存和同源 `/api` 代理；运行时通过 `API_UPSTREAM` 指向 API Service，不把 API 地址或任何密钥烘焙进前端产物。

## 本地运行

```bash
cp .env.example .env
pnpm dev
```

访问 `http://127.0.0.1:5175`。

默认连接真实 Admin API。打开页面后使用服务端开发身份登录，随后玩家列表和所有编辑操作均访问 `/api/v1/admin/*`。前端配置为：

```dotenv
VITE_ADMIN_AUTH_ENABLED=true
VITE_ADMIN_DEV_LOGIN_ENABLED=true
VITE_ADMIN_PREVIEW_MODE=false
```

API 侧需要完成数据库迁移，并配置：

```dotenv
APP_ENVIRONMENT=development
ADMIN_DEV_AUTH_ENABLED=true
ADMIN_SESSION_COOKIE_SECURE=false
ADMIN_DEV_AUTH_EMAIL=admin@example.test
ADMIN_DEV_AUTH_DISPLAY_NAME=Development Admin
ADMIN_DEV_AUTH_ROLE=super_admin
```

开发登录不接收浏览器传入的账号或角色，身份完全由 API 服务端配置；前端不会持久化 access token。`ADMIN_SESSION_COOKIE_SECURE=false` 只用于本地 HTTP，production 配置会强制要求 Secure Cookie 并拒绝开发登录。

Fixture 预览仅用于显式 UI 开发，设置 `VITE_ADMIN_AUTH_ENABLED=false`、`VITE_ADMIN_DEV_LOGIN_ENABLED=false` 和 `VITE_ADMIN_PREVIEW_MODE=true` 才会启用；它不能作为联调或验收结果。

也可以从仓库根目录执行：

```bash
make admin-web
```

## 检查

```bash
pnpm lint
pnpm test -- --run
pnpm build
```

## 设计原则

- 不调用当前匿名 `/api/v1/*` 管理写接口；
- 不从 `apps/web/src` 跨应用导入；
- 不复制旧 Web 的哥特全局样式和 C 端页面；
- Admin/Public DTO、权限和 OpenAPI client 相互独立；
- 前端权限隐藏只改善体验，服务端必须强制鉴权；
- 业务接入只使用 `/api/v1/admin/*`，并复用现有 session、权限依赖和审计入口；
- 玩家状态使用 `draft -> published -> archived`，更新携带 `expected_version`，过期编辑返回 `409`；
- 预览模式使用本地 fixture，不能访问 API 或 API 图片资源。

完整方案见 [`docs/admin-web-development-plan.md`](../../docs/admin-web-development-plan.md)。
