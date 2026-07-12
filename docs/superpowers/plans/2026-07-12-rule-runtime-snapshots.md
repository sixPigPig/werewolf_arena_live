# 可配置规则集运行快照与恢复链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 将已发布规则修订原子绑定到新对局，并保证创建、后台执行、Live、checkpoint、恢复、orphan recovery、历史回放和提示词始终使用同一份不可漂移快照。

**Architecture:** 开局服务锁定 rule_sets 稳定实体、解析当前 published revision、准备 Live run 和 run_created 事件，并在同一数据库事务提交 revision 引用与完整 snapshot；提交后才注册内存 run 和启动线程。runner 与 resume 不访问规则目录，只通过 CompiledRuleSet 或 checkpoint snapshot 构造 GameEngine。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、threading、JSON checkpoint、Prometheus text exposition、pytest、Ruff。

## Global Constraints

- Requires completed plan: docs/superpowers/plans/2026-07-12-rule-catalog-admin-api.md。
- 新对局必须绑定 published revision；archived、draft 或 revision 前置条件不匹配都不能开局。
- POST /api/v1/games/runs 的 expected_rule_revision_id 在兼容期可选；新客户端必须提交。
- Managed snapshot 的 version 是 revision_no 十进制字符串；legacy snapshot 的 version=2026.04 不重写。
- Live run、GameState、checkpoint、game session 和 replay 保存的 snapshot 是执行真源。
- runner、resume、orphan reaper、replay 不得查询当前 rule_sets 目录。
- checkpoint reader 永久支持 schema v1 和 v2；v1 snapshot 不完整时明确失败，不 fallback 到当前目录。
- archive 或发布下一 revision 不影响已启动对局。
- 数据库目录模式异常返回 503；不得静默回退到静态规则。
- 一期不新增 action、phase、SSE/WS 事件类型或 voice cue。
- 历史未知 snapshot 必须继续展示；无法严格匹配的 revision 外键保持 NULL。
- 只记录 stable ID、revision_no、schema_version 和 hash 前缀，不记录完整规则 JSON。

---

## File Structure

- Create apps/api/alembic/versions/20260712_16_add_rule_revision_references.py：Live/game nullable metadata、索引和保守回填。
- Modify apps/api/app/models/live.py、game_session.py：revision ID/no/hash 列。
- Modify apps/api/app/werewolf/live.py、live_store.py：LiveGameRun 元数据、原子 prepare/stage/attach。
- Modify apps/api/app/werewolf/replay.py：game session 标量元数据、v1/v2 checkpoint 验证。
- Modify apps/api/app/werewolf/runner.py：新局和恢复只消费 CompiledRuleSet。
- Modify apps/api/app/werewolf/checkpoint.py：schema v2 writer、v1/v2 reader 和统一 snapshot resolver。
- Modify apps/api/app/api/routes/games.py：数据库目录、revision precondition、原子开局和结构化错误。
- Create apps/api/app/api/schemas/public_rule_sets.py：严格 public catalog response DTO。
- Modify apps/api/app/werewolf/orphan_reaper.py：复用统一 checkpoint 验证，不增加目录读取。
- Modify apps/api/app/admin/games.py、live_runs.py 及对应 route/schema：稳定 ID/精确 revision 查询和历史名称。
- Modify apps/api/app/werewolf/rules.py、engine.py、prompts_zh.py：动态规则文本，不扩展 action。
- Create apps/api/app/rule_sets/telemetry.py：规则 counters 和 metrics renderer。
- Modify apps/api/app/api/routes/metrics.py、core/config.py：指标和显式目录 source。
- Create apps/api/tests/rule_set_fixtures.py：SQLite tests 的四套官方目录种子，不被生产代码导入。
- Modify README.md、docs/architecture.md、docs/admin-deployment-runbook.md：迁移、灰度、回滚边界。
- Create/modify对应 API、Live、runner、resume、orphan、admin、metrics tests。

## Interfaces Consumed from Plan 1

~~~python
compiled = resolve_published_rule_set(
    db,
    rule_set_id,
    expected_revision_id=request.expected_rule_revision_id,
    for_update=True,
)

restored = resolve_rule_set_snapshot(snapshot)
~~~

Runtime metadata names are fixed:

~~~python
rule_set_revision_id: str | None
rule_set_revision_no: int | None
rule_set_content_hash: str | None
~~~

