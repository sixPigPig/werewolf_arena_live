# 可配置规则集后端目录与管理 API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 建立受限规则配置的纯领域编译器、稳定规则实体与不可变修订目录，并提供具备 RBAC、CSRF、乐观锁和审计的 Admin API。

**Architecture:** app.rule_sets 负责不可信管理配置的规范化、校验、编译、canonical hash 和目录生命周期；app.werewolf.rules 继续保留引擎消费的冻结运行对象。数据库使用 rule_sets 稳定实体和 rule_set_revisions 修订表，服务层只 flush，路由将业务变更与审计放在同一事务提交。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、PostgreSQL、SQLite pytest、Ruff。

## Global Constraints

- 一期只能配置 werewolf、villager、seer、guard、witch、hunter、idiot，不能新增角色、action、行动顺序或胜负算法。
- 玩家人数由角色数量推导，必须为 6–12；seer、guard、witch、hunter、idiot 数量只能为 0 或 1。
- sheriff_vote_weight 只允许 1、1.5、2；未知字段、未知枚举和未知角色全部拒绝。
- display_order 和 is_default 是稳定实体元数据，不进入 revision 内容哈希。
- 发布修订不可原地修改；编辑已发布或已归档规则时创建下一修订草稿。
- description 不进入任意模型指令；模型规则文本只从结构化字段生成。
- 发布、归档、恢复和设置默认的原因必须为 3–500 个字符。
- Viewer、Operator 仅有 rules.read；Content Editor 增加 rules.write；只有 Super Admin 拥有全部规则权限。
- 所有写 API 要求 Admin Session 和 CSRF；服务端权限是最终边界。
- Alembic 修订不得 import 应用运行时代码或 OFFICIAL_RULE_SETS。
- 本计划不修改游戏创建、runner、checkpoint、Mobile 或 Admin Web；这些由后续计划消费本计划接口。

---

## File Structure

- Create apps/api/app/rule_sets/__init__.py：导出跨计划使用的稳定领域接口。
- Create apps/api/app/rule_sets/types.py：管理配置、校验问题、编译结果和目录聚合类型。
- Create apps/api/app/rule_sets/validation.py：Unicode 规范化、字段/组合校验、角色能力目录和派生 action。
- Create apps/api/app/rule_sets/snapshots.py：配置编译、runtime snapshot、legacy parser、canonical JSON 和 SHA-256。
- Create apps/api/app/rule_sets/errors.py：not-found、validation、transition 和乐观锁异常。
- Create apps/api/app/rule_sets/repository.py：稳定实体、修订、分页目录和历史查询。
- Create apps/api/app/rule_sets/service.py：创建、编辑、校验、发布、归档、恢复、默认切换和复制。
- Create apps/api/app/models/rule_set.py：RuleSetRecord 与 RuleSetRevisionRecord。
- Modify apps/api/app/models/__init__.py：注册规则模型。
- Create apps/api/alembic/versions/20260712_15_create_rule_set_catalog.py：两表、索引和四套官方 revision 1 种子。
- Create apps/api/app/api/schemas/admin_rule_sets.py：严格 Admin DTO。
- Create apps/api/app/api/routes/admin_rule_sets.py：Admin 读写、错误映射和审计。
- Modify apps/api/app/admin/rbac.py 与 apps/api/app/api/router.py：权限和路由接入。
- Create tests/test_rule_set_validation.py、test_rule_set_snapshots.py、test_rule_set_migration.py、test_rule_set_repository.py、test_rule_set_service.py、test_admin_rule_sets.py。
- Modify tests/test_models.py、test_admin_rbac.py、test_werewolf_rules.py。

## Stable Interfaces Produced by This Plan

后三份计划只依赖以下命名：

~~~python
from app.rule_sets.types import CompiledRuleSet, RuleSetConfig
from app.rule_sets.snapshots import (
    compile_rule_set_config,
    resolve_rule_set_snapshot,
    rule_set_config_from_snapshot,
)
from app.rule_sets.repository import list_published_rule_sets
from app.rule_sets.service import resolve_published_rule_set
~~~

~~~python
@dataclass(frozen=True)
class CompiledRuleSet:
    config: RuleSetConfig
    rule_set: RuleSet
    snapshot: dict[str, Any]
    schema_version: int
    revision_id: str | None
    revision_no: int | None
    content_hash: str
~~~

Managed snapshot 在现有 runtime 字段之外固定包含 revision_id、revision_no、version、schema_version、content_hash。Managed revision 1 的 version 为字符串 1；legacy snapshot 的 version=2026.04 不重写。

---

### Task 1: Define and Validate the Restricted Rule Configuration

**Files:**
- Create: apps/api/app/rule_sets/__init__.py
- Create: apps/api/app/rule_sets/types.py
- Create: apps/api/app/rule_sets/validation.py
- Test: apps/api/tests/test_rule_set_validation.py

**Interfaces:**
- Consumes: app.werewolf.rules 中现有 RoleSpec、RuleSet 与常量。
- Produces: RuleSetConfig、RuleValidationIssue、RuleSetValidationResult、normalize_rule_set_config()、validate_rule_set_config()。

- [ ] **Step 1: Write the failing validation tests**

