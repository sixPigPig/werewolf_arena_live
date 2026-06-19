# Mobile Lobby Card Drawer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the mobile `/games` lobby into a gothic, seat-triggered player-card drawer while preserving the existing game creation flow.

**Architecture:** Keep the feature inside `apps/mobile-web/src/pages/GamesPage.tsx` and `apps/mobile-web/src/styles/index.css` because the current mobile app uses page-local JSX and a single stylesheet. Add small helper functions at the bottom of `GamesPage.tsx` for filtering, labels, and tags so the UI stays backed by real `VirtualPlayerProfile` and `RuleSetSummary` fields. Tests stay in `GamesPage.test.tsx` and lock the new drawer behavior before styling polish.

**Tech Stack:** React 19, React Router 7, TanStack Query 5, Vitest, Testing Library, Vite, CSS with existing px-to-rem processing.

---

## File Structure

- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx`
  - Add tests for opening the player drawer from a seat, confirming a selected player, and closing without mutating a seat.
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx`
  - Add drawer state, profile filtering, gothic lobby markup, explicit confirm behavior, and local helper functions.
- Modify: `apps/mobile-web/src/styles/index.css`
  - Add `.mobile-lobby-page` scoped styles for hero, rules, seats, settings, action bar, drawer, player cards, and mobile safe-area behavior.
- No new backend, shared package, or desktop web files.

---

### Task 1: Add Failing Drawer Interaction Tests

**Files:**
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: Enrich the test profiles**

In `beforeEach`, replace the `profiles` array with profiles that exercise favorite, strategy, and search-visible fields:

```tsx
profiles: [
  buildProfile({
    id: "profile-1",
    display_name: "阿青",
    favorite: true,
    short_description: "雾夜里的分析者",
    strategy_profile: "analysis",
    tags: ["分析"],
  }),
  buildProfile({
    id: "profile-2",
    display_name: "白石",
    short_description: "稳健守序的观察者",
    strategy_profile: "balanced",
    tags: ["均衡"],
  }),
],
```

- [ ] **Step 2: Add the drawer tests**

Append these tests inside `describe("GamesPage", () => { ... })` after the existing shortage test:

```tsx
it("opens the player card drawer from a selected seat", async () => {
  const user = userEvent.setup();
  renderGamesPage();

  await user.click(
    await screen.findByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    }),
  );

  expect(
    screen.getByRole("dialog", { name: "玩家卡牌库" }),
  ).toBeVisible();
  expect(screen.getByText("当前选择：1号座位")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
  ).toBeVisible();
});

it("confirms a player card into the active seat", async () => {
  const user = userEvent.setup();
  renderGamesPage();

  await user.click(
    await screen.findByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    }),
  );
  await user.click(
    screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
  );
  await user.click(screen.getByRole("button", { name: "确认选择" }));

  await waitFor(() => {
    expect(
      screen.queryByRole("dialog", { name: "玩家卡牌库" }),
    ).not.toBeInTheDocument();
  });
  expect(
    screen.getByRole("button", {
      name: "选择 1 号座位，当前为 阿青",
    }),
  ).toBeVisible();
});

it("closes the player card drawer without changing the seat", async () => {
  const user = userEvent.setup();
  renderGamesPage();

  await user.click(
    await screen.findByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    }),
  );
  await user.click(
    screen.getByRole("button", { name: "为 1 号座位候选 阿青" }),
  );
  await user.click(screen.getByRole("button", { name: "关闭玩家卡牌库" }));

  await waitFor(() => {
    expect(
      screen.queryByRole("dialog", { name: "玩家卡牌库" }),
    ).not.toBeInTheDocument();
  });
  expect(
    screen.getByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    }),
  ).toBeVisible();
});
```

- [ ] **Step 3: Run the focused tests and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/GamesPage.test.tsx
```

Expected: FAIL because the current seat buttons are named only by visible text and no `role="dialog"` player-card drawer exists.

- [ ] **Step 4: Commit after this task only if the failing tests are added intentionally**

Run:

```bash
git add apps/mobile-web/src/pages/GamesPage.test.tsx
git commit -m "test: cover mobile lobby card drawer"
```

Expected: Commit succeeds with only the test file staged.

---

### Task 2: Add Drawer State, Filtering, and Helper Functions

**Files:**
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx`

- [ ] **Step 1: Import the profile type**

Change the game-client import so it includes `VirtualPlayerProfile`:

```tsx
import {
  createGameRun,
  hasPlayerConfig,
  listPlayerProfiles,
  listRuleSets,
  randomFillEmptySeats,
  removeInvalidProfileRefs,
  resizeLineupForPlayerCount,
  type PlayerConfig,
  type RuleSetSummary,
  type VirtualPlayerProfile,
} from "@werewolf-arena/game-client";
```

- [ ] **Step 2: Add local drawer and filter state**

After `const [activeSeat, setActiveSeat] = useState(1);`, add:

```tsx
const [isProfileDrawerOpen, setIsProfileDrawerOpen] = useState(false);
const [pendingProfileId, setPendingProfileId] = useState<string | null>(null);
const [profileSearch, setProfileSearch] = useState("");
const [favoriteFilter, setFavoriteFilter] = useState<"all" | "favorite">("all");
const [profileStrategyFilter, setProfileStrategyFilter] = useState("all");
```

- [ ] **Step 3: Add derived values**

After `const safeActiveSeat = clampSeat(activeSeat, playerCount);`, add:

```tsx
const activeSeatProfile = selectedProfilesBySeat.get(safeActiveSeat) ?? null;
const pendingProfile =
  profiles.find((profile) => profile.id === pendingProfileId) ?? null;
const strategyFilterOptions = useMemo(
  () => getStrategyFilterOptions(profiles),
  [profiles],
);
const filteredProfiles = useMemo(
  () =>
    filterProfiles(profiles, {
      favoriteFilter,
      search: profileSearch,
      strategy: profileStrategyFilter,
    }),
  [favoriteFilter, profileSearch, profileStrategyFilter, profiles],
);
```

- [ ] **Step 4: Add drawer handlers**

After `assignProfileToActiveSeat`, add:

```tsx
function openProfileDrawer(seat: number) {
  const profile = selectedProfilesBySeat.get(seat) ?? null;
  setActiveSeat(seat);
  setPendingProfileId(profile?.id ?? null);
  setProfileSearch("");
  setFavoriteFilter("all");
  setProfileStrategyFilter("all");
  setValidationError(null);
  setShortage(false);
  setIsProfileDrawerOpen(true);
}

function closeProfileDrawer() {
  setIsProfileDrawerOpen(false);
  setPendingProfileId(null);
}

function confirmPendingProfile() {
  if (!pendingProfileId) {
    return;
  }
  assignProfileToActiveSeat(pendingProfileId);
  setIsProfileDrawerOpen(false);
  setPendingProfileId(null);
}
```

- [ ] **Step 5: Add helper functions at the bottom of the file**

After `clampSeat`, add:

```tsx
type ProfileFilters = {
  favoriteFilter: "all" | "favorite";
  search: string;
  strategy: string;
};

function filterProfiles(
  profiles: VirtualPlayerProfile[],
  filters: ProfileFilters,
) {
  const search = filters.search.trim().toLowerCase();

  return profiles.filter((profile) => {
    if (filters.favoriteFilter === "favorite" && !profile.favorite) {
      return false;
    }

    if (
      filters.strategy !== "all" &&
      profile.strategy_profile !== filters.strategy
    ) {
      return false;
    }

    if (!search) {
      return true;
    }

    return profileMatchesSearch(profile, search);
  });
}

function profileMatchesSearch(profile: VirtualPlayerProfile, search: string) {
  return [
    profile.display_name,
    profile.model,
    profile.personality_id,
    profile.personality_text,
    profile.short_description,
    profile.strategy_profile,
    ...profile.tags,
  ]
    .filter(Boolean)
    .some((value) => value.toLowerCase().includes(search));
}

function getStrategyFilterOptions(profiles: VirtualPlayerProfile[]) {
  return [...new Set(profiles.map((profile) => profile.strategy_profile))]
    .filter(Boolean)
    .sort((left, right) => left.localeCompare(right));
}

function getRuleTags(ruleSet: RuleSetSummary) {
  const tags = [
    ...(ruleSet.rule_tags ?? []),
    ruleSet.complexity,
    ruleSet.estimated_duration,
  ].filter((tag): tag is string => Boolean(tag));

  return tags.slice(0, 3);
}

function formatStrategyLabel(strategy: string) {
  const strategyLabels: Record<string, string> = {
    analysis: "分析型",
    balanced: "均衡型",
    deceptive: "策略型",
    defensive: "防御型",
    aggressive: "进攻型",
  };

  return strategyLabels[strategy] ?? strategy;
}

function getProfileDescription(profile: VirtualPlayerProfile) {
  return (
    profile.short_description ||
    profile.personality_text ||
    profile.model ||
    "暗夜牌局候选人"
  );
}
```