---

### Task 1: Expand Run and Game Tables with Conservative Backfill

**Files:**
- Create: apps/api/alembic/versions/20260712_16_add_rule_revision_references.py
- Modify: apps/api/app/models/live.py:20-30
- Modify: apps/api/app/models/game_session.py:12-28
- Modify: apps/api/tests/test_models.py
- Create: apps/api/tests/test_rule_revision_backfill.py

**Interfaces:**
- Consumes: rule_set_revisions from plan 1.
- Produces: nullable scalar metadata and indexed historical filters.

- [ ] **Step 1: Write failing schema and backfill tests**

~~~python
def test_run_and_game_models_expose_rule_revision_metadata() -> None:
    for table in (LiveRunRecord.__table__, GameSessionRecord.__table__):
        assert "rule_set_revision_id" in table.c
        assert "rule_set_revision_no" in table.c
        assert "rule_set_content_hash" in table.c
    assert "rule_set_id" in GameSessionRecord.__table__.c


def test_backfill_links_only_exact_official_legacy_snapshots(
    migrated_database: Engine,
) -> None:
    with Session(migrated_database) as db:
        exact = db.get(GameSessionRecord, "game_exact001")
        changed = db.get(GameSessionRecord, "game_changed1")
        unknown = db.get(GameSessionRecord, "game_unknown1")
        assert exact.rule_set_revision_id == (
            "e9fa678e-9b18-5079-91d2-f74835364fb6"
        )
        assert exact.rule_set_content_hash == (
            "00095728147a022c48eab88faf21a14567ad0afa13ab9418306e84ff85b10131"
        )
        assert changed.rule_set_id == "classic_8"
        assert changed.rule_set_revision_id is None
        assert unknown.rule_set_id == "unknown_8"
        assert unknown.rule_set_revision_id is None
~~~

Insert one exact snapshot, one same-ID modified snapshot, one unknown ID and one incomplete snapshot before upgrading revision 16. Assert JSON columns are byte-for-byte unchanged after upgrade and downgrade.

- [ ] **Step 2: Run and verify missing columns/revision**

~~~bash
cd apps/api
.venv/bin/python -m pytest \
  tests/test_models.py::test_run_and_game_models_expose_rule_revision_metadata \
  tests/test_rule_revision_backfill.py -q
~~~

Expected: missing-column or migration-file failures.

- [ ] **Step 3: Add nullable ORM columns and indexes**

LiveRunRecord retains non-null rule_set_id and JSON rule_set. GameSessionRecord adds nullable rule_set_id because legacy snapshots may be unknown. Both add nullable revision ID/no/hash. Revision IDs are ON DELETE RESTRICT FKs.

Required indexes:

~~~text
ix_live_runs_rule_set_revision_id
ix_live_runs_rule_set_id_updated_at_run_id_desc
ix_game_sessions_rule_set_revision_id
ix_game_sessions_rule_set_id_created_at_session_id_desc
~~~

- [ ] **Step 4: Implement frozen best-effort backfill**

The migration has revision=20260712_16 and down_revision=20260712_15. It imports only stdlib、Alembic、SQLAlchemy. Canonical legacy snapshot hash is JSON sort_keys、ensure_ascii=False、separators comma/colon、allow_nan=False.

Embed this exact mapping:

| Legacy full-snapshot hash | Stable ID | Revision ID | New config hash |
|---|---|---|---|
| e63a962b73bb85d4d75f35c3c9fc7834b991ce39d41e4f892f66c3b68e4c4804 | classic_8 | e9fa678e-9b18-5079-91d2-f74835364fb6 | 00095728147a022c48eab88faf21a14567ad0afa13ab9418306e84ff85b10131 |
| ace7fb0d1e33de641fa5394d2253b2de6cf2489e38394ad36047a47bb590ca73 | starter_6 | b607e17e-b86f-5eb0-9dc2-b8df09aa71ab | ecf10b12dfd87fe3b41d5db61e67b0897acf78a97510c23377272bfd7719df02 |
| 17ceee957477643a7d97fd31dd181c6ad126676ba1af0bc1fc144d4b4a411e6d | social_8 | 2b4a993f-e4e6-5312-b11d-92874851a70a | 21e1bd2bb495e4479a346724c85a9722477f840afc2c99c389558a52427a0fbc |
| 688244c09a67521c10610875af305bafcadbcf16e164e5203cf7add4bd48aa00 | classic_12_seer_witch_hunter_idiot | 0489f6ac-16fd-5323-96ce-ee256c98cf32 | bcae38e48a7791fa0f7ae236c90f1852056938ea60f5447532e5d879260d6da2 |

