# Python + React Web 单仓库

## 仓库结构

- `apps/api`：FastAPI 后端
- `apps/web`：React SPA 前端
- `docs`：架构与规划文档

## 快速开始

1. 复制环境变量文件：
   - `cp apps/api/.env.example apps/api/.env`
   - `cp apps/web/.env.example apps/web/.env`
2. 启动 PostgreSQL：
   - `docker compose up -d db`
3. 安装依赖：
   - `cd apps/api && uv sync`
   - `pnpm install`
4. 执行数据库迁移：
   - `cd apps/api && uv run alembic upgrade head`
5. 启动后端：
   - `make api`
6. 启动前端：
   - `make web`

## 质量检查

- `make lint`
- `make test`
- `cd apps/api && uv run alembic upgrade head`
- `cd apps/web && pnpm build`