~~~python
def valid_config(**overrides: object) -> dict[str, object]:
    value = {
        "name": "经典 8 人局",
        "description": "包含狼人、预言家、守卫与村民的官方标准局。",
        "complexity": "标准",
        "estimated_duration": "中",
        "rule_tags": ["无警长", "顺序发言", "标准"],
        "role_counts": {
            "werewolf": 2, "villager": 4, "seer": 1, "guard": 1,
            "witch": 0, "hunter": 0, "idiot": 0,
        },
        "win_condition": "wolves_gte_others",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1,
        "speech_policy": "sequential",
        "werewolf_self_explosion_enabled": False,
        "sheriff_badge_bomb_policy": "none",
    }
    value.update(overrides)
    return value


def test_normalization_derives_player_count_and_deduplicates_tags() -> None:
    config = normalize_rule_set_config(
        valid_config(name="  经典８人局  ", rule_tags=[" 标准 ", "标准", "新手"])
    )
    assert config.name == "经典8人局"
    assert config.rule_tags == ("标准", "新手")
    assert config.player_count == 8


@pytest.mark.parametrize(
    ("changes", "code", "path"),
    [
        ({"role_counts": {"werewolf": 0, "villager": 6, "seer": 0, "guard": 0,
                          "witch": 0, "hunter": 0, "idiot": 0}},
         "werewolf_required", "role_counts.werewolf"),
        ({"sheriff_enabled": False, "sheriff_vote_weight": 1.5},
         "sheriff_disabled_vote_weight", "sheriff_vote_weight"),
        ({"werewolf_self_explosion_enabled": False,
          "sheriff_badge_bomb_policy": "double"},
         "badge_policy_requires_self_explosion", "sheriff_badge_bomb_policy"),
    ],
)
def test_validation_returns_stable_codes_and_paths(
    changes: dict[str, object], code: str, path: str
) -> None:
    result = validate_rule_set_config(normalize_rule_set_config(valid_config(**changes)))
    assert result.valid is False
    assert [(item.code, item.path) for item in result.errors] == [(code, path)]
~~~

- [ ] **Step 2: Run the test to verify it fails**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_rule_set_validation.py -q
~~~

Expected: collection FAILS with ModuleNotFoundError for app.rule_sets.

- [ ] **Step 3: Add the exact domain types**

~~~python
RuleRoleId = Literal[
    "werewolf", "villager", "seer", "guard", "witch", "hunter", "idiot"
]


@dataclass(frozen=True)
class RuleSetConfig:
    name: str
    description: str
    complexity: str
    estimated_duration: str
    rule_tags: tuple[str, ...]
    role_counts: dict[RuleRoleId, int]
    win_condition: Literal["wolves_gte_others", "slaughter_side"]
    sheriff_enabled: bool
    sheriff_vote_weight: float
    speech_policy: Literal["sequential", "sheriff_directed"]
    werewolf_self_explosion_enabled: bool
    sheriff_badge_bomb_policy: Literal["none", "double"]

    @property
    def player_count(self) -> int:
        return sum(self.role_counts.values())


@dataclass(frozen=True)
class RuleValidationIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class RuleSetValidationResult:
    errors: tuple[RuleValidationIssue, ...]
    warnings: tuple[RuleValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors
~~~

- [ ] **Step 4: Implement strict normalization**

Use NFKC plus trim for every managed text field, including description; reject Unicode control characters. Require the exact seven role keys and non-negative integer values, explicitly rejecting bool. Normalize tags by order-preserving deduplication, maximum 8 items and maximum 20 characters each. Require name 1–120, description 0–1000, complexity/duration 1–40.

~~~python
RULE_ROLE_IDS = ("werewolf", "villager", "seer", "guard", "witch", "hunter", "idiot")
SPECIAL_ROLE_IDS = ("seer", "guard", "witch", "hunter", "idiot")
SHERIFF_VOTE_WEIGHTS = (1.0, 1.5, 2.0)


def normalize_rule_set_config(value: Mapping[str, object]) -> RuleSetConfig:
    unknown = set(value) - CONFIG_FIELDS
    if unknown:
        raise ValueError(f"Unsupported rule fields: {', '.join(sorted(unknown))}")
    raw_counts = value.get("role_counts")
    if not isinstance(raw_counts, Mapping) or set(raw_counts) != set(RULE_ROLE_IDS):
        raise ValueError("role_counts must contain exactly the supported role ids")
    counts: dict[RuleRoleId, int] = {}
    for role_id in RULE_ROLE_IDS:
        count = raw_counts[role_id]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"role_counts.{role_id} must be a non-negative integer")
        counts[role_id] = count
    weight = value.get("sheriff_vote_weight")
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        raise ValueError("sheriff_vote_weight must be numeric")
    try:
        normalized_weight = float(weight)
    except OverflowError as error:
        raise ValueError("sheriff_vote_weight must be finite") from error
    if not math.isfinite(normalized_weight):
        raise ValueError("sheriff_vote_weight must be finite")
    return RuleSetConfig(
        name=_text(value.get("name"), 1, 120, "name"),
        description=_text(value.get("description", ""), 0, 1000, "description"),
        complexity=_text(value.get("complexity"), 1, 40, "complexity"),
        estimated_duration=_text(
            value.get("estimated_duration"), 1, 40, "estimated_duration"
        ),
        rule_tags=_tags(value.get("rule_tags", [])),
        role_counts=counts,
        win_condition=_literal(
            value.get("win_condition"),
            {"wolves_gte_others", "slaughter_side"},
            "win_condition",
        ),
        sheriff_enabled=_bool(value.get("sheriff_enabled"), "sheriff_enabled"),
        sheriff_vote_weight=normalized_weight,
        speech_policy=_literal(
            value.get("speech_policy"),
            {"sequential", "sheriff_directed"},
            "speech_policy",
        ),
        werewolf_self_explosion_enabled=_bool(
            value.get("werewolf_self_explosion_enabled"),
            "werewolf_self_explosion_enabled",
        ),
        sheriff_badge_bomb_policy=_literal(
            value.get("sheriff_badge_bomb_policy"),
            {"none", "double"},
            "sheriff_badge_bomb_policy",
        ),
    )
