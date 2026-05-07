# 狼人杀实时观战工作台

## 仓库结构

- `apps/api`：FastAPI 后端
- `apps/web`：React SPA 前端
- `docs`：架构与规划文档

## 快速开始

复制环境变量文件：

```bash
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env
```

安装依赖：

```bash
cd apps/api && uv sync
pnpm install
```

`uv` 只用于首次同步 Python 依赖。如果本机没有 `uv`，请先安装 `uv`，或者使用已经存在的 `apps/api/.venv` 运行后端；`make api` 会直接调用项目内的 `.venv/bin/python`。

如需数据库，启动 PostgreSQL 并执行迁移：

```bash
docker compose up -d db
cd apps/api && uv run alembic upgrade head
```

## 本地运行

后端和前端需要在两个终端分别运行。

终端 1，启动 FastAPI：

```bash
make api
```

等价直接命令：

```bash
cd apps/api
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

后端地址：

```text
http://127.0.0.1:8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

终端 2，启动 Vite 前端：

```bash
make web
```

等价直接命令：

```bash
cd apps/web
pnpm dev --host 127.0.0.1 --port 5173
```

前端地址：

```text
http://127.0.0.1:5173
```

开发服务器会把 `/api` 代理到 `http://localhost:8000`，因此前端页面中的 `/api/v1/...` 请求会自动转发到 FastAPI。

## 实时观战流程

1. 打开 `http://127.0.0.1:5173/games`。
2. 点击“发起对局”。
3. 页面会进入 `/games/live/<run_id>`。
4. 实时观战页会展示玩家列表、当前聚焦玩家、原始事件侧栏。
5. 对局结束后点击“查看完整复盘”进入 `/games/<session_id>`。

运行真实模型对局前，请确认 `apps/api/.env` 中模型服务相关配置已经填写。当前内置
DeepSeek 和 MiniMax；如果 `WEREWOLF_DEFAULT_MODEL` 为空，后端会从已配置 API key 的
provider 中选择默认模型。只配置 MiniMax key 时，默认对局模型会自动使用
`MINIMAX_MODEL`，也可以在 CLI 或 API 请求中显式传入 `MiniMax-M2.7` 这类模型名。
DeepSeek 默认模型为 `deepseek-v4-flash`。
MiniMax key 需要和 host 区域匹配：大陆 key 使用 `https://api.minimaxi.com/v1`，Global
key 使用 `https://api.minimax.io/v1`。Qwen 使用阿里云百炼 DashScope OpenAI 兼容接口，
默认模型为 `qwen3.6-plus`，也支持在对局参数中传入 `Qwen3.6-Plus`；北京地域默认
base URL 为 `https://dashscope.aliyuncs.com/compatible-mode/v1`。新增 OpenAI-compatible
厂商时，优先在 `apps/api/app/werewolf/providers.py` 增加 provider config。

## 质量检查

- `make lint`
- `make test`
- `cd apps/web && pnpm build`

常用单独命令：

```bash
cd apps/api && .venv/bin/python -m pytest
cd apps/web && pnpm test -- --run
cd apps/web && pnpm build
```
