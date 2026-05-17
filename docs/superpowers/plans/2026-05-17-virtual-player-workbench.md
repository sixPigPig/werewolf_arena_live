# Virtual Player Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move virtual player creation into a dedicated `/players` workbench page and enrich reusable player profiles with identity, speaking style, strategy sliders, examples, and a preview surface.

**Architecture:** Keep the saved virtual player profile as the single reusable unit, extend the existing profile API/storage with richer fields, and compose those fields into the existing runtime `personality` snapshot when a game starts. The new player workbench owns profile creation/editing; the game lobby only consumes saved profiles for seat assignment.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy ORM, Alembic, pytest, React 19, React Router, TanStack Query, Vitest, Testing Library, existing gothic CSS assets, local image uploads, and the current model-options API.

---

## Reference Cases

The next version should borrow patterns from three product families without copying their surface design.

- Character.AI separates quick creation from deeper character attributes such as name, avatar, tagline, description, greeting, voice, and visibility. Use this to keep the first screen approachable while still offering an advanced editor. Source: <https://book.character.ai/character-book/how-to-quick-creation>
- SillyTavern treats characters as reusable cards with avatar, description, first message, scenario, tags, search, import/export, duplication, and persona concepts. Use this for library management and reusable profile cards. Source: <https://docs.sillytavern.app/usage/characters/>
- Inworld AI models game characters through character profile, personality, dialogue style, knowledge, emotional state, and goals. Use this for game-facing fields such as strategy, pressure response, and speaking style. Source: <https://docs.inworld.ai/unreal-engine/runtime/templates/character>
- D&D Beyond and BG3 use stepwise character creation with identity, origin/background, class/role, ability choices, and final review. Use this for a segmented editor with a persistent preview. Sources: <https://dndbeyond-support.wizards.com/hc/en-us/articles/7747202748436-Builder-Sections> and <https://bg3.wiki/wiki/Character_Creation>

## Product Scope

### In Scope

- Dedicated route `/players`.
- Global navigation entry from the game lobby to the player workbench.
- Player library with search, tag filter, model/personality filter, favorite filter, duplicate, delete, edit, and create.
- Rich profile editor with sections:
  - Basic: name, avatar, model, tags, favorite.
  - Identity: short description, background story, speaking style, catchphrases.
  - Werewolf strategy: strategy profile plus five 1-5 numeric tendencies.
  - Examples: example messages that represent the player voice.
  - Preview: compact profile card and prompt preview showing what will be sent to the runtime.
- Existing avatar upload and system avatar selection remain available.
- Game creation keeps seat assignment, but profile creation/editing moves out of the `/games` page.
- Runtime game players receive a composed personality text that includes the enriched profile settings.

### Out Of Scope For This Iteration

- Live model call for "try speaking once".
- Multi-profile lineup templates.
- Import/export JSON.
- Per-user private profiles beyond the existing nullable `owner_user_id`.
- Full prompt version history.

## Profile Field Design

Extend `VirtualPlayerProfile` and profile API payloads with these fields. Defaults are chosen so all existing saved profiles continue to render and run.

| Field | Type | Default | Validation | Purpose |
| --- | --- | --- | --- | --- |
| `short_description` | string | `""` | max 160 | One-line profile summary shown on cards. |
| `background_story` | string | `""` | max 1200 | Character background and self-image. |
| `speaking_style` | string | `""` | max 800 | Dialogue tone, sentence rhythm, and reasoning style. |
| `catchphrases` | string[] | `[]` | max 6 items, each max 40 | Common phrases and verbal habits. |
| `strategy_profile` | string | `"balanced"` | registered strategy id | High-level Werewolf play archetype. |
| `risk_tolerance` | int | `3` | 1..5 | Willingness to make bold reads or plays. |
| `bluffing_tendency` | int | `3` | 1..5 | Tendency to bluff, fake certainty, or pressure. |
| `trust_tendency` | int | `3` | 1..5 | Speed of trusting other players. |
| `leadership_tendency` | int | `3` | 1..5 | Willingness to lead discussion and voting. |
| `talkativeness` | int | `3` | 1..5 | Average speech length and frequency. |
| `example_messages` | string[] | `[]` | max 5 items, each max 240 | Sample speeches used in prompt composition and preview. |
| `favorite` | bool | `false` | boolean | Library filtering and quick access. |