~~~

- [ ] **Step 5: Implement deterministic cross-field validation**

Return issues in this order: player count 6–12, at least one wolf and one good player, wolves fewer than good players, special counts at most 1, slaughter-side requires god and villager, sheriff weight is exactly 1/1.5/2, sheriff-off forces weight 1 and sequential speech, sheriff-directed requires sheriff, self-explosion-off forces none, double requires both sheriff and self-explosion. Do not auto-correct invalid combinations.

- [ ] **Step 6: Verify and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_rule_set_validation.py -q
.venv/bin/ruff check app/rule_sets tests/test_rule_set_validation.py
git add app/rule_sets tests/test_rule_set_validation.py
git commit -m "feat(api): validate restricted rule configurations"
~~~

Expected: tests PASS and Ruff is clean.

---

### Task 2: Compile Configurations and Pin Canonical Snapshots

**Files:**
- Create: apps/api/app/rule_sets/snapshots.py
- Modify: apps/api/app/rule_sets/__init__.py
- Modify: apps/api/app/werewolf/rules.py:55-255
- Test: apps/api/tests/test_rule_set_snapshots.py
- Test: apps/api/tests/test_werewolf_rules.py

**Interfaces:**
- Consumes: Task 1 RuleSetConfig.
- Produces: compile_rule_set_config(), rule_set_config_from_snapshot(), resolve_rule_set_snapshot() and CompiledRuleSet.

- [ ] **Step 1: Write failing compiler and round-trip tests**

Define complete literal `OFFICIAL_CONFIG_GOLDENS` and `OFFICIAL_RUNTIME_GOLDENS` dictionaries for all four official rules at the top of `test_rule_set_snapshots.py`; do not derive expected data from `get_rule_set()` or `rule_set_snapshot()`. The literal `starter_6` description uses the ASCII comma. Hardcode this exact schema-v1 hash mapping:

~~~python
OFFICIAL_CONFIG_HASHES = {
    "classic_8": "00095728147a022c48eab88faf21a14567ad0afa13ab9418306e84ff85b10131",
    "starter_6": "f2c52827ff3eea2725fbf2f1a01436f69c7e6465a64dec9a92bd7a07a9368f4c",
    "social_8": "21e1bd2bb495e4479a346724c85a9722477f840afc2c99c389558a52427a0fbc",
    "classic_12_seer_witch_hunter_idiot":
        "bcae38e48a7791fa0f7ae236c90f1852056938ea60f5447532e5d879260d6da2",
}
~~~

~~~python
@pytest.mark.parametrize("rule_set_id", tuple(OFFICIAL_CONFIG_GOLDENS))
def test_all_official_configs_match_literal_runtime_and_hash_goldens(
    rule_set_id: str,
) -> None:
    raw_config = copy.deepcopy(OFFICIAL_CONFIG_GOLDENS[rule_set_id])
    config = normalize_rule_set_config(raw_config)
    compiled = compile_rule_set_config(
        rule_set_id,
        config,
        revision_id="revision-1",
        revision_no=1,
    )
    expected = copy.deepcopy(OFFICIAL_RUNTIME_GOLDENS[rule_set_id])
    expected["version"] = "1"
    expected.update(
        revision_id="revision-1",
        revision_no=1,
        schema_version=1,
        content_hash=OFFICIAL_CONFIG_HASHES[rule_set_id],
    )
    assert canonical_rule_set_config(config) == raw_config
    assert compiled.snapshot == expected
    assert compiled.content_hash == OFFICIAL_CONFIG_HASHES[rule_set_id]


def test_managed_snapshot_round_trips_without_catalog_access() -> None:
    compiled = compile_rule_set_config(
        "classic_8", normalize_rule_set_config(valid_config()),
        revision_id="revision-1", revision_no=1,
    )
    restored = resolve_rule_set_snapshot(compiled.snapshot)
    assert restored.rule_set == compiled.rule_set
    assert restored.snapshot == compiled.snapshot


def test_obsolete_fullwidth_comma_starter_legacy_snapshot_is_rejected() -> None:
    snapshot = copy.deepcopy(OFFICIAL_RUNTIME_GOLDENS["starter_6"])
    snapshot["description"] = "更短的官方入门局，适合快速观察模型策略。"
    with pytest.raises(ValueError, match="snapshot field description does not match"):
        resolve_rule_set_snapshot(snapshot)