For game_sessions, set rule_set_id from a non-empty snapshot ID even when unmatched. Set revision fields only on full hash match. For live_runs, preserve current rule_set_id and use the same match rule. Never update rule_set JSON.

- [ ] **Step 5: Verify upgrade/downgrade and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_models.py \
  tests/test_rule_revision_backfill.py -q
.venv/bin/alembic check
.venv/bin/ruff check app/models/live.py app/models/game_session.py \
  alembic/versions/20260712_16_add_rule_revision_references.py
git add app/models/live.py app/models/game_session.py \
  alembic/versions/20260712_16_add_rule_revision_references.py \
  tests/test_models.py tests/test_rule_revision_backfill.py
git commit -m "feat(api): add pinned rule metadata to game records"
~~~

---

### Task 2: Persist Pinned Metadata through Live and Replay Stores

**Files:**
- Modify: apps/api/app/werewolf/live.py:115-175,265-320
- Modify: apps/api/app/werewolf/live_store.py:36-130,310-335
- Modify: apps/api/app/werewolf/replay.py:122-176
- Modify: apps/api/tests/test_live.py
- Modify: apps/api/tests/test_live_store.py
- Modify: apps/api/tests/test_game_record_store.py

**Interfaces:**
- Consumes: Task 1 columns and managed snapshots.
- Produces: Live summaries/events and game records with matching revision/hash.

- [ ] **Step 1: Write failing store round-trip tests**

~~~python
def test_live_store_round_trips_pinned_rule_metadata(db: Session) -> None:
    run = build_live_run(
        rule_set_revision_id="revision-2",
        rule_set_revision_no=2,
        rule_set_content_hash="a" * 64,
        rule_set=managed_snapshot(revision_id="revision-2", revision_no=2),
    )
    DatabaseLiveStore(db).save_run(run)
    loaded = DatabaseLiveStore(db).load_run(run.run_id)
    assert loaded.rule_set_revision_id == "revision-2"
    assert loaded.rule_set_revision_no == 2
    assert loaded.rule_set_content_hash == "a" * 64
    assert loaded.rule_set == run.rule_set


def test_replay_store_projects_metadata_from_saved_snapshot(db: Session) -> None:
    state = complete_state_with_managed_rule()
    DatabaseReplayStore(db).save_game_payload(state=state, logs=[])
    record = db.get(GameSessionRecord, state["session_id"])
    assert record.rule_set_id == state["rule_set"]["id"]
    assert record.rule_set_revision_id == state["rule_set"]["revision_id"]
    assert record.rule_set_revision_no == state["rule_set"]["revision_no"]
    assert record.rule_set_content_hash == state["rule_set"]["content_hash"]
~~~

- [ ] **Step 2: Run and verify constructor/round-trip failures**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_live.py tests/test_live_store.py \
  tests/test_game_record_store.py -k "rule_revision or pinned_rule_metadata" -q
~~~

- [ ] **Step 3: Extend LiveGameRun and event summaries**

Add the three nullable fields to LiveGameRun、LiveRunRegistry create/get-or-create signatures、to_summary and run_created payload. A managed run requires all three values; legacy rows may have all three NULL. Reject partial metadata combinations in a shared validator.

- [ ] **Step 4: Persist and load exact fields**

DatabaseLiveStore save/load copies all three scalar fields and the JSON snapshot. DatabaseReplayStore extracts optional managed metadata from state.rule_set; malformed partial metadata causes ReplayNotFoundError for new writes, while legacy snapshots with no managed fields remain saveable.

- [ ] **Step 5: Verify and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_live.py tests/test_live_store.py \
  tests/test_game_record_store.py -q
.venv/bin/ruff check app/werewolf/live.py app/werewolf/live_store.py \
  app/werewolf/replay.py
git add app/werewolf/live.py app/werewolf/live_store.py app/werewolf/replay.py \
  tests/test_live.py tests/test_live_store.py tests/test_game_record_store.py
