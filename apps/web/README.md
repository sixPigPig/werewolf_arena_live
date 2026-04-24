# Web 应用

这个包包含单仓库中的 Vite React 前端。

- 将 `.env.example` 复制为 `.env`，本地开发时保持 `VITE_API_BASE_URL=http://localhost:8000`。
- 可以在仓库根目录使用 `make web` 启动应用，或者在当前目录使用 `pnpm dev`。
- 这个 SPA 默认后端 API 在本地运行，并通过 `/api/v1/health` 提供健康检查。