~~~

Also cover exact ASCII-comma legacy resolution and its full-runtime-snapshot hash `02f31f4aa42e54f83836bf2d9b68c25291181c91a722136ed6a0a9a0e40ea4fc`; compiler/canonical/hash rejection of normalized objects mutated with bool role counts, extra/missing role keys, bool vote weight, and an integer too large for finite float conversion; caller-alias detachment; non-string/unhashable role metadata; missing fields; unknown fields; bool-as-number; NaN/Infinity; derived-action mismatch; and hash mismatch. Every invalid public boundary must raise `ValueError`, never `KeyError`, `TypeError`, or `OverflowError`.

- [ ] **Step 2: Verify the missing module failure**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_rule_set_snapshots.py -q
~~~

Expected: collection FAILS because app.rule_sets.snapshots is missing.

- [ ] **Step 3: Add the fixed capability and action compiler**

~~~python
ROLE_ORDER = ("werewolf", "seer", "guard", "witch", "hunter", "idiot", "villager")


def _night_actions(config: RuleSetConfig) -> tuple[str, ...]:
    actions = [ACTION_REMOVE]
    if config.role_counts["guard"]:
        actions.append(ACTION_PROTECT)
    if config.role_counts["seer"]:
        actions.append(ACTION_INVESTIGATE)
    if config.role_counts["witch"]:
        actions.extend((ACTION_WITCH_SAVE, ACTION_WITCH_POISON))
    return tuple(actions)


def _day_actions(config: RuleSetConfig) -> tuple[str, ...]:
    actions: list[str] = []
    if config.sheriff_enabled:
        actions.extend((
            ACTION_SHERIFF_RUN, ACTION_SHERIFF_SPEECH, ACTION_SHERIFF_WITHDRAW,
            ACTION_SHERIFF_VOTE, ACTION_SHERIFF_PK_SPEECH,
            ACTION_SHERIFF_RUNOFF_VOTE,
        ))
    if config.werewolf_self_explosion_enabled:
        actions.append(ACTION_WEREWOLF_SELF_EXPLOSION)
    if config.sheriff_enabled and config.speech_policy == SPEECH_POLICY_SHERIFF_DIRECTED:
        actions.append(ACTION_SPEECH_ORDER)
    actions.extend((ACTION_DEBATE, ACTION_VOTE))
    if config.role_counts["hunter"]:
        actions.append(ACTION_HUNTER_SHOOT)
    actions.append(ACTION_SUMMARIZE)
    return tuple(actions)
~~~

Map each stable role ID to the current exact Chinese role, team, model_group and category; the management input must never submit those derived values.

The compiler always derives reveal_policy="hidden" and speech_rounds=1. These fields are runtime snapshot output, never management input.

Before compiler code indexes or sums roles, converts vote weight, builds runtime objects, or hashes content, reconstruct all `RuleSetConfig` fields through `normalize_rule_set_config()` and full cross-field validation. Use only that detached normalized result. Apply the same boundary in `canonical_rule_set_config()` (and therefore hashing), so a previously normalized object whose mutable `role_counts` or frozen fields were later mutated is rejected with `ValueError`; compiled runtime and snapshot output must retain no caller-owned mutable alias.

- [ ] **Step 4: Implement the exact hash boundary**

~~~python
RULE_SCHEMA_VERSION = 1


def canonical_rule_set_config(config: RuleSetConfig) -> dict[str, object]:
    config = _normalize_config_boundary(config)
    return {
        "name": config.name,
        "description": config.description,
        "complexity": config.complexity,
        "estimated_duration": config.estimated_duration,
        "rule_tags": list(config.rule_tags),
        "role_counts": {
            role_id: config.role_counts[role_id] for role_id in RULE_ROLE_IDS
        },
        "win_condition": config.win_condition,
        "sheriff_enabled": config.sheriff_enabled,
        "sheriff_vote_weight": float(config.sheriff_vote_weight),
        "speech_policy": config.speech_policy,
        "werewolf_self_explosion_enabled":
            config.werewolf_self_explosion_enabled,
        "sheriff_badge_bomb_policy": config.sheriff_badge_bomb_policy,
    }


def rule_set_content_hash(config: RuleSetConfig) -> str:
    payload = {"schema_version": 1, "config": canonical_rule_set_config(config)}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
~~~

The hash excludes stable ID, revision metadata, compatibility version, display_order, is_default and all derived fields.

- [ ] **Step 5: Implement strict snapshot parsing**

The parser accepts exactly the current legacy runtime fields plus optional revision_id、revision_no、schema_version、content_hash. Before tuple lookup, every role metadata field (`role`、`team`、`model_group`、`category`) must be a string. It maps roles back to stable IDs, recompiles, compares every ordered runtime field, and verifies hash when present. A managed snapshot additionally requires schema_version=1 and version=str(revision_no). Unknown or incomplete snapshots fail explicitly; there is no fallback to a current rule ID. Preserve general schema-v1 and exact-current legacy support, but reject the obsolete fullwidth-comma `starter_6` snapshot rather than rewriting or mapping it.