git commit -m "feat(api): persist pinned rule snapshots"
~~~

---

### Task 3: Switch Public Catalog and Atomically Create Runs

**Files:**
- Modify: apps/api/app/api/routes/games.py:90-96,339-348,543-609,832-870
- Modify: apps/api/app/api/public/dependencies.py:95-111
- Create: apps/api/app/api/schemas/public_rule_sets.py
- Modify: apps/api/app/core/config.py
- Modify: apps/api/tests/test_games_api.py
- Modify: apps/api/tests/test_config.py

**Interfaces:**
- Consumes: resolve_published_rule_set() and public_rule_set_catalog_snapshot().
- Produces: revisioned GET /games/rule-sets and POST /games/runs preconditions.

- [ ] **Step 1: Write failing catalog/create consistency tests**

Add these tests:

~~~text
test_list_rule_sets_returns_published_database_revisions_default_first
test_list_rule_sets_returns_503_without_static_fallback
test_create_game_run_pins_expected_revision_and_snapshot
test_create_game_run_rejects_revision_changed_with_current_catalog_item
test_create_game_run_rejects_archived_rule
test_create_game_run_without_expected_revision_records_compatibility
test_background_thread_starts_only_after_run_transaction_commits
test_publish_waits_while_run_selection_holds_parent_lock
~~~

The create test captures the CompiledRuleSet passed to the background target and asserts it equals the persisted Live snapshot/hash.

Because Base.metadata.create_all() does not run Alembic seed data, add a tests/rule_set_fixtures.py helper that inserts the same four parent/revision rows from migration 15. Call it from the existing test_games_api isolated_db fixture before every database-catalog test; production code must never auto-seed at request time.

- [ ] **Step 2: Run and verify old static behavior**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_games_api.py \
  -k "published_database_revisions or expected_revision or archived_rule or transaction_commits" -q
~~~

Expected: list lacks revision metadata; create ignores expected_rule_revision_id.

- [ ] **Step 3: Add the request and problem contract**

~~~python
class CreateGameRunRequest(BaseModel):
    villager_model: str = Field(default_factory=default_model_name)
    werewolf_model: str = Field(default_factory=default_model_name)
    seed: int | None = None
    max_rounds: int = Field(default=8, ge=1, le=20)
    rule_set_id: str = DEFAULT_RULE_SET_ID
    expected_rule_revision_id: str | None = Field(default=None, max_length=36)
    player_configs: list[CreatePlayerConfigRequest] = Field(default_factory=list)
~~~

Extend public_problem() with an extensions mapping merged inside detail. rule_revision_changed returns current_rule_set; rule_set_unavailable returns no stale snapshot; store failures return 503 rule_set_store_unavailable.

Define PublicRuleRole、PublicRuleSetCatalogItem and PublicRuleSetCatalogResponse Pydantic response models. Catalog fields are required, roles are included, and GET /games/rule-sets declares response_model=PublicRuleSetCatalogResponse so the OpenAPI contract matches packages/game-client.

- [ ] **Step 4: Refactor registry creation into prepare, stage and attach**

~~~python
def prepare_run(self, **values: object) -> LiveGameRun:
    # Builds run plus run_created event in memory; no store write and no registry attach.

def attach_prepared_run(self, run: LiveGameRun) -> None:
    # Adds an already-committed run to the local registry; no database write.

def stage_new_run(self, run: LiveGameRun) -> None:
    # DatabaseLiveStore inserts LiveRunRecord and run_created LiveEventRecord,
    # calls flush, and never commits.
~~~

Move existing run construction/payload code into prepare_run. Existing create_run remains a compatibility wrapper for tests/CLI and calls prepare → save → attach; the HTTP route must use explicit prepare/stage/commit/attach.

- [ ] **Step 5: Implement the atomic HTTP sequence**

