# Admin Web 浏览器级质量基线

`apps/admin-web` 的单元测试覆盖数据契约和业务分支；浏览器级测试补足真实构建、路由、焦点、响应式侧栏和可访问性扫描。

## 本地执行

```bash
pnpm --dir apps/admin-web exec playwright install chromium
pnpm --dir apps/admin-web test:e2e
```

测试会以 Vite `test` 模式构建 Admin，并在 `127.0.0.1:4175` 启动隔离的生产预览服务器；不会连接 API、写入真实数据或复用浏览器会话。正式 production 构建仍保持 fail closed。

## 当前门槛

- 桌面总览应在 5 秒内显示；实际时间会以 `overview-performance.json` 写入 Playwright 报告，CI 保留浏览器报告工件；
- 跳过链接必须把键盘焦点移动到 `main`；
- 默认 axe 规则在 `.admin-app-shell` 中不得产生违规；
- 移动端必须可打开侧栏、导航到页面，并在导航后收起；
- AI 草稿只能填入新建表单，测试不点击保存，持续验证人工审核/保存边界。

该基线不是端到端生产环境的 SLO。真实 OIDC、数据库、Worker 与部署探针仍在目标环境的发布烟测中验收。