- [ ] **Step 6: Verify and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_rule_set_snapshots.py tests/test_werewolf_rules.py -q
.venv/bin/ruff check app/rule_sets app/werewolf/rules.py tests/test_rule_set_snapshots.py
git add app/rule_sets app/werewolf/rules.py tests/test_rule_set_snapshots.py tests/test_werewolf_rules.py
git commit -m "feat(api): compile and hash rule set snapshots"
~~~

---

### Task 3: Add Versioned Catalog Tables and Official Seeds

**Files:**
- Create: apps/api/app/models/rule_set.py
- Modify: apps/api/app/models/__init__.py
- Create: apps/api/alembic/versions/20260712_15_create_rule_set_catalog.py
- Modify: apps/api/tests/test_models.py
- Create: apps/api/tests/test_rule_set_migration.py

**Interfaces:**
- Consumes: Task 2 hash contract, duplicated as frozen migration data.
- Produces: RuleSetRecord、RuleSetRevisionRecord and four published revision 1 rows.

- [ ] **Step 1: Write failing metadata and migration tests**

~~~python
def test_rule_set_catalog_tables_match_expected_schema() -> None:
    assert set(RuleSetRecord.__table__.columns.keys()) == {
        "id", "status", "current_published_revision_id", "draft_revision_id",
        "is_default", "display_order", "lock_version", "created_by_user_id",
        "updated_by_user_id", "archived_by_user_id", "created_at",
        "updated_at", "archived_at",
    }
    assert set(RuleSetRevisionRecord.__table__.columns.keys()) == {
        "id", "rule_set_id", "revision_no", "state", "schema_version",
        "content_hash", "lock_version", "name", "description",
        "player_count", "role_summary", "complexity", "estimated_duration",
        "config", "created_by_user_id", "updated_by_user_id",
        "published_by_user_id", "publish_reason", "created_at",
        "updated_at", "published_at",
    }
~~~

Migration tests assert revision=20260712_15, down_revision=20260711_14, four rows, one default, exact IDs/hashes, and downgrade removal.

- [ ] **Step 2: Run and verify missing model/migration failures**

~~~bash
cd apps/api
.venv/bin/python -m pytest \
  tests/test_models.py::test_rule_set_catalog_tables_match_expected_schema \
  tests/test_rule_set_migration.py -q
~~~

- [ ] **Step 3: Implement models and constraints**

Use String(36) UUIDs. Revision to parent is an ON DELETE RESTRICT FK. Parent revision pointers are indexed String(36) columns without reverse FKs to avoid circular SQLite DDL; service tests enforce ownership.

Required constraint/index names:

~~~python
ck_rule_sets_status
ck_rule_sets_lock_version_positive
ck_rule_sets_display_order_nonnegative
ck_rule_sets_default_published
ck_rule_sets_pointer_state
ck_rule_sets_archive_timestamp
ck_rule_set_revisions_state
ck_rule_set_revisions_revision_positive
ck_rule_set_revisions_schema_version
ck_rule_set_revisions_lock_version_positive
ck_rule_set_revisions_publish_fields
uq_rule_set_revisions_rule_revision
uq_rule_sets_one_default
uq_rule_set_revisions_one_draft
uq_rule_set_revisions_one_published
~~~

Both models use __mapper_args__ = {"version_id_col": lock_version}. Partial unique indexes define both PostgreSQL and SQLite predicates.

ck_rule_sets_pointer_state requires a draft pointer for draft status, a current published pointer for published status, and at least one retained pointer for archived status. ck_rule_sets_archive_timestamp requires archived_at only for archived status. ck_rule_set_revisions_publish_fields allows draft hash/published fields to be NULL but requires content_hash and published_at for published/superseded rows; system-seeded revisions may have NULL actor/reason fields.

- [ ] **Step 4: Add the frozen migration and seeds**

| Stable ID | Revision ID | Content hash | Order | Default |
|---|---|---|---:|---:|
| classic_8 | e9fa678e-9b18-5079-91d2-f74835364fb6 | 00095728147a022c48eab88faf21a14567ad0afa13ab9418306e84ff85b10131 | 1 | true |
| starter_6 | b607e17e-b86f-5eb0-9dc2-b8df09aa71ab | f2c52827ff3eea2725fbf2f1a01436f69c7e6465a64dec9a92bd7a07a9368f4c | 2 | false |
| social_8 | 2b4a993f-e4e6-5312-b11d-92874851a70a | 21e1bd2bb495e4479a346724c85a9722477f840afc2c99c389558a52427a0fbc | 3 | false |
| classic_12_seer_witch_hunter_idiot | 0489f6ac-16fd-5323-96ce-ee256c98cf32 | bcae38e48a7791fa0f7ae236c90f1852056938ea60f5447532e5d879260d6da2 | 4 | false |

Embed all normalized config fields from the four current rules. Each parent is published and points at revision 1; revision is published, schema_version=1, lock_version=1. Do not import app code.

The frozen configs are exactly:

~~~json
{"classic_8":{"name":"经典 8 人局","description":"包含狼人、预言家、守卫与村民的官方标准局。","complexity":"标准","estimated_duration":"中","rule_tags":["无警长","顺序发言","标准"],"role_counts":{"werewolf":2,"villager":4,"seer":1,"guard":1,"witch":0,"hunter":0,"idiot":0},"win_condition":"wolves_gte_others","sheriff_enabled":false,"sheriff_vote_weight":1.0,"speech_policy":"sequential","werewolf_self_explosion_enabled":false,"sheriff_badge_bomb_policy":"none"},"starter_6":{"name":"新手 6 人快局","description":"更短的官方入门局,适合快速观察模型策略。","complexity":"入门","estimated_duration":"短","rule_tags":["无警长","顺序发言","新手"],"role_counts":{"werewolf":1,"villager":3,"seer":1,"guard":1,"witch":0,"hunter":0,"idiot":0},"win_condition":"wolves_gte_others","sheriff_enabled":false,"sheriff_vote_weight":1.0,"speech_policy":"sequential","werewolf_self_explosion_enabled":false,"sheriff_badge_bomb_policy":"none"},"social_8":{"name":"社交 8 人局","description":"仅保留狼人夜晚行动的官方心理博弈局。","complexity":"心理","estimated_duration":"中","rule_tags":["无警长","顺序发言","心理"],"role_counts":{"werewolf":2,"villager":6,"seer":0,"guard":0,"witch":0,"hunter":0,"idiot":0},"win_condition":"wolves_gte_others","sheriff_enabled":false,"sheriff_vote_weight":1.0,"speech_policy":"sequential","werewolf_self_explosion_enabled":false,"sheriff_badge_bomb_policy":"none"},"classic_12_seer_witch_hunter_idiot":{"name":"12 人预女猎白局","description":"4 狼、预言家、女巫、猎人、白痴与 4 民的标准屠边局。","complexity":"进阶","estimated_duration":"长","rule_tags":["有警长","警徽 1.5 票","屠边","预女猎白"],"role_counts":{"werewolf":4,"villager":4,"seer":1,"guard":0,"witch":1,"hunter":1,"idiot":1},"win_condition":"slaughter_side","sheriff_enabled":true,"sheriff_vote_weight":1.5,"speech_policy":"sheriff_directed","werewolf_self_explosion_enabled":true,"sheriff_badge_bomb_policy":"double"}}
~~~

`starter_6` 的 ASCII 逗号配置和上述新 hash 是唯一冻结 seed。旧全角逗号 canonical config/legacy snapshot 与 schema-v1 规范不一致，明确不兼容，也不是迁移或历史回填候选。

- [ ] **Step 5: Protect immutable revisions**

An ORM before_update listener allows a published revision only to change state from published to superseded with no content-field changes. A superseded revision cannot change. A before_delete listener permits deletion only for a never-published draft.

- [ ] **Step 6: Verify and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_models.py tests/test_rule_set_migration.py -q
.venv/bin/alembic check
.venv/bin/ruff check app/models/rule_set.py \
  alembic/versions/20260712_15_create_rule_set_catalog.py \
  tests/test_rule_set_migration.py
git add app/models/rule_set.py app/models/__init__.py \
  alembic/versions/20260712_15_create_rule_set_catalog.py \
  tests/test_models.py tests/test_rule_set_migration.py
git commit -m "feat(api): add versioned rule set catalog"
~~~

---

### Task 4: Add Repository Reads and Safe Snapshots

**Files:**
- Create: apps/api/app/rule_sets/repository.py
- Modify: apps/api/app/rule_sets/snapshots.py
- Test: apps/api/tests/test_rule_set_repository.py

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces: RuleSetAggregate、RuleSetPage、list_published_rule_sets() and bounded response snapshots.

- [ ] **Step 1: Write failing repository tests**

Seed published、draft-only、archived records. Assert q/status/player_count/sort/page behavior and public ordering is is_default DESC、display_order ASC、id ASC. Assert draft/archived rows never appear in public results.

- [ ] **Step 2: Run and verify the missing repository failure**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_rule_set_repository.py -q
~~~

- [ ] **Step 3: Implement exact result types and functions**

~~~python
@dataclass(frozen=True)
class RuleSetAggregate:
    record: RuleSetRecord
    draft: RuleSetRevisionRecord | None
    published: RuleSetRevisionRecord | None
    revisions: tuple[RuleSetRevisionRecord, ...] = ()


@dataclass(frozen=True)
class RuleSetPage:
    items: tuple[RuleSetAggregate, ...]
    page: int
    page_size: int
    total: int
    pages: int
~~~

Implement list_rule_sets、get_rule_set_record、get_rule_set_aggregate、get_rule_set_revision、list_rule_set_revisions(limit=50)、next_rule_set_revision_no and list_published_rule_sets. Validate parent pointer ownership; mismatches raise RuleSetCatalogCorrupt.

- [ ] **Step 4: Add bounded snapshots**

Add admin_rule_set_snapshot、admin_rule_revision_snapshot(include_config)、public_rule_set_catalog_snapshot and audit_rule_set_snapshot. Audit output contains only IDs、states、versions、hashes and changed fields, never config/description/full runtime snapshot. Public output compiles current published revision and includes roles plus managed metadata.