~~~python
compiled = resolve_published_rule_set(
    db,
    request.rule_set_id,
    expected_revision_id=request.expected_rule_revision_id,
    for_update=True,
)
player_configs = complete_player_configs_from_library(
    requests=request.player_configs,
    player_count=compiled.rule_set.player_count,
    seed=request.seed,
    db=db,
)
run = registry.prepare_run(
    session_id=new_session_id(),
    villager_model=request.villager_model,
    werewolf_model=request.werewolf_model,
    seed=request.seed,
    max_rounds=request.max_rounds,
    rule_set_id=compiled.rule_set.id,
    rule_set_revision_id=compiled.revision_id,
    rule_set_revision_no=compiled.revision_no,
    rule_set_content_hash=compiled.content_hash,
    rule_set=compiled.snapshot,
    player_configs=player_configs,
    lineup_quality_warnings=lineup_quality_warnings(player_configs),
)
DatabaseLiveStore(db).stage_new_run(run)
db.commit()
registry.attach_prepared_run(run)
_start_game_thread(run=run, compiled=compiled, registry=registry)
~~~

No thread is created before commit. Any failure rolls back and leaves neither a local run nor a background worker.

- [ ] **Step 6: Add explicit catalog source and production safety**

Add rule_set_catalog_source: Literal["static", "database"] = "database". Static mode is an explicit staging-only compatibility mode that synthesizes the same official revision IDs/hashes; database mode never falls back. Production validation rejects source=static.

- [ ] **Step 7: Verify and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_games_api.py tests/test_config.py -q
.venv/bin/ruff check app/api/routes/games.py app/api/public/dependencies.py \
  app/api/schemas/public_rule_sets.py app/core/config.py
git add app/api/routes/games.py app/api/public/dependencies.py \
  app/api/schemas/public_rule_sets.py app/core/config.py \
  tests/test_games_api.py tests/test_config.py
git commit -m "feat(api): atomically pin rule revisions at game creation"
~~~

---

### Task 4: Make Runner Execute Only the Pinned Snapshot

**Files:**
- Modify: apps/api/app/werewolf/runner.py:37-111
- Modify: apps/api/app/api/routes/games.py:832-870
- Modify: apps/api/app/cli.py
- Modify: apps/api/tests/test_werewolf_runner.py
- Modify: apps/api/tests/test_games_api.py
- Modify: apps/api/tests/test_werewolf_cli.py

**Interfaces:**
- Consumes: CompiledRuleSet from create or resolve_rule_set_snapshot().
- Produces: run_params and GameState containing the identical managed snapshot.

- [ ] **Step 1: Write failing runner identity tests**

~~~python
def test_run_game_never_resolves_a_rule_id_after_receiving_compiled_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled = managed_classic_rule()
    monkeypatch.setattr(
        "app.werewolf.rules.get_rule_set",
        lambda _rule_id: (_ for _ in ()).throw(AssertionError("catalog lookup")),
    )
    result = run_game(
        record_store=record_store(),
        compiled_rule_set=compiled,
        provider=deterministic_provider(),
        max_rounds=1,
    )
    saved = load_saved_state(result.session_id)
    assert saved["rule_set"] == compiled.snapshot
~~~

Also assert run_params stores rule_set_id、revision_id、revision_no、content_hash and full rule_set_snapshot.

- [ ] **Step 2: Run and verify signature/lookup failure**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py \
  tests/test_games_api.py -k "compiled_snapshot or background_passes" -q
~~~

- [ ] **Step 3: Require CompiledRuleSet in run_game**

~~~python
def run_game(
    *,
    record_store: GameRecordStore,
    compiled_rule_set: CompiledRuleSet,
    villager_model: str | None = None,
    werewolf_model: str | None = None,
    seed: int | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    provider: ModelProvider | None = None,
    session_id: str | None = None,
    event_sink: object | None = None,
    player_configs: list[PlayerConfig] | None = None,
) -> RunGameResult:
~~~

Use compiled_rule_set.rule_set for initialize_game_state and GameEngine; use compiled_rule_set.snapshot in run_params. Delete get_rule_set import from runner.

- [ ] **Step 4: Update all call sites explicitly**

HTTP background receives CompiledRuleSet from Task 3. CLI resolves an official compatibility snapshot before calling runner. Tests use a shared managed or legacy compiled fixture. No caller may pass only rule_set_id.

- [ ] **Step 5: Verify and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_runner.py \
  tests/test_games_api.py tests/test_werewolf_cli.py -q
.venv/bin/ruff check app/werewolf/runner.py app/api/routes/games.py app/cli.py
git add app/werewolf/runner.py app/api/routes/games.py app/cli.py \
  tests/test_werewolf_runner.py tests/test_games_api.py \
  tests/test_werewolf_cli.py