- [ ] **Step 6: Run typecheck through the focused test command**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/GamesPage.test.tsx
```

Expected: The test file still fails on missing drawer markup, but TypeScript parsing succeeds. If the command fails with a TypeScript error, fix the type name or helper signature before continuing.

---

### Task 3: Replace the GamesPage Markup with Gothic Lobby and Drawer UI

**Files:**
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx`

- [ ] **Step 1: Replace the `<main>` class and hero**

Change:

```tsx
<main className="mobile-page" data-testid="mobile-games-page">
  <header className="mobile-page-section">
    <h1>移动大厅</h1>
    <p>选择规则和虚拟玩家，发起一局新的狼人杀对局。</p>
  </header>
```

to:

```tsx
<main className="mobile-page mobile-lobby-page" data-testid="mobile-games-page">
  <header className="mobile-lobby-hero">
    <div className="mobile-lobby-crest" aria-hidden="true">
      狼
    </div>
    <div className="mobile-lobby-hero-copy">
      <span>公平 · 推理 · 社交的暗夜决策</span>
      <h1>狼人杀对局大厅</h1>
      <p>选择规则，点亮座位，从卡牌库召集你的暗夜阵容。</p>
    </div>
  </header>
```

- [ ] **Step 2: Replace the rule section**

Replace the current rule section with:

```tsx
<section aria-labelledby="mobile-rule-title" className="mobile-lobby-section">
  <div className="mobile-lobby-section-heading">
    <h2 id="mobile-rule-title">规则选择</h2>
    {selectedRuleSet ? (
      <span>{selectedRuleSet.player_count} 人局</span>
    ) : null}
  </div>
  {ruleSetsQuery.isError ? <p>规则加载失败</p> : null}
  <div className="mobile-lobby-rule-scroll">
    {ruleSets.map((ruleSet) => {
      const isSelected = selectedRuleSet?.id === ruleSet.id;
      const ruleTags = getRuleTags(ruleSet);

      return (
        <label
          className={[
            "mobile-lobby-rule-card",
            isSelected ? "mobile-lobby-rule-card-active" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          key={ruleSet.id}
        >
          <input
            checked={isSelected}
            name="mobile-rule-set"
            onChange={() => handleRuleSetChange(ruleSet.id)}
            type="radio"
            value={ruleSet.id}
          />
          <span className="mobile-lobby-rule-emblem" aria-hidden="true">
            {isSelected ? "✓" : "✦"}
          </span>
          <strong>{ruleSet.name}</strong>
          <span>{ruleSet.role_summary ?? `${ruleSet.player_count} 人局`}</span>
          {ruleTags.length > 0 ? (
            <span className="mobile-lobby-rule-tags">
              {ruleTags.map((tag) => (
                <em key={tag}>{tag}</em>
              ))}
            </span>
          ) : null}
        </label>
      );
    })}
    {isLoading ? <p>加载中</p> : null}
  </div>
</section>
```

- [ ] **Step 3: Replace the selected-rule body**

Replace the current `selectedRuleSet ? (...) : null` fragment with:

```tsx
{selectedRuleSet ? (
  <section aria-labelledby="mobile-seat-title" className="mobile-lobby-section">
    <div className="mobile-lobby-section-heading">
      <h2 id="mobile-seat-title">组建阵容</h2>
      <span>
        {selectedRuleSet.name} · {playerCount} 个座位
      </span>
    </div>
    <div className="mobile-lobby-seat-grid">
      {Array.from({ length: playerCount }, (_, index) => index + 1).map(
        (seat) => {
          const profile = selectedProfilesBySeat.get(seat);
          const isActive = safeActiveSeat === seat;

          return (
            <button
              aria-label={`选择 ${seat} 号座位，当前为 ${
                profile?.display_name ?? "待选择"
              }`}
              aria-pressed={isActive}
              className={[
                "mobile-lobby-seat-card",
                isActive ? "mobile-lobby-seat-card-active" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              key={seat}
              onClick={() => openProfileDrawer(seat)}
              type="button"
            >
              <span className="mobile-lobby-seat-avatar">
                {profile?.avatar_image_url ? (
                  <img alt="" src={profile.avatar_image_url} />
                ) : (
                  <span aria-hidden="true" />
                )}
              </span>
              <span className="mobile-lobby-seat-label">{seat}号座位</span>
              <strong>{profile?.display_name ?? "待选择"}</strong>
            </button>
          );
        },
      )}
    </div>
    {playerProfilesQuery.isError ? (
      <p className="mobile-lobby-inline-error">玩家库加载失败</p>
    ) : null}
  </section>
) : null}
```