- [ ] **Step 5: Verify and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_rule_set_repository.py -q
.venv/bin/ruff check app/rule_sets/repository.py app/rule_sets/snapshots.py
git add app/rule_sets tests/test_rule_set_repository.py
git commit -m "feat(api): query rule set catalog revisions"
~~~

---

### Task 5: Implement Lifecycle Services

**Files:**
- Create: apps/api/app/rule_sets/errors.py
- Create: apps/api/app/rule_sets/service.py
- Test: apps/api/tests/test_rule_set_service.py

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces: all mutations and resolve_published_rule_set().

- [ ] **Step 1: Write failing workflow and conflict tests**

Cover create → publish → fork-on-edit → republish; archive/restore; duplicate; one draft/current/default; stale parent/revision versions; default archive with and without atomic replacement; published/superseded immutability.

- [ ] **Step 2: Verify missing service symbols**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_rule_set_service.py -q
~~~

- [ ] **Step 3: Add stable exceptions**

Define RuleSetNotFound、RuleSetRevisionNotFound、RuleSetValidationFailed、RuleSetVersionConflict、RuleSetTransitionConflict、RuleRevisionChanged、RuleSetUnavailable、DefaultRuleRequired and RuleSetCatalogCorrupt. Carry only bounded IDs/versions/issues.

- [ ] **Step 4: Implement exact service signatures**

~~~python
def create_rule_set(
    db: Session, *, rule_set_id: str, config: RuleSetConfig,
    display_order: int, actor_user_id: int,
) -> RuleSetAggregate

def update_rule_set_draft(
    db: Session, rule_set_id: str, *, config: RuleSetConfig,
    display_order: int, expected_rule_set_lock_version: int,
    expected_revision_lock_version: int | None, actor_user_id: int,
) -> RuleSetAggregate

@dataclass(frozen=True)
class RuleSetDraftValidation:
    aggregate: RuleSetAggregate
    validation: RuleSetValidationResult
    compiled: CompiledRuleSet | None

def validate_rule_set_draft(
    db: Session, rule_set_id: str, *,
    expected_revision_lock_version: int,
) -> RuleSetDraftValidation

def publish_rule_set(
    db: Session, rule_set_id: str, *,
    expected_rule_set_lock_version: int,
    expected_revision_lock_version: int,
    reason: str, actor_user_id: int,
) -> RuleSetAggregate

def archive_rule_set(
    db: Session, rule_set_id: str, *,
    expected_rule_set_lock_version: int,
    replacement_default_rule_set_id: str | None,
    replacement_expected_lock_version: int | None,
    reason: str, actor_user_id: int,
) -> RuleSetAggregate

def restore_rule_set(
    db: Session, rule_set_id: str, *,
    expected_rule_set_lock_version: int,
    reason: str, actor_user_id: int,
) -> RuleSetAggregate

def set_default_rule_set(
    db: Session, rule_set_id: str, *,
    expected_rule_set_lock_version: int,
    previous_default_expected_lock_version: int | None,
    reason: str, actor_user_id: int,
) -> RuleSetDefaultChange

def duplicate_rule_set(
    db: Session, source_rule_set_id: str, *,
    new_rule_set_id: str, new_name: str,
    expected_source_lock_version: int, actor_user_id: int,
) -> RuleSetAggregate

def resolve_published_rule_set(
    db: Session, rule_set_id: str, *,
    expected_revision_id: str | None = None,
    for_update: bool = False,
) -> CompiledRuleSet
~~~

All functions flush but never commit. Lock multiple parents in sorted ID order. validate_rule_set_draft returns compiled=None when validation errors exist and never raises merely because valid is false. Publish revalidates and round-trips, raises RuleSetValidationFailed on errors, supersedes prior current, freezes hash, updates pointers and restores archived parent. Restore creates no revision. Duplicate creates revision 1 draft and copies no lifecycle/default/audit state.

- [ ] **Step 5: Verify and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_rule_set_service.py -q
.venv/bin/ruff check app/rule_sets/errors.py app/rule_sets/service.py
git add app/rule_sets/errors.py app/rule_sets/service.py \
  tests/test_rule_set_service.py
git commit -m "feat(api): manage rule set revision lifecycle"
~~~

---

### Task 6: Add Admin DTO, RBAC and Read Endpoints

**Files:**
- Create: apps/api/app/api/schemas/admin_rule_sets.py
- Create: apps/api/app/api/routes/admin_rule_sets.py
- Modify: apps/api/app/admin/rbac.py:13-64
- Modify: apps/api/app/api/router.py:3-35
- Modify: apps/api/tests/test_admin_rbac.py
- Create: apps/api/tests/test_admin_rule_sets.py

**Interfaces:**
- Consumes: Tasks 4–5.
- Produces: exact Admin JSON contract for the Admin Web plan.

- [ ] **Step 1: Write failing auth/RBAC/read tests**

Assert Viewer/Operator read, Content Editor write but no high-risk permissions, Super Admin all. Copy the SQLite/TestClient fixture from test_admin_player_profiles.py and cover 401、403、options、list filters/pagination and bounded detail/history.

- [ ] **Step 2: Verify missing permission/404 failures**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_admin_rbac.py \
  tests/test_admin_rule_sets.py -k "authentication or read or options or list" -q
~~~