Strategy profile registry:

```python
STRATEGY_PRESETS = {
    "balanced": "稳健观察，按证据推进，不轻易极端站边。",
    "logic_leader": "偏逻辑带队，主动整理票型、发言顺序和矛盾链。",
    "shadow_wolf": "擅长隐藏动机，低调拆票，避免过早成为焦点。",
    "social_reader": "偏社交阅读，重视情绪变化、关系线和发言姿态。",
    "pressure_attacker": "喜欢强压和快速验人式提问，用压力制造信息。",
    "cautious_observer": "谨慎慢热，先收集信息，再给出明确判断。",
}
```

## UX Structure

### `/players` Page

Use a work-focused application layout, not a landing page.

- Top navigation: brand, "返回大厅", "新建虚拟玩家".
- Left rail: search input, filters, sorting, profile list/card grid.
- Center editor: segmented tabs for Basic, Identity, Strategy, Examples.
- Right preview: portrait, name, tags, model, personality summary, strategy radar-like values using compact stat bars, composed prompt preview.
- Empty state: one primary action to create a profile, plus four system avatar examples visible in the first viewport.

### `/games` Page

- Remove the embedded `VirtualPlayerLibrary` editor from the lobby.
- Keep `CreateGameRunForm` and `PlayerConfigPanel` seat assignment.
- Add a compact link or nav action to `/players`.
- When no profiles exist, show an inline hint in the seat selection panel: "先去玩家库创建可复用虚拟玩家".

## File Structure

Backend:

- Modify `apps/api/app/models/virtual_player_profile.py`: add rich profile columns.
- Create `apps/api/alembic/versions/20260517_02_expand_virtual_player_profiles.py`: migration chained after `20260517_01`.
- Modify `apps/api/app/werewolf/player_profile_store.py`: file fallback version 3 with defaults for rich fields.
- Modify `apps/api/app/werewolf/player_presets.py`: add strategy preset registry and validation.
- Create `apps/api/app/werewolf/player_profile_prompts.py`: compose profile settings into game-facing prompt text.
- Modify `apps/api/app/api/routes/player_profiles.py`: extend create/update/response schemas and validation.
- Modify `apps/api/app/werewolf/player_configs.py`: include composed enriched personality in runtime snapshots.
- Modify `apps/api/tests/test_player_profiles_api.py`: profile persistence, validation, update, and fallback tests.
- Modify `apps/api/tests/test_games_api.py`: game run snapshots include enriched profile prompt.
- Modify `apps/api/tests/test_werewolf_runner.py`: engine receives enriched personality fields.
- Modify `apps/api/tests/test_models.py`: schema assertions for new columns.

Frontend:

- Modify `apps/web/src/features/games/types.ts`: extend `VirtualPlayerProfile`, `PlayerProfileRequest`, and `PlayerConfig`.
- Create `apps/web/src/features/games/playerStrategyOptions.ts`: shared strategy labels, defaults, and numeric labels.
- Create `apps/web/src/features/games/profilePromptPreview.ts`: client-side mirror for preview text.
- Create `apps/web/src/pages/PlayersPage.tsx`: route shell and nav actions.
- Create `apps/web/src/pages/components/PlayersWorkspace.tsx`: query/mutation ownership for player workbench.
- Modify `apps/web/src/routes/definitions.tsx`: add `/players`.
- Modify `apps/web/src/pages/GamesPage.tsx`: add player workbench nav action.
- Modify `apps/web/src/pages/components/GamesWorkspace.tsx`: remove embedded profile editor, keep profile query for game creation.
- Split `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx` into smaller components:
  - Create `apps/web/src/features/games/components/VirtualPlayerCardGrid.tsx`.
  - Create `apps/web/src/features/games/components/VirtualPlayerEditor.tsx`.
  - Create `apps/web/src/features/games/components/VirtualPlayerPreview.tsx`.
  - Keep `VirtualPlayerLibrary.tsx` as composition for the `/players` workbench.