- [ ] **Step 4: Replace the settings section**

Replace the current settings section with:

```tsx
<section aria-labelledby="mobile-create-title" className="mobile-lobby-section">
  <div className="mobile-lobby-section-heading">
    <h2 id="mobile-create-title">填充设置</h2>
    {activeSeatProfile ? <span>{activeSeatProfile.display_name}</span> : null}
  </div>
  <div className="mobile-lobby-settings-grid">
    <label className="mobile-lobby-field">
      <span>种子</span>
      <input
        inputMode="numeric"
        onChange={(event) => setSeed(event.target.value)}
        placeholder="随机"
        type="number"
        value={seed}
      />
    </label>
    <label className="mobile-lobby-field">
      <span>最大轮数</span>
      <input
        inputMode="numeric"
        max={20}
        min={1}
        onChange={(event) => {
          setMaxRounds(event.target.value);
          setValidationError(null);
        }}
        type="number"
        value={maxRounds}
      />
    </label>
  </div>
</section>
```

- [ ] **Step 5: Replace the action bar**

Replace the current action bar with:

```tsx
<div className="mobile-action-bar mobile-lobby-action-bar">
  <button
    className="mobile-button"
    disabled={!selectedRuleSet}
    onClick={() => fillEmptySeats()}
    type="button"
  >
    随机补齐
  </button>
  <button
    className="mobile-button"
    disabled={!selectedRuleSet}
    onClick={() => fillEmptySeats({ favoritesOnly: true })}
    type="button"
  >
    收藏补齐
  </button>
  <button
    className="mobile-button"
    onClick={() => {
      setPlayerConfigs([]);
      setShortage(false);
      setValidationError(null);
    }}
    type="button"
  >
    清空席位
  </button>
  <button
    className="mobile-button mobile-button-primary"
    disabled={isSubmitDisabled}
    onClick={handleSubmit}
    type="button"
  >
    {createGameRunMutation.isPending ? "发起中" : "发起对局"}
  </button>
</div>
```

- [ ] **Step 6: Add the drawer before `</main>`**

Insert this block immediately before the closing `</main>` tag:

```tsx
{isProfileDrawerOpen ? (
  <div className="mobile-profile-drawer-layer">
    <button
      aria-label="关闭玩家卡牌库"
      className="mobile-profile-drawer-backdrop"
      onClick={closeProfileDrawer}
      type="button"
    />
    <section
      aria-labelledby="mobile-profile-drawer-title"
      aria-modal="true"
      className="mobile-profile-drawer"
      role="dialog"
    >
      <div className="mobile-profile-drawer-handle" aria-hidden="true" />
      <div className="mobile-profile-drawer-heading">
        <div>
          <h2 id="mobile-profile-drawer-title">玩家卡牌库</h2>
          <p>当前选择：{safeActiveSeat}号座位</p>
        </div>
        <button
          aria-label="关闭玩家卡牌库"
          className="mobile-profile-drawer-close"
          onClick={closeProfileDrawer}
          type="button"
        >
          ×
        </button>
      </div>

      <div className="mobile-profile-drawer-filters">
        <label className="mobile-profile-search">
          <span>搜索玩家</span>
          <input
            onChange={(event) => setProfileSearch(event.target.value)}
            placeholder="搜索名称、标签、模型"
            type="search"
            value={profileSearch}
          />
        </label>
        <label className="mobile-profile-select">
          <span>收藏</span>
          <select
            aria-label="收藏筛选"
            onChange={(event) =>
              setFavoriteFilter(event.target.value as "all" | "favorite")
            }
            value={favoriteFilter}
          >
            <option value="all">全部玩家</option>
            <option value="favorite">只看收藏</option>
          </select>
        </label>
        <label className="mobile-profile-select">
          <span>策略</span>
          <select
            aria-label="策略筛选"
            onChange={(event) => setProfileStrategyFilter(event.target.value)}
            value={profileStrategyFilter}
          >
            <option value="all">全部策略</option>
            {strategyFilterOptions.map((strategy) => (
              <option key={strategy} value={strategy}>
                {formatStrategyLabel(strategy)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {playerProfilesQuery.isError ? (
        <p className="mobile-lobby-inline-error">玩家库加载失败</p>
      ) : null}
      <div className="mobile-profile-card-grid">
        {filteredProfiles.map((profile) => {
          const isPending = pendingProfileId === profile.id;

          return (
            <button
              aria-label={`为 ${safeActiveSeat} 号座位候选 ${profile.display_name}`}
              className={[
                "mobile-profile-card-choice",
                isPending ? "mobile-profile-card-choice-active" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              key={profile.id}
              onClick={() => setPendingProfileId(profile.id)}
              type="button"
            >
              <span className="mobile-profile-card-image">
                {profile.avatar_image_url ? (
                  <img alt="" src={profile.avatar_image_url} />
                ) : (
                  <span aria-hidden="true" />
                )}
                {profile.favorite ? (
                  <em aria-label="已收藏" className="mobile-profile-card-star">
                    ★
                  </em>
                ) : null}
                {isPending ? (
                  <em aria-hidden="true" className="mobile-profile-card-check">
                    ✓
                  </em>
                ) : null}
              </span>
              <strong>{profile.display_name}</strong>
              <span>{formatStrategyLabel(profile.strategy_profile)}</span>
              <small>{getProfileDescription(profile)}</small>
            </button>
          );
        })}
      </div>
      {!playerProfilesQuery.isPending && filteredProfiles.length === 0 ? (
        <p className="mobile-profile-empty">没有匹配玩家</p>
      ) : null}
      <div className="mobile-profile-drawer-footer">
        <span>{pendingProfile ? pendingProfile.display_name : "请选择一张玩家卡"}</span>
        <button
          className="mobile-button mobile-button-primary"
          disabled={!pendingProfileId}
          onClick={confirmPendingProfile}
          type="button"
        >
          确认选择
        </button>
      </div>
    </section>
  </div>
) : null}
```