git commit -m "refactor(api): execute games from pinned rule snapshots"
~~~

---

### Task 5: Upgrade Checkpoints and Resume v1/v2 from Snapshots

**Files:**
- Modify: apps/api/app/werewolf/checkpoint.py:21-155
- Modify: apps/api/app/werewolf/replay.py:255-292
- Modify: apps/api/app/werewolf/runner.py:114-185
- Modify: apps/api/app/api/routes/games.py:697-750,888-929
- Modify: apps/api/app/werewolf/orphan_reaper.py:151-190
- Modify: apps/api/tests/test_werewolf_resume.py
- Modify: apps/api/tests/test_game_record_store.py
- Modify: apps/api/tests/test_orphan_reaper.py
- Modify: apps/api/tests/test_games_api.py

**Interfaces:**
- Consumes: resolve_rule_set_snapshot().
- Produces: resolved_rule_set_from_checkpoint() as the sole resume parser.

- [ ] **Step 1: Write failing v1/v2 and tamper tests**

Add exact tests:

~~~text
test_checkpoint_v2_writes_snapshot_revision_and_hash
test_checkpoint_reader_accepts_v1_full_snapshot
test_checkpoint_reader_accepts_v2_and_verifies_hash
test_checkpoint_reader_rejects_future_schema
test_checkpoint_reader_rejects_incomplete_v1_without_catalog_fallback
test_resume_uses_old_snapshot_after_new_revision_published
test_resume_uses_old_snapshot_after_rule_archived
test_orphan_recovery_uses_the_same_checkpoint_resolver
~~~

Monkeypatch get_rule_set and resolve_published_rule_set to raise AssertionError during resume; valid v1/v2 restores must still proceed.

- [ ] **Step 2: Run and verify current strict-v1/current-ID failures**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_resume.py \
  tests/test_game_record_store.py tests/test_orphan_reaper.py \
  -k "checkpoint or snapshot or archived" -q
~~~

- [ ] **Step 3: Add the sole checkpoint resolver**

~~~python
CHECKPOINT_SCHEMA_VERSION = 2
SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS = frozenset({1, 2})


def resolved_rule_set_from_checkpoint(
    checkpoint: Mapping[str, object],
) -> CompiledRuleSet:
    schema_version = checkpoint.get("schema_version")
    if schema_version not in SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS:
        raise ResumeCheckpointError("Unsupported checkpoint schema")
    state = require_mapping(checkpoint.get("state_at_round_start"))
    state_snapshot = require_mapping(state.get("rule_set"))
    run_params = require_mapping(checkpoint.get("run_params"))
    if schema_version == 1:
        authoritative_snapshot = state_snapshot
    else:
        authoritative_snapshot = require_mapping(
            run_params.get("rule_set_snapshot")
        )
    compiled = resolve_rule_set_snapshot(authoritative_snapshot)
    if compiled.snapshot != resolve_rule_set_snapshot(state_snapshot).snapshot:
        raise ResumeCheckpointError("Checkpoint rule snapshots disagree")
    if run_params.get("rule_set_id") != compiled.rule_set.id:
        raise ResumeCheckpointError("Checkpoint rule id mismatch")
    return compiled
~~~

For v2, additionally require revision_id、positive revision_no、64-character lowercase content_hash and exact hash match. For v1, revision remains NULL but complete old snapshot is mandatory.

- [ ] **Step 4: Normalize resumed writes to v2**

ResumeCheckpointManager always writes schema 2 and run_params from CompiledRuleSet. After a v1 checkpoint resumes and starts its next round, the persisted checkpoint becomes v2 without mutating the original at read time.

- [ ] **Step 5: Remove both current-ID resume lookups**

start_resume_game_run and runner.resume_game both call resolved_rule_set_from_checkpoint. start_resume uses it when preparing the resumed Live run; runner uses the same result for GameEngine. Orphan reaper only calls DatabaseReplayStore.load_resume_checkpoint, which now validates the rule snapshot through the same helper.

- [ ] **Step 6: Replace incomplete checkpoint fixtures**

Any test fixture representing a resumable production checkpoint must use rule_set_snapshot(get_rule_set("starter_6")) or a managed snapshot. Partial rule dictionaries remain valid only for non-resumable replay fixtures.