- Modify `apps/web/src/features/games/components/PlayerConfigPanel.tsx`: empty-state link to `/players`.
- Modify `apps/web/src/styles/index.css`: player workbench layout, editor sections, stat controls, preview panel.
- Create `apps/web/src/pages/PlayersPage.test.tsx`: route, create, edit, filter, and save behavior.
- Modify `apps/web/src/pages/GamesPage.test.tsx`: lobby no longer embeds the full editor and still passes profiles to seat assignment.
- Modify `apps/web/src/features/games/components/VirtualPlayerLibrary.test.tsx`: enriched editor behavior.

---

### Task 1: Backend Rich Profile Schema

**Files:**
- Modify: `apps/api/app/models/virtual_player_profile.py`
- Create: `apps/api/alembic/versions/20260517_02_expand_virtual_player_profiles.py`
- Modify: `apps/api/app/werewolf/player_profile_store.py`
- Modify: `apps/api/app/werewolf/player_presets.py`
- Modify: `apps/api/app/api/routes/player_profiles.py`
- Modify: `apps/api/tests/test_models.py`
- Modify: `apps/api/tests/test_player_profiles_api.py`

- [ ] **Step 1: Write failing schema and API tests**

Append to `apps/api/tests/test_models.py`:

```python
def test_virtual_player_profile_has_rich_character_columns() -> None:
    table = VirtualPlayerProfile.__table__

    for column_name in (
        "short_description",
        "background_story",
        "speaking_style",
        "catchphrases",
        "strategy_profile",
        "risk_tolerance",
        "bluffing_tendency",
        "trust_tendency",
        "leadership_tendency",
        "talkativeness",
        "example_messages",
        "favorite",
    ):
        assert column_name in table.c
        assert table.c[column_name].nullable is False
```

Append to `apps/api/tests/test_player_profiles_api.py`:

```python
def test_create_profile_persists_rich_character_settings() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "夜谈控场",
            "model": "deepseek-v4-flash",
            "short_description": "沉稳控场，喜欢先盘逻辑再给站边。",
            "background_story": "长期观察圆桌局的复盘型玩家。",
            "speaking_style": "短句推进，先列证据，再给结论。",
            "catchphrases": ["我先盘票型", "这里不急着站死"],
            "strategy_profile": "logic_leader",
            "risk_tolerance": 2,
            "bluffing_tendency": 2,
            "trust_tendency": 3,
            "leadership_tendency": 5,
            "talkativeness": 4,
            "example_messages": ["我认为 3 号这一轮的视角不完整，先听后置位补充。"],
            "favorite": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["short_description"] == "沉稳控场，喜欢先盘逻辑再给站边。"
    assert payload["catchphrases"] == ["我先盘票型", "这里不急着站死"]
    assert payload["strategy_profile"] == "logic_leader"
    assert payload["risk_tolerance"] == 2
    assert payload["leadership_tendency"] == 5
    assert payload["example_messages"] == ["我认为 3 号这一轮的视角不完整，先听后置位补充。"]
    assert payload["favorite"] is True
```

Append validation coverage:

```python
def test_create_profile_rejects_invalid_strategy_slider_values() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "越界玩家",
            "model": "deepseek-v4-flash",
            "strategy_profile": "unknown",
            "risk_tolerance": 6,
        },
    )

    assert response.status_code == 422
```

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```bash
cd apps/api && PYTHONPATH=. .venv/bin/python -m pytest tests/test_models.py tests/test_player_profiles_api.py -q
```

Expected: failures mention missing rich columns or unexpected request fields.

- [ ] **Step 3: Add backend fields and migration**

Add these columns to `VirtualPlayerProfile`:

```python
short_description: Mapped[str] = mapped_column(String(160), nullable=False, default="")
background_story: Mapped[str] = mapped_column(Text, nullable=False, default="")
speaking_style: Mapped[str] = mapped_column(Text, nullable=False, default="")
catchphrases: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), nullable=False, default=list)
strategy_profile: Mapped[str] = mapped_column(String(40), nullable=False, default="balanced")
risk_tolerance: Mapped[int] = mapped_column(nullable=False, default=3)
bluffing_tendency: Mapped[int] = mapped_column(nullable=False, default=3)
trust_tendency: Mapped[int] = mapped_column(nullable=False, default=3)
leadership_tendency: Mapped[int] = mapped_column(nullable=False, default=3)
talkativeness: Mapped[int] = mapped_column(nullable=False, default=3)
example_messages: Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), nullable=False, default=list)
favorite: Mapped[bool] = mapped_column(nullable=False, default=False)
```

