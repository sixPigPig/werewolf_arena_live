# CI、恢复并发与玩家档案存储加固设计

## 目标

完成三项可靠性修复：恢复后端 CI 绿灯；保证同一未完成对局只能有一个恢复任务；将 PostgreSQL 明确为虚拟玩家档案的唯一运行时数据源，并为旧 `player_profiles.json` 提供一次性迁移入口。

## 方案

### CI 修复

`test_werewolf_runner.py` 中若干测试 provider 在方法开头删除 `model` 和 `temperature`，随后 fallback 分支又把这两个参数传给父类。保留参数直到分支判断完成，只在实际不使用参数的分支消除未使用告警。修复仅影响测试夹具，不改变游戏运行逻辑。

### 防止重复恢复

`LiveRunRegistry` 增加按 `session_id` 查询活动 run 的能力，活动状态定义为 `queued` 或 `running`。恢复接口在同一把 registry 锁内完成“检查活动恢复 + 创建 run”，避免两个并发请求都通过检查。

恢复接口行为：

- 首次请求创建恢复 run，返回 `201`。
- 同一进程内再次恢复同一 `session_id` 时，不启动新线程，返回现有 run 摘要和 `200`。
- run 进入 `completed` 或 `failed` 后，不再占用该 `session_id`；如果检查点仍存在，可以再次恢复。
- 新对局创建使用新的 `session_id`，不受该约束影响。

该约束解决当前单进程部署中的重复点击和并发请求。跨进程排他需要共享任务存储或数据库锁，不在本次范围；README 会明确实时 run registry 当前仍是单进程内存组件。

### PostgreSQL 单一数据源

虚拟玩家档案 CRUD 和创建对局时的档案解析只访问 SQLAlchemy `VirtualPlayerProfile`。数据库不可用时统一返回 `503`，不再读取或写入 JSON fallback。这样运行时只有一份权威数据，数据库恢复后不会出现档案切换或消失。

保留 `PlayerProfileFileStore` 作为旧文件解析器，仅供迁移命令使用，不再由 API 依赖注入。

新增 CLI：

```text
werewolf-api import-player-profiles --source <player_profiles.json>
```

迁移规则：

- 读取旧版和 v3 JSON，复用现有兼容解析逻辑。
- 按档案 `id` 幂等导入；已存在 ID 默认跳过，不覆盖数据库内容。
- 单事务提交；数据库错误时回滚并返回非零退出码。
- 输出读取数、导入数、跳过数，便于确认迁移结果。
- 源文件不存在、格式损坏或没有合法档案时返回非零退出码，不修改数据库。

头像文件仍保存在 `WEREWOLF_LOGS_DIR/player_profile_assets`；数据库中的 `avatar_image_url` 和 MIME 元数据保持不变。

## 错误与 API 行为

- 玩家档案列表、读取、创建、更新、删除遇到数据库连接或表结构错误时返回 `503`，detail 使用稳定公开文案，不泄露连接字符串。
- 创建对局需要读取档案库时，数据库不可用同样返回 `503`。
- 未知 `profile_id` 继续返回 `422`；正常 CRUD 的 `404`、`204` 契约保持不变。
- 重复恢复返回同一个 `run_id`，前端现有导航逻辑无需修改。

## 测试与验收

- `ruff check .` 通过，后端现有 286 个测试保持通过。
- 新增 registry 与 API 测试，证明并发/重复恢复只创建一个 run、只启动一个后台任务。
- 将原 JSON fallback API 测试替换为数据库不可用返回 `503` 的测试。
- 新增 CLI 测试覆盖成功导入、重复导入跳过、损坏文件、数据库失败回滚。
- 完整运行后端测试、前端测试、前后端 lint 和前端 production build。

## 非目标

- 不把实时 run registry 迁移到 Redis 或 PostgreSQL。
- 不改变对局日志、检查点和头像文件的文件系统存储方式。
- 不自动删除旧 `player_profiles.json`，迁移成功后由运维人员自行归档。
