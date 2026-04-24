# Web 应用

这个包包含单仓库中的 Vite React 前端。

## 本地运行

推荐从仓库根目录启动：

```bash
make web
```

也可以在当前目录直接启动：

```bash
pnpm dev --host 127.0.0.1 --port 5173
```

前端地址：

```text
http://127.0.0.1:5173
```

## 后端 API

本地开发时，Vite 会把 `/api` 代理到 `http://localhost:8000`。因此前端默认可以直接请求 `/api/v1/...`。

如果需要绕过 Vite 代理，可以将 `.env.example` 复制为 `.env`，并设置：

```bash
VITE_API_BASE_URL=http://localhost:8000
```

后端健康检查：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

## 页面入口

- `/games`：对局列表与发起新对局
- `/games/live/:runId`：实时观战
- `/games/:sessionId`：完整复盘