Create `apps/api/alembic/versions/20260517_02_expand_virtual_player_profiles.py`:

```python
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260517_02"
down_revision = "20260517_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("virtual_player_profiles", sa.Column("short_description", sa.String(length=160), nullable=False, server_default=""))
    op.add_column("virtual_player_profiles", sa.Column("background_story", sa.Text(), nullable=False, server_default=""))
    op.add_column("virtual_player_profiles", sa.Column("speaking_style", sa.Text(), nullable=False, server_default=""))
    op.add_column("virtual_player_profiles", sa.Column("catchphrases", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("virtual_player_profiles", sa.Column("strategy_profile", sa.String(length=40), nullable=False, server_default="balanced"))
    op.add_column("virtual_player_profiles", sa.Column("risk_tolerance", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("virtual_player_profiles", sa.Column("bluffing_tendency", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("virtual_player_profiles", sa.Column("trust_tendency", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("virtual_player_profiles", sa.Column("leadership_tendency", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("virtual_player_profiles", sa.Column("talkativeness", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("virtual_player_profiles", sa.Column("example_messages", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("virtual_player_profiles", sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("virtual_player_profiles", "favorite")
    op.drop_column("virtual_player_profiles", "example_messages")
    op.drop_column("virtual_player_profiles", "talkativeness")
    op.drop_column("virtual_player_profiles", "leadership_tendency")
    op.drop_column("virtual_player_profiles", "trust_tendency")
    op.drop_column("virtual_player_profiles", "bluffing_tendency")
    op.drop_column("virtual_player_profiles", "risk_tolerance")
    op.drop_column("virtual_player_profiles", "strategy_profile")
    op.drop_column("virtual_player_profiles", "catchphrases")
    op.drop_column("virtual_player_profiles", "speaking_style")
    op.drop_column("virtual_player_profiles", "background_story")
    op.drop_column("virtual_player_profiles", "short_description")
```

- [ ] **Step 4: Add strategy presets and schema validation**

Extend `apps/api/app/werewolf/player_presets.py` with `STRATEGY_PRESETS`, `default_strategy_text(strategy_profile: str) -> str`, and `is_valid_strategy(strategy_profile: str) -> bool` using the registry from this plan.

Extend `PlayerProfileBase`, `UpdatePlayerProfileRequest`, and `PlayerProfileResponse` with the new fields. Use these validators:

```python
def _normalize_limited_strings(value: list[str], *, max_items: int, max_length: int) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        trimmed = str(item).strip()
        if not trimmed or trimmed in seen:
            continue
        if len(trimmed) > max_length:
            raise ValueError(f"Items must be {max_length} characters or fewer")
        normalized.append(trimmed)
        seen.add(trimmed)
    if len(normalized) > max_items:
        raise ValueError(f"At most {max_items} items are allowed")
    return normalized
```

For numeric fields, use `Field(default=3, ge=1, le=5)`.

- [ ] **Step 5: Update file fallback store**

Add the same fields to `StoredPlayerProfile`, `_profile_from_payload()`, `_profile_to_payload()`, `create_profile()`, and `update_profile()`. Write `"version": 3` from `_write_profiles()`. Old profile files must receive these defaults:

```python
short_description=""
background_story=""
speaking_style=""
catchphrases=[]
strategy_profile="balanced"
risk_tolerance=3
bluffing_tendency=3
trust_tendency=3
leadership_tendency=3
talkativeness=3
example_messages=[]
favorite=False
```

- [ ] **Step 6: Verify focused backend tests pass**

Run:

```bash
cd apps/api && PYTHONPATH=. .venv/bin/python -m pytest tests/test_models.py tests/test_player_profiles_api.py -q
```

Expected: all selected tests pass.

### Task 2: Runtime Prompt Composition

**Files:**
- Create: `apps/api/app/werewolf/player_profile_prompts.py`
- Modify: `apps/api/app/werewolf/player_configs.py`
- Modify: `apps/api/tests/test_games_api.py`
- Modify: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write failing runtime snapshot test**