- [ ] **Step 3: Add exact permission strings**

~~~python
RULES_READ = "rules.read"
RULES_WRITE = "rules.write"
RULES_PUBLISH = "rules.publish"
RULES_ARCHIVE = "rules.archive"
RULES_SET_DEFAULT = "rules.set_default"
~~~

Add RULES_READ to viewer base; add only RULES_WRITE to Content Editor; Super Admin remains frozenset(AdminPermission).

- [ ] **Step 4: Add strict Pydantic contracts**

All request models use ConfigDict(extra="forbid"). AdminRuleRoleCounts has exactly seven integer fields. AdminRuleSetDraftUpdate carries expected_rule_set_lock_version、expected_revision_lock_version、display_order、config. Transition requests carry stable/revision versions and 3–500 reason. Archive additionally carries optional replacement default ID/version. ID regex is ^[a-z][a-z0-9_]{2,79}$.

- [ ] **Step 5: Add and mount options/list/detail routes**

GET routes require rules.read and no CSRF. rule-set-options returns all role labels/limits, enum choices, player min/max 6/12, tag limits, ID pattern and reason limits. Detail returns stable metadata, current draft/published, at most 50 revisions, and real usage counts using current storage: LiveRunRecord.rule_set_id plus GameSessionRecord.rule_set JSON id. It also returns bounded published-player-shortage and judge-seat-coverage warnings. The runtime plan replaces the game JSON predicate with indexed scalar/revision aggregates. Set no-store headers.

- [ ] **Step 6: Verify and commit**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_admin_rbac.py \
  tests/test_admin_rule_sets.py -k "authentication or read or options or list or detail" -q
.venv/bin/ruff check app/admin/rbac.py app/api/schemas/admin_rule_sets.py \
  app/api/routes/admin_rule_sets.py
git add app/admin/rbac.py app/api/router.py app/api/schemas/admin_rule_sets.py \
  app/api/routes/admin_rule_sets.py tests/test_admin_rbac.py \
  tests/test_admin_rule_sets.py
git commit -m "feat(api): expose admin rule set reads"
~~~

---

### Task 7: Complete Admin Mutations, Problems and Audit

**Files:**
- Modify: apps/api/app/api/routes/admin_rule_sets.py
- Modify: apps/api/app/api/schemas/admin_rule_sets.py
- Modify: apps/api/tests/test_admin_rule_sets.py

**Interfaces:**
- Consumes: all Task 5 services and existing record_audit_event().
- Produces: complete Admin contract.

- [ ] **Step 1: Write failing mutation tests**

Cover create、draft update、validate、publish、archive、restore、set-default、duplicate; missing CSRF; Content Editor denial for high-risk operations; Super Admin success; validation paths; stale conflicts; success/failure/conflict/rejected audit rows.

- [ ] **Step 2: Run and verify endpoint failures**

~~~bash
cd apps/api
.venv/bin/python -m pytest tests/test_admin_rule_sets.py \
  -k "create or draft or validate or publish or archive or restore or default or duplicate or audit or conflict" -q
~~~

- [ ] **Step 3: Implement low-risk mutations**

POST /rule-sets creates revision 1 draft; PATCH /{id}/draft performs clone-on-first-edit; POST /{id}/validate validates the exact expected draft and always returns valid/errors/warnings. compiled_snapshot、content_hash、rule_text_preview are present only when valid=true; an invalid validation request returns HTTP 200 and records audit result rejected. POST /{id}/duplicate creates a new draft. Require rules.write and CSRF.

- [ ] **Step 4: Implement high-risk transitions**

Publish requires rules.publish; archive/restore require rules.archive; set-default requires rules.set_default. Require CSRF and reason. Archive may switch replacement default in the same transaction. Add success audit before one commit.

- [ ] **Step 5: Map failures and persist bounded audit attempts**

Rollback business changes, re-read bounded versions, write one audit attempt, commit that audit, then return exact codes:

~~~text
rule_set_validation_failed
rule_set_version_conflict
rule_revision_changed
rule_set_unavailable
default_rule_required
rule_set_store_unavailable
~~~

Never expose SQL, exception repr, config JSON or description as error detail.

- [ ] **Step 6: Verify all backend rule work**

~~~bash
cd apps/api
.venv/bin/python -m pytest \
  tests/test_rule_set_validation.py tests/test_rule_set_snapshots.py \
  tests/test_rule_set_migration.py tests/test_rule_set_repository.py \
  tests/test_rule_set_service.py tests/test_admin_rule_sets.py \
  tests/test_admin_rbac.py -q
.venv/bin/ruff check app tests
.venv/bin/alembic check
~~~

- [ ] **Step 7: Commit**

~~~bash
git add apps/api/app/api/routes/admin_rule_sets.py \
  apps/api/app/api/schemas/admin_rule_sets.py \
  apps/api/tests/test_admin_rule_sets.py
git commit -m "feat(api): manage rule sets through admin API"
~~~

## Plan Completion Gate

~~~bash
cd apps/api
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/alembic check
~~~

Expected: full API suite PASS, Ruff clean, no pending Alembic operations。确认四套官方种子编译行为不变、Content Editor 无法执行高风险转换、已发布修订不可更改。