- [ ] **Step 7: Verify and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_werewolf_resume.py \
  tests/test_game_record_store.py tests/test_orphan_reaper.py \
  tests/test_games_api.py -q
.venv/bin/ruff check app/werewolf/checkpoint.py app/werewolf/replay.py \
  app/werewolf/runner.py app/api/routes/games.py \
  app/werewolf/orphan_reaper.py
git add app/werewolf/checkpoint.py app/werewolf/replay.py \
  app/werewolf/runner.py app/api/routes/games.py \
  app/werewolf/orphan_reaper.py tests/test_werewolf_resume.py \
  tests/test_game_record_store.py tests/test_orphan_reaper.py \
  tests/test_games_api.py
git commit -m "feat(api): resume games from versioned rule snapshots"
~~~

---

### Task 6: Preserve Historical Admin Semantics and Dynamic Prompts

**Files:**
- Modify: apps/api/app/admin/games.py
- Modify: apps/api/app/admin/live_runs.py
- Modify: apps/api/app/api/schemas/admin_games.py
- Modify: apps/api/app/api/schemas/admin_live_runs.py
- Modify: apps/api/app/api/routes/admin_games.py
- Modify: apps/api/app/api/routes/admin_live_runs.py
- Modify: apps/api/app/rule_sets/repository.py
- Modify: apps/api/app/api/routes/admin_rule_sets.py
- Modify: apps/api/app/api/schemas/admin_rule_sets.py
- Modify: apps/api/app/werewolf/rules.py:262-307
- Modify: apps/api/app/werewolf/engine.py:2173-2195
- Modify: apps/api/app/werewolf/prompts_zh.py
- Modify: apps/api/tests/test_admin_games.py
- Modify: apps/api/tests/test_admin_live_runs.py
- Modify: apps/api/tests/test_admin_rule_sets.py
- Modify: apps/api/tests/test_werewolf_rules.py
- Modify: apps/api/tests/test_werewolf_lm.py

**Interfaces:**
- Consumes: persisted scalar metadata/snapshot only.
- Produces: stable-ID and exact-revision filters plus prompt text matching pinned rules.

- [ ] **Step 1: Write failing history and prompt tests**

Cover rule_set_id cross-revision filter, rule_set_revision_id exact filter, legacy NULL revision, historical name unchanged after rename, Live list not calling static get_rule_set, no large JSON/payload projection, weight 1/1.5/2, self-explosion with none/double, sheriff disabled, and absent special roles.

- [ ] **Step 2: Run and verify current JSON/static/hardcoded behavior**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_admin_games.py \
  tests/test_admin_live_runs.py tests/test_werewolf_rules.py \
  tests/test_werewolf_lm.py -k "rule_revision or historical_rule or vote_weight or badge_policy" -q
~~~

- [ ] **Step 3: Use scalar filters and revision joins**

Game list filters GameSessionRecord.rule_set_id, not JSON path. Both Admin lists accept optional rule_set_revision_id. Live projection outer-joins RuleSetRevisionRecord only for name/player_count/revision metadata and does not select LiveRunRecord.rule_set. Legacy NULL revision displays stable ID; detail may read saved snapshot where already authorized.

Extend the rule-set repository/detail response to aggregate game_count and live_count by stable ID, plus per-revision counts for the revision history. Add operational warnings for published-player shortage and missing judge-seat voice coverage; warnings are bounded code/path/message objects and never block publication. Replace the plan-1 zero usage placeholders with these real aggregates.

- [ ] **Step 4: Remove static registry lookup from Admin routes**

Delete get_rule_set import and _rule_set_summary lookup. Construct Admin summaries from persisted revision columns or historical snapshot. Current catalog rename/archive/default never changes old labels.

- [ ] **Step 5: Make all rule text configuration-driven**

render_rule_text uses actual sheriff_vote_weight and distinguishes badge policy none from double. Self-explosion text renders even when sheriff is disabled. prompts_zh reads pinned rule values from world_state.rule_set_snapshot; remove literal 1.5 and double assumptions. description remains outside system instruction composition.

- [ ] **Step 6: Verify and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_admin_games.py \
  tests/test_admin_live_runs.py tests/test_admin_rule_sets.py \
  tests/test_werewolf_rules.py \
  tests/test_werewolf_lm.py -q