Add to `apps/api/tests/test_games_api.py`:

```python
def test_game_run_player_config_composes_rich_profile_prompt() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "控场样本",
            "model": "deepseek-v4-flash",
            "personality_id": "analytical",
            "personality_text": "先找矛盾，再给站边。",
            "short_description": "逻辑控场玩家",
            "speaking_style": "发言会分点列证据。",
            "catchphrases": ["我先拆一下视角"],
            "strategy_profile": "logic_leader",
            "leadership_tendency": 5,
            "talkativeness": 4,
            "example_messages": ["我觉得 2 号的视角漏掉了昨晚信息。"],
        },
    ).json()

    response = client.post(
        "/api/v1/games/runs",
        json={
            "rule_set_id": "classic_8",
            "player_configs": [{"seat": 1, "profile_id": created["id"]}],
        },
    )

    assert response.status_code == 201
    config = response.json()["player_configs"][0]
    assert config["name"] == "控场样本"
    assert "逻辑控场玩家" in config["personality"]
    assert "我先拆一下视角" in config["personality"]
    assert "领导倾向: 5/5" in config["personality"]
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd apps/api && PYTHONPATH=. .venv/bin/python -m pytest tests/test_games_api.py::test_game_run_player_config_composes_rich_profile_prompt -q
```

Expected: fail because `personality` only contains the current `personality_text`.

- [ ] **Step 3: Create prompt composer**

Create `apps/api/app/werewolf/player_profile_prompts.py`:

```python
from __future__ import annotations

from app.werewolf.player_presets import default_strategy_text


def compose_player_profile_prompt(profile: object, base_personality: str) -> str:
    sections = [base_personality.strip()]

    short_description = _profile_string(profile, "short_description")
    if short_description:
        sections.append(f"角色简介: {short_description}")

    background_story = _profile_string(profile, "background_story")
    if background_story:
        sections.append(f"背景设定: {background_story}")

    speaking_style = _profile_string(profile, "speaking_style")
    if speaking_style:
        sections.append(f"发言风格: {speaking_style}")

    strategy_profile = _profile_string(profile, "strategy_profile") or "balanced"
    sections.append(f"狼人杀策略: {default_strategy_text(strategy_profile)}")

    for label, field_name in (
        ("冒险倾向", "risk_tolerance"),
        ("伪装倾向", "bluffing_tendency"),
        ("信任倾向", "trust_tendency"),
        ("领导倾向", "leadership_tendency"),
        ("发言活跃", "talkativeness"),
    ):
        sections.append(f"{label}: {_profile_int(profile, field_name)}/5")

    catchphrases = _profile_list(profile, "catchphrases")
    if catchphrases:
        sections.append(f"常用表达: {'；'.join(catchphrases)}")

    example_messages = _profile_list(profile, "example_messages")
    if example_messages:
        sections.append(f"示例发言: {'；'.join(example_messages)}")

    return "\n".join(section for section in sections if section)


def _profile_string(profile: object, field_name: str) -> str:
    value = getattr(profile, field_name, "")
    return str(value).strip() if value is not None else ""


def _profile_int(profile: object, field_name: str) -> int:
    value = getattr(profile, field_name, 3)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 3
    return min(5, max(1, parsed))


def _profile_list(profile: object, field_name: str) -> list[str]:
    value = getattr(profile, field_name, [])
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
```

- [ ] **Step 4: Use composer in player config normalization**

In `player_config_from_profile()`, when a profile exists and no explicit `personality` override is provided, replace the base personality with `compose_player_profile_prompt(profile, profile_personality or default_personality_text(personality_id))`.

An explicit run-level `personality` or `personality_text` override continues to win and must not be expanded with profile fields.

- [ ] **Step 5: Verify runtime tests**

Run:

```bash
cd apps/api && PYTHONPATH=. .venv/bin/python -m pytest tests/test_games_api.py tests/test_werewolf_runner.py -q
```

Expected: all selected tests pass.

### Task 3: Dedicated Players Route And Query Ownership

