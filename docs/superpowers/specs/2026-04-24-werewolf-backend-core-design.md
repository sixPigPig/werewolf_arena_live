# Werewolf 后端核心与 CLI 设计方案

**日期**: 2026-04-24
**范围**: 只开发后端，不修改前端。

## 1. 目标

本阶段参考 `reference/werewolf_arena`，在 `apps/api` 内建立 Werewolf 游戏后端核心，并增加一个 CLI，让后端可以脱离前端独立运行一局游戏。

第一版不追求完整复制参考项目的所有评测能力，也不接入真实前端页面。它要先做到：

- 后端有清晰的 Werewolf 领域模块。
- CLI 可以启动一局游戏。
- 游戏运行后生成 session 日志文件。
- 代码可以在没有真实 OpenAI、Gemini 或 Vertex 凭据时稳定测试。
- 现有 FastAPI health、数据库骨架和前端代码保持不变。

## 2. 非目标

本阶段不做以下内容：

- 不修改 `apps/web`。
- 不新增前端页面或前端 API client。
- 不实现多人实时房间、WebSocket 或浏览器观战。
- 不引入 Celery、Redis 或异步任务队列。
- 不把参考项目作为运行时依赖直接 import。
- 不要求真实 LLM API key 才能跑通测试。

## 3. 推荐方案

采用“后端内生领域模块 + 可替换模型客户端”的方案。

目录建议：

```text
apps/api/app
  /werewolf
    __init__.py
    config.py
    engine.py
    logging.py
    models.py
    runner.py
    local_ai.py
  cli.py
```

职责：

- `models.py`: 定义玩家、角色、回合、游戏状态、日志等领域对象。
- `engine.py`: 执行 Werewolf 游戏流程，包括夜晚行动、白天讨论、投票、胜负判断。
- `runner.py`: 提供面向 CLI 和未来 API 的运行入口，例如 `run_game(...)`。
- `logging.py`: 负责 session 目录和 JSON 日志读写。
- `local_ai.py`: 提供本地确定性模型，用于测试和无密钥开发。
- `config.py`: 管理玩家名、默认玩家数量、默认回合限制等后端配置。
- `cli.py`: 暴露命令行入口。

这样做的好处是：核心游戏逻辑属于当前后端项目，不依赖参考仓库路径；同时保留模型调用接口，后续可以接入 OpenAI、Gemini 或其他模型。

## 4. CLI 设计

第一版 CLI 支持单局游戏：

```bash
cd apps/api
uv run python -m app.cli run-game --villager-model local --werewolf-model local
```

可选参数：

- `--villager-model`: 村民阵营模型名，默认 `local`。
- `--werewolf-model`: 狼人阵营模型名，默认 `local`。
- `--seed`: 随机种子，便于复现测试。
- `--logs-dir`: 日志根目录，默认 `logs`。
- `--max-rounds`: 最大回合数，避免本地模型或未来模型异常导致无限循环。

CLI 成功时输出：

- winner
- session id
- log directory

CLI 失败时返回非零退出码，并在日志中写入错误信息。

## 5. 游戏流程

参考项目的核心流程会被保留，但第一版实现会更适合后端内测：

1. 初始化 8 名玩家。
2. 分配角色：2 Werewolf、1 Seer、1 Doctor、其余 Villager。
3. 每回合执行夜晚阶段：狼人袭击、医生保护、预言家查验。
4. 结算夜晚淘汰。
5. 执行白天阶段：有限轮讨论和投票。
6. 结算放逐。
7. 判断胜负。
8. 保存完整状态与日志。

本地模型会用确定性策略产生行动，例如从合法选项中选择固定位置或按 seed 派生选择。它不是高质量游戏 AI，只用于让后端核心可运行、可测试。

## 6. 日志与数据

每局游戏写入一个 session 目录：

```text
apps/api/logs/session_YYYYMMDD_HHMMSS_<suffix>
  game_complete.json
  game_logs.json
```

如果运行失败：

```text
apps/api/logs/session_YYYYMMDD_HHMMSS_<suffix>
  game_partial.json
  game_logs.json
```

JSON 结构应包含：

- session id
- winner
- players and roles
- rounds
- eliminated/protected/investigated/exiled player
- debate and votes
- error message when present

日志格式参考原项目，但使用当前后端自己的数据对象，避免直接依赖参考项目实现细节。

## 7. 错误处理

- CLI 参数错误由 `argparse` 返回标准错误。
- 游戏运行错误会被 `runner.py` 捕获，写入 `state.error_message`。
- `max_rounds` 达到上限但没有胜者时，记录错误并退出失败。
- 日志写入失败时让异常向 CLI 冒泡，CLI 返回非零退出码。

## 8. 测试策略

采用测试先行。

优先覆盖：

- CLI help 和参数解析。
- `run_game(...)` 使用 local 模型能返回 winner 和 log directory。
- 日志目录中生成 `game_complete.json` 与 `game_logs.json`。
- 相同 seed 下玩家角色与胜者结果可复现。
- `max_rounds` 能阻止无限循环。

验证命令：

```bash
cd apps/api && uv run pytest
cd apps/api && uv run ruff check .
```

本轮不运行前端测试，因为要求前端无改动。

## 9. 后续扩展

完成本阶段后，下一阶段可以在不推翻结构的前提下继续扩展：

- 接入真实 LLM provider。
- 增加 FastAPI 路由来创建游戏和读取日志。
- 把日志目录暴露给前端观战页面。
- 支持恢复失败游戏。
- 支持批量模型评测。