.venv/bin/ruff check app/admin app/api/routes/admin_games.py \
  app/api/routes/admin_live_runs.py app/werewolf/rules.py \
  app/werewolf/engine.py app/werewolf/prompts_zh.py
git add app/admin/games.py app/admin/live_runs.py \
  app/rule_sets/repository.py app/api/routes/admin_rule_sets.py \
  app/api/schemas/admin_rule_sets.py \
  app/api/schemas/admin_games.py app/api/schemas/admin_live_runs.py \
  app/api/routes/admin_games.py app/api/routes/admin_live_runs.py \
  app/werewolf/rules.py app/werewolf/engine.py app/werewolf/prompts_zh.py \
  tests/test_admin_games.py tests/test_admin_live_runs.py \
  tests/test_admin_rule_sets.py \
  tests/test_werewolf_rules.py tests/test_werewolf_lm.py
git commit -m "feat(api): preserve historical rule semantics"
~~~

---

### Task 7: Add Rule Telemetry, Cutover Guardrails and Runbook

**Files:**
- Create: apps/api/app/rule_sets/telemetry.py
- Modify: apps/api/app/api/routes/metrics.py
- Modify: apps/api/app/api/routes/games.py
- Modify: apps/api/app/api/routes/admin_rule_sets.py
- Modify: apps/api/tests/test_metrics.py
- Modify: apps/api/tests/test_games_api.py
- Modify: README.md
- Modify: docs/architecture.md
- Modify: docs/admin-deployment-runbook.md

**Interfaces:**
- Consumes: all prior runtime behavior.
- Produces: observable cutover and rollback instructions.

- [ ] **Step 1: Write failing metrics tests**

Assert metrics for publish result/conflict, create revision conflict, snapshot parse failures by reason, checkpoint failures by reason, legacy no-revision creates, games by stable ID/revision/status, and published default count. Assert labels/logs never include full JSON, description, player names or SQL errors.

- [ ] **Step 2: Run and verify metrics are absent**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_metrics.py \
  tests/test_games_api.py -k "rule_metric or legacy_revision_metric" -q
~~~

- [ ] **Step 3: Implement bounded thread-safe counters**

Use a Lock plus Counter keyed only by fixed result/reason and stable ID/revision. Export record_rule_publish、record_rule_create_conflict、record_rule_snapshot_failure、record_rule_checkpoint_failure、record_legacy_rule_create and render_rule_set_metrics(db). Derive published default count from rule_sets on scrape.

- [ ] **Step 4: Render and instrument metrics**

Append rule metrics to /metrics. Instrument Admin publish outcomes, public create conflicts, snapshot/checkpoint parse failures and terminal game outcomes. Log only stable ID、revision number、schema version and the first 12 hash characters.

- [ ] **Step 5: Document exact rollout**

Runbook order:

1. upgrade Alembic through 20260712_16;
2. verify four seeds and exactly one published default;
3. deploy v1/v2 readers and database source in staging;
4. deploy Admin API/UI and revision-aware Mobile;
5. observe conflict、parse、restore and per-revision failure metrics;
6. production requires RULE_SET_CATALOG_SOURCE=database;
7. rollback application without downgrading schema;
8. never downgrade revision 15 after user-authored rules without an export because it is data-lossy;
9. permanently retain legacy snapshot parser and v1 checkpoint reader.

Configure alerts for published default count not equal to one, sustained snapshot/hash or checkpoint failures, a new revision's failure rate materially above its preceding revision, and legacy no-revision creates continuing past the compatibility deadline.

- [ ] **Step 6: Run the full backend gate and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/alembic check
git add app/rule_sets/telemetry.py app/api/routes/metrics.py \
  app/api/routes/games.py app/api/routes/admin_rule_sets.py \
  tests/test_metrics.py tests/test_games_api.py \
  ../../README.md ../../docs/architecture.md \
  ../../docs/admin-deployment-runbook.md
git commit -m "docs(api): add rule catalog rollout guardrails"
~~~

## Plan Completion Gate

~~~bash
cd apps/api
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/alembic check
~~~

Expected: full API suite PASS, Ruff clean, no missing migration operations。额外检查：创建线程只在 commit 后启动；代码搜索确认 runner/resume/Admin Live 不再调用 get_rule_set；v1 和 v2 checkpoint tests 均通过；数据库模式失败不会返回静态目录。