**Files:**
- Create: `apps/web/src/pages/PlayersPage.tsx`
- Create: `apps/web/src/pages/components/PlayersWorkspace.tsx`
- Modify: `apps/web/src/routes/definitions.tsx`
- Modify: `apps/web/src/pages/GamesPage.tsx`
- Modify: `apps/web/src/pages/components/GamesWorkspace.tsx`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`
- Create: `apps/web/src/pages/PlayersPage.test.tsx`

- [ ] **Step 1: Write failing route and separation tests**

Create `apps/web/src/pages/PlayersPage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { PlayersPage } from "./PlayersPage";

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <PlayersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PlayersPage", () => {
  it("renders the dedicated virtual player workbench", async () => {
    renderPage();

    expect(
      screen.getByRole("heading", { name: "虚拟玩家工作台" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "返回大厅" }),
    ).toHaveAttribute("href", "/games");
  });
});
```

Add to `apps/web/src/pages/GamesPage.test.tsx`:

```tsx
expect(
  screen.queryByRole("heading", { name: "虚拟玩家工作台" }),
).not.toBeInTheDocument();
expect(screen.getByRole("link", { name: "玩家库" })).toHaveAttribute(
  "href",
  "/players",
);
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd apps/web && npm test -- --run src/pages/PlayersPage.test.tsx src/pages/GamesPage.test.tsx
```

Expected: fail because `PlayersPage` and `/players` route do not exist.

- [ ] **Step 3: Add page shell and route**

Create `PlayersPage.tsx` with `ArenaGlobalNav`, primary action "新建虚拟玩家", and secondary action "返回大厅" linking to `/games`.

Add route:

```tsx
{
  path: "/players",
  element: <PlayersPage />,
}
```

Modify `GamesPage.tsx` so the nav includes:

```tsx
secondaryAction={
  <>
    <ArenaNavButton to="/players">玩家库</ArenaNavButton>
    <ArenaNavButton to="/games/history">对局历史</ArenaNavButton>
  </>
}
```

- [ ] **Step 4: Move profile editor ownership to `PlayersWorkspace`**

Create `PlayersWorkspace.tsx` with the current profile queries and mutations now located in `GamesWorkspace.tsx`. Keep `GamesWorkspace` responsible only for data needed by `CreateGameRunForm`.

`GamesWorkspace` should still query player profiles and pass them to `CreateGameRunForm`, but it should not render `VirtualPlayerLibrary`.

- [ ] **Step 5: Verify route tests**

Run:

```bash
cd apps/web && npm test -- --run src/pages/PlayersPage.test.tsx src/pages/GamesPage.test.tsx
```

Expected: selected frontend tests pass.

### Task 4: Rich Editor Components

**Files:**
- Modify: `apps/web/src/features/games/types.ts`
- Create: `apps/web/src/features/games/playerStrategyOptions.ts`
- Create: `apps/web/src/features/games/profilePromptPreview.ts`
- Create: `apps/web/src/features/games/components/VirtualPlayerCardGrid.tsx`
- Create: `apps/web/src/features/games/components/VirtualPlayerEditor.tsx`
- Create: `apps/web/src/features/games/components/VirtualPlayerPreview.tsx`
- Modify: `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx`
- Modify: `apps/web/src/features/games/components/VirtualPlayerLibrary.test.tsx`
- Modify: `apps/web/src/styles/index.css`

- [ ] **Step 1: Write failing enriched editor tests**

Add to `VirtualPlayerLibrary.test.tsx`:

```tsx
it("saves rich virtual player settings from the dedicated editor", async () => {
  const user = userEvent.setup();
  const onCreateProfile = vi.fn().mockResolvedValue({});
  renderLibrary({ onCreateProfile });

  await user.click(screen.getByRole("button", { name: "新建虚拟玩家" }));
  await user.type(screen.getByLabelText("一句话简介"), "逻辑控场玩家");
  await user.type(screen.getByLabelText("背景故事"), "长期复盘高阶狼人杀对局。");
  await user.type(screen.getByLabelText("发言风格"), "分点列证据，最后给结论。");
  await user.type(screen.getByLabelText("常用表达"), "我先拆视角，票型不对劲");
  await user.selectOptions(screen.getByLabelText("策略模板"), "logic_leader");
  await user.clear(screen.getByLabelText("领导倾向"));
  await user.type(screen.getByLabelText("领导倾向"), "5");
  await user.type(screen.getByLabelText("示例发言"), "我认为 3 号视角漏了一层。");

  await user.click(screen.getByRole("button", { name: "保存虚拟玩家" }));

  expect(onCreateProfile).toHaveBeenCalledWith(
    expect.objectContaining({
      short_description: "逻辑控场玩家",
      background_story: "长期复盘高阶狼人杀对局。",
      speaking_style: "分点列证据，最后给结论。",
      catchphrases: ["我先拆视角", "票型不对劲"],
      strategy_profile: "logic_leader",
      leadership_tendency: 5,
      example_messages: ["我认为 3 号视角漏了一层。"],
    }),
  );
});
```

- [ ] **Step 2: Run editor test to verify failure**

Run:

```bash
cd apps/web && npm test -- --run src/features/games/components/VirtualPlayerLibrary.test.tsx
```

Expected: fail because the new fields are not rendered.

- [ ] **Step 3: Extend frontend types and defaults**

Add the rich fields to `VirtualPlayerProfile` and `PlayerProfileRequest`. Add `DEFAULT_PLAYER_PROFILE_DRAFT` or equivalent local helper so new profiles use:

```ts
{
  short_description: "",
  background_story: "",
  speaking_style: "",
  catchphrases: [],
  strategy_profile: "balanced",
  risk_tolerance: 3,
  bluffing_tendency: 3,
  trust_tendency: 3,
  leadership_tendency: 3,
  talkativeness: 3,
  example_messages: [],
  favorite: false,
}
```

- [ ] **Step 4: Add strategy options and prompt preview**

Create `playerStrategyOptions.ts`:

```ts
export const STRATEGY_OPTIONS = [
  { id: "balanced", label: "均衡观察", description: "稳健观察，按证据推进。" },
  { id: "logic_leader", label: "逻辑带队", description: "主动整理票型和矛盾链。" },
  { id: "shadow_wolf", label: "阴影潜伏", description: "低调隐藏动机，避免过早成为焦点。" },
  { id: "social_reader", label: "社交阅读", description: "重视情绪变化、关系线和姿态。" },
  { id: "pressure_attacker", label: "强压进攻", description: "用快速提问和压力制造信息。" },
  { id: "cautious_observer", label: "谨慎观察", description: "先收集信息，再明确判断。" },
] as const;