- [ ] **Step 7: Run the focused tests and verify logic passes or only styling-independent queries remain**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/GamesPage.test.tsx
```

Expected: PASS. If it fails, fix the accessible names or dialog structure before moving to CSS.

- [ ] **Step 8: Commit the JSX and behavior**

Run:

```bash
git add apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/pages/GamesPage.test.tsx
git commit -m "feat: add mobile lobby card drawer"
```

Expected: Commit succeeds with the page and test files.

---

### Task 4: Add Scoped Gothic Mobile Lobby Styles

**Files:**
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Append the scoped lobby CSS**

Append this block after the existing `.mobile-status-banner` rules and before `.mobile-player-list`:

```css
.mobile-lobby-page {
  position: relative;
  isolation: isolate;
  min-height: 100%;
  padding: 18px 12px 178px;
  overflow: hidden;
  background:
    radial-gradient(circle at 84% 42px, rgb(244 238 219 / 82%) 0 18px, transparent 19px),
    radial-gradient(circle at 50% 124px, rgb(26 65 104 / 38%), transparent 112px),
    linear-gradient(180deg, #03070d 0%, #071018 40%, #030609 100%);
}

.mobile-lobby-page::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: -2;
  background:
    linear-gradient(180deg, transparent 0 88px, rgb(0 0 0 / 36%) 89px),
    radial-gradient(circle at 46% 104px, rgb(3 12 24 / 0%) 0 34px, rgb(2 5 9 / 74%) 92px);
}

.mobile-lobby-page::after {
  content: "";
  position: absolute;
  inset: 70px 32px auto;
  z-index: -1;
  height: 86px;
  opacity: 0.72;
  background:
    linear-gradient(90deg, transparent, rgb(20 32 46 / 75%), transparent),
    linear-gradient(135deg, transparent 0 44%, rgb(4 8 14) 45% 55%, transparent 56%),
    linear-gradient(45deg, transparent 0 44%, rgb(4 8 14) 45% 55%, transparent 56%);
  clip-path: polygon(0 100%, 12% 64%, 20% 100%, 30% 40%, 41% 100%, 50% 12%, 60% 100%, 71% 44%, 81% 100%, 90% 62%, 100% 100%);
}

.mobile-lobby-hero {
  display: flex;
  min-height: 104px;
  align-items: start;
  gap: 12px;
  padding: 8px 2px 0;
}

.mobile-lobby-crest {
  display: inline-flex;
  width: 54px;
  height: 54px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border: 1px solid rgb(215 184 121 / 62%);
  border-radius: 999px;
  background:
    radial-gradient(circle, rgb(227 213 180 / 22%), transparent 58%),
    rgb(3 7 12 / 76%);
  color: #ead3a0;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 22px;
  font-weight: 700;
  box-shadow: 0 0 26px rgb(218 163 54 / 16%);
}

.mobile-lobby-hero-copy {
  display: grid;
  min-width: 0;
  gap: 6px;
}

.mobile-lobby-hero-copy span {
  color: rgb(235 214 173 / 72%);
  font-size: 11px;
  letter-spacing: 2px;
}

.mobile-lobby-hero-copy h1 {
  color: #ead8b7;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 29px;
  letter-spacing: 0;
  line-height: 1.08;
  text-shadow: 0 0 18px rgb(221 167 67 / 20%);
}

.mobile-lobby-hero-copy p {
  max-width: 260px;
  color: rgb(217 205 185 / 76%);
  font-size: 13px;
  line-height: 1.45;
}

.mobile-lobby-section {
  display: grid;
  gap: 12px;
  margin-bottom: 18px;
}

.mobile-lobby-section-heading {
  display: flex;
  min-width: 0;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.mobile-lobby-section-heading h2 {
  color: #f4d28e;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 18px;
}

.mobile-lobby-section-heading span {
  overflow: hidden;
  color: rgb(223 209 184 / 74%);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-lobby-rule-scroll {
  display: grid;
  grid-auto-columns: minmax(210px, 76%);
  grid-auto-flow: column;
  gap: 10px;
  margin-inline: -12px;
  overflow-x: auto;
  padding: 0 12px 6px;
  scroll-snap-type: x mandatory;
}

.mobile-lobby-rule-card {
  position: relative;
  display: grid;
  min-height: 154px;
  box-sizing: border-box;
  align-content: end;
  gap: 7px;
  padding: 16px 14px 14px;
  overflow: hidden;
  border: 1px solid rgb(165 141 103 / 54%);
  border-radius: 6px;
  background:
    radial-gradient(circle at 50% 34%, rgb(219 193 131 / 20%), transparent 34px),
    linear-gradient(180deg, rgb(21 25 32 / 88%), rgb(5 8 12 / 96%));
  color: #ead8b7;
  scroll-snap-align: start;
  box-shadow: inset 0 0 24px rgb(255 255 255 / 4%);
}

.mobile-lobby-rule-card input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

.mobile-lobby-rule-card-active {
  border-color: rgb(247 185 52 / 92%);
  box-shadow:
    0 0 18px rgb(233 156 28 / 20%),
    inset 0 0 30px rgb(236 172 52 / 14%);
}

.mobile-lobby-rule-emblem {
  position: absolute;
  top: 10px;
  right: 10px;
  display: inline-flex;
  width: 28px;
  height: 28px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgb(247 185 52 / 72%);
  border-radius: 999px;
  color: #f8d889;
  font-size: 15px;
}

.mobile-lobby-rule-card strong {
  color: #f0d39a;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 23px;
  line-height: 1.1;
}

.mobile-lobby-rule-card > span:not(.mobile-lobby-rule-emblem):not(.mobile-lobby-rule-tags) {
  color: rgb(234 218 190 / 78%);
  font-size: 13px;
  line-height: 1.35;
}

.mobile-lobby-rule-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mobile-lobby-rule-tags em {
  border: 1px solid rgb(245 212 139 / 30%);
  border-radius: 4px;
  padding: 4px 7px;
  background: rgb(245 212 139 / 8%);
  color: #f5d48b;
  font-size: 11px;
  font-style: normal;
  line-height: 1;
}

.mobile-lobby-seat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.mobile-lobby-seat-card {
  display: grid;
  min-width: 0;
  min-height: 92px;
  box-sizing: border-box;
  justify-items: center;
  gap: 5px;
  padding: 8px 5px;
  border: 1px solid rgb(170 150 111 / 50%);
  border-radius: 5px;
  background: rgb(3 8 12 / 78%);
  color: #d9c8a9;
  text-align: center;
}

.mobile-lobby-seat-card-active {
  border-color: rgb(247 185 52 / 92%);
  background: rgb(68 46 12 / 28%);
  box-shadow: inset 0 0 18px rgb(247 185 52 / 12%);
}

.mobile-lobby-seat-avatar {
  display: inline-flex;
  width: 34px;
  height: 34px;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 1px solid rgb(214 184 121 / 42%);
  border-radius: 999px;
  background: radial-gradient(circle, rgb(245 212 139 / 20%), rgb(9 13 18 / 92%));
}

.mobile-lobby-seat-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.mobile-lobby-seat-avatar > span {
  width: 17px;
  height: 17px;
  border-radius: 999px;
  background: rgb(245 212 139 / 18%);
}

.mobile-lobby-seat-label,
.mobile-lobby-seat-card strong {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-lobby-seat-label {
  color: rgb(222 207 181 / 72%);
  font-size: 11px;
}

.mobile-lobby-seat-card strong {
  color: #f2dfbd;
  font-size: 12px;
  line-height: 1.2;
}

.mobile-lobby-inline-error {
  color: #fecaca;
  font-size: 13px;
  line-height: 1.4;
}

.mobile-lobby-settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.mobile-lobby-field {
  display: grid;
  gap: 7px;
  padding: 10px;
  border: 1px solid rgb(170 150 111 / 42%);
  border-radius: 5px;
  background: rgb(4 9 13 / 74%);
}

.mobile-lobby-field span {
  color: rgb(222 207 181 / 72%);
  font-size: 12px;
}

.mobile-lobby-field input {
  min-width: 0;
  height: 40px;
  box-sizing: border-box;
  border: 1px solid rgb(244 232 210 / 14%);
  border-radius: 5px;
  padding: 0 10px;
  background: rgb(2 5 8 / 88%);
  color: #f4e8d2;
}

.mobile-lobby-action-bar {
  border-color: rgb(180 150 92 / 54%);
  border-radius: 6px;
  background: rgb(5 8 11 / 94%);
}

.mobile-profile-drawer-layer {
  position: fixed;
  inset: 0;
  z-index: 30;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.mobile-profile-drawer-backdrop {
  position: absolute;
  inset: 0;
  border: 0;
  background: rgb(0 0 0 / 62%);
}

.mobile-profile-drawer {
  position: relative;
  display: grid;
  width: min(100%, 480px);
  max-height: calc(100svh - 74px);
  box-sizing: border-box;
  gap: 12px;
  overflow-y: auto;
  padding: 10px 14px calc(88px + env(safe-area-inset-bottom));
  border: 1px solid rgb(201 160 87 / 82%);
  border-radius: 24px 24px 0 0;
  background:
    linear-gradient(180deg, rgb(19 19 18 / 98%), rgb(5 8 11 / 99%)),
    radial-gradient(circle at 50% 0, rgb(229 171 62 / 18%), transparent 100px);
  color: #f4e8d2;
  box-shadow: 0 -18px 48px rgb(0 0 0 / 58%);
}

.mobile-profile-drawer-handle {
  justify-self: center;
  width: 58px;
  height: 5px;
  border-radius: 999px;
  background: rgb(244 232 210 / 34%);
}

.mobile-profile-drawer-heading {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 12px;
}

.mobile-profile-drawer-heading h2 {
  color: #e8c886;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 30px;
  text-align: center;
}

.mobile-profile-drawer-heading p {
  color: rgb(222 207 181 / 74%);
  font-size: 13px;
  line-height: 1.4;
}

.mobile-profile-drawer-close {
  display: inline-flex;
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border: 1px solid rgb(201 160 87 / 64%);
  border-radius: 999px;
  background: rgb(6 9 12 / 72%);
  color: #e8c886;
  font-size: 26px;
  line-height: 1;
}

.mobile-profile-drawer-filters {
  display: grid;
  grid-template-columns: 1.35fr 1fr 1fr;
  gap: 8px;
}

.mobile-profile-search,
.mobile-profile-select {
  display: grid;
  min-width: 0;
  gap: 5px;
}

.mobile-profile-search span,
.mobile-profile-select span {
  color: rgb(222 207 181 / 70%);
  font-size: 11px;
}

.mobile-profile-search input,
.mobile-profile-select select {
  min-width: 0;
  height: 42px;
  box-sizing: border-box;
  border: 1px solid rgb(244 232 210 / 16%);
  border-radius: 5px;
  padding: 0 9px;
  background: rgb(3 7 10 / 88%);
  color: #f4e8d2;
}

.mobile-profile-card-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.mobile-profile-card-choice {
  position: relative;
  display: grid;
  min-width: 0;
  gap: 7px;
  box-sizing: border-box;
  padding: 8px;
  border: 1px solid rgb(160 139 103 / 50%);
  border-radius: 5px;
  background: rgb(4 8 12 / 82%);
  color: #f4e8d2;
  text-align: left;
}

.mobile-profile-card-choice-active {
  border-color: rgb(247 185 52 / 92%);
  box-shadow: 0 0 18px rgb(233 156 28 / 18%);
}

.mobile-profile-card-image {
  position: relative;
  display: block;
  aspect-ratio: 4 / 5;
  overflow: hidden;
  border: 1px solid rgb(244 232 210 / 14%);
  border-radius: 4px;
  background:
    radial-gradient(circle at 50% 30%, rgb(73 99 132 / 64%), transparent 48px),
    linear-gradient(180deg, #101a25, #030609);
}

.mobile-profile-card-image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.mobile-profile-card-star,
.mobile-profile-card-check {
  position: absolute;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  font-style: normal;
}

.mobile-profile-card-star {
  top: 6px;
  right: 6px;
  width: 24px;
  height: 24px;
  background: rgb(5 8 11 / 72%);
  color: #f5d48b;
}

.mobile-profile-card-check {
  right: 8px;
  bottom: 8px;
  width: 32px;
  height: 32px;
  background: rgb(144 91 13 / 88%);
  color: #ffe3a1;
  font-size: 20px;
}

.mobile-profile-card-choice strong,
.mobile-profile-card-choice span,
.mobile-profile-card-choice small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-profile-card-choice strong {
  color: #f0d39a;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 18px;
  line-height: 1.15;
}

.mobile-profile-card-choice span {
  color: #c9d8c7;
  font-size: 12px;
}

.mobile-profile-card-choice small {
  color: rgb(222 207 181 / 72%);
  font-size: 12px;
}

.mobile-profile-empty {
  color: rgb(222 207 181 / 74%);
  font-size: 13px;
  text-align: center;
}

.mobile-profile-drawer-footer {
  position: sticky;
  right: 0;
  bottom: 0;
  left: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(128px, auto);
  gap: 10px;
  align-items: center;
  margin: 0 -4px calc(-74px - env(safe-area-inset-bottom));
  padding: 10px 4px calc(12px + env(safe-area-inset-bottom));
  background: linear-gradient(180deg, rgb(5 8 11 / 0%), rgb(5 8 11) 24%);
}

.mobile-profile-drawer-footer span {
  min-width: 0;
  overflow: hidden;
  color: rgb(222 207 181 / 74%);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

- [ ] **Step 2: Add a narrow-screen seat fallback**

Append this media query immediately after the CSS above:

```css
@media (max-width: 360px) {
  .mobile-lobby-seat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .mobile-profile-drawer-filters {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 3: Run focused tests**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/GamesPage.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Run mobile build**

Run:

```bash
pnpm --dir apps/mobile-web build
```

Expected: PASS with TypeScript and Vite build output.

- [ ] **Step 5: Commit styling**

Run:

```bash
git add apps/mobile-web/src/styles/index.css
git commit -m "style: restyle mobile lobby"
```

Expected: Commit succeeds with only the stylesheet staged.

---

### Task 5: Visual QA and Final Verification

**Files:**
- No code changes expected unless QA reveals a defect.

- [ ] **Step 1: Start the mobile dev server**

Run:

```bash
pnpm --dir apps/mobile-web dev
```

Expected: Vite starts on `http://127.0.0.1:5174`. Keep this session running until QA is complete.

- [ ] **Step 2: Open `/games` in a 375px-wide browser viewport**

Use the in-app browser or Playwright to inspect:

```text
http://127.0.0.1:5174/games
```

Expected:
- The first viewport shows the gothic title, moon/night atmosphere, rule cards, and the start of the seat grid.
- Text inside rule cards, seat cards, inputs, and buttons does not overflow.
- The bottom action bar stays above the tab bar.

- [ ] **Step 3: Inspect the drawer interaction**

In the browser:

1. Click `1号座位`.
2. Confirm the `玩家卡牌库` drawer opens from the bottom.
3. Click `阿青`.
4. Click `确认选择`.

Expected:
- The drawer does not cover the whole app awkwardly; it sits above the bottom safe area.
- The selected card shows a gold active state before confirmation.
- After confirmation, `1号座位` shows `阿青`.

- [ ] **Step 4: Run all mobile tests**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run
```

Expected: PASS.

- [ ] **Step 5: Run final status check**

Run:

```bash
git status --short
```

Expected: clean working tree, unless QA required a fix. If a fix was needed, run focused tests and commit it with:

```bash
git add apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/styles/index.css apps/mobile-web/src/pages/GamesPage.test.tsx
git commit -m "fix: polish mobile lobby drawer"
```

---

## Self-Review

- Spec coverage:
  - Dark gothic mobile lobby: Task 4.
  - Seat-triggered drawer: Tasks 1, 2, 3.
  - Confirm-before-write behavior: Tasks 1 and 3.
  - Real profile search/filter fields: Tasks 2 and 3.
  - Existing create flow preserved: Tasks 1 and 5.
  - Accessibility names and dialog semantics: Tasks 1 and 3.
- Placeholder scan: No placeholder red flags or undefined future work remain.
- Type consistency: The plan uses real `RuleSetSummary`, `VirtualPlayerProfile`, and `PlayerConfig` fields from `packages/game-client/src/types.ts`.