export const TENDENCY_LABELS = {
  risk_tolerance: "冒险倾向",
  bluffing_tendency: "伪装倾向",
  trust_tendency: "信任倾向",
  leadership_tendency: "领导倾向",
  talkativeness: "发言活跃",
} as const;
```

Create `profilePromptPreview.ts` with the same section labels as the backend composer so the preview matches runtime behavior.

- [ ] **Step 5: Split and implement editor UI**

Use `VirtualPlayerLibrary` as the orchestrator and move focused rendering into:

- `VirtualPlayerCardGrid`: list, search, filters, copy/delete/edit actions.
- `VirtualPlayerEditor`: form sections and save/cancel.
- `VirtualPlayerPreview`: image, metadata, stat bars, and prompt preview.

The editor must use compact field labels and controls:

- Text input for nickname and one-line description.
- File dropzone plus system avatar swatches for portrait.
- Select for model and strategy template.
- Textareas for background, speaking style, and examples.
- Numeric steppers or range inputs for five tendencies.
- Checkbox/toggle for favorite.

- [ ] **Step 6: Verify editor tests**

Run:

```bash
cd apps/web && npm test -- --run src/features/games/components/VirtualPlayerLibrary.test.tsx src/pages/PlayersPage.test.tsx
```

Expected: selected tests pass.

### Task 5: Library Filters And Game Lobby Integration

**Files:**
- Modify: `apps/web/src/features/games/components/VirtualPlayerCardGrid.tsx`
- Modify: `apps/web/src/features/games/components/PlayerConfigPanel.tsx`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`
- Modify: `apps/web/src/pages/PlayersPage.test.tsx`
- Modify: `apps/web/src/styles/index.css`

- [ ] **Step 1: Write failing filter and lobby tests**

Add tests proving:

- Searching by display name filters cards.
- Searching by tag filters cards.
- Model and personality filters narrow the card grid.
- Favorite filter shows only favorite profiles.
- Sorting can switch between recent update and display name.
- `/games` still renders seat assignment profile cards.
- Empty profile list in seat assignment links to `/players`.

Use these accessible names:

```tsx
screen.getByLabelText("搜索虚拟玩家")
screen.getByLabelText("模型筛选")
screen.getByLabelText("性格筛选")
screen.getByLabelText("排序方式")
screen.getByRole("button", { name: "只看收藏" })
screen.getByRole("link", { name: "去玩家库创建" })
```

- [ ] **Step 2: Run selected tests to verify failure**

Run:

```bash
cd apps/web && npm test -- --run src/pages/PlayersPage.test.tsx src/pages/GamesPage.test.tsx
```

Expected: fail on missing filter controls or missing empty-state link.

- [ ] **Step 3: Implement filters and lobby empty state**

In `VirtualPlayerCardGrid`, derive filtered profiles with:

```ts
const normalizedSearch = search.trim().toLowerCase();
const filteredProfiles = profiles
  .filter((profile) => {
    const text = [
      profile.display_name,
      profile.short_description,
      profile.model,
      profile.personality_id,
      profile.strategy_profile,
      ...profile.tags,
    ]
      .join(" ")
      .toLowerCase();

    return (
      (!favoritesOnly || profile.favorite) &&
      (!selectedModel || profile.model === selectedModel) &&
      (!selectedPersonality || profile.personality_id === selectedPersonality) &&
      (!normalizedSearch || text.includes(normalizedSearch))
    );
  })
  .toSorted((left, right) => {
    if (sortMode === "name") {
      return left.display_name.localeCompare(right.display_name, "zh-Hans-CN");
    }

    return right.updated_at.localeCompare(left.updated_at);
  });
```

In `PlayerConfigPanel`, when `profiles.length === 0`, render a compact call to action linking to `/players` instead of a dead gallery.

- [ ] **Step 4: Verify selected tests**

Run:

```bash
cd apps/web && npm test -- --run src/pages/PlayersPage.test.tsx src/pages/GamesPage.test.tsx
```

Expected: selected tests pass.

### Task 6: Visual QA And Full Verification

**Files:**
- No source files.

- [ ] **Step 1: Run backend verification**

Run:

```bash
cd apps/api && PYTHONPATH=. .venv/bin/python -m pytest tests/test_player_profiles_api.py tests/test_games_api.py tests/test_werewolf_runner.py tests/test_models.py
cd apps/api && .venv/bin/ruff check .
```

Expected: pytest exits 0 and ruff prints `All checks passed!`.

- [ ] **Step 2: Run frontend verification**

Run:

```bash
cd apps/web && npm test -- --run
cd apps/web && npm run lint
cd apps/web && npm run build
```

Expected: Vitest exits 0, ESLint exits 0, and Vite build exits 0.

- [ ] **Step 3: Browser QA**

Start the web app from the worktree:

```bash
cd apps/web && npm run dev -- --host 127.0.0.1
```

Use Browser to verify:

- `/players` opens and the first viewport shows the workbench, not a marketing page.
- New profile starts with random name and random system avatar.
- Dragging or choosing an image updates the portrait preview.
- Rich fields save and re-open with the same values.
- Search and favorite filters update the card grid.
- `/games` no longer embeds the full profile editor.
- `/games` can still assign saved profiles to seats.
- Desktop and mobile widths have no overlapping text, clipped buttons, or card-in-card nesting.

## Acceptance Criteria

- `/players` is the only place for creating and editing reusable virtual players.
- `/games` still supports choosing saved profiles into seats.
- Existing profiles created before this iteration load with safe defaults for all new fields.
- Rich profile fields are persisted in DB and file fallback mode.
- Runtime `player_configs` contain composed personality text from rich settings unless the game request explicitly overrides personality.
- The prompt preview on the frontend uses the same section labels as the backend composer.
- Full backend and frontend verification commands pass.

## Execution Choice

Plan complete and saved to `docs/superpowers/plans/2026-05-17-virtual-player-workbench.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. Inline Execution - execute tasks in this session using executing-plans, batch execution with checkpoints.
