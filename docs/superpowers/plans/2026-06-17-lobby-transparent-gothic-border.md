# Lobby Transparent Gothic Border Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable transparent gothic border frame from the supplied artwork and apply it to the four marked lobby workbench regions.

**Architecture:** Add a focused `GothicBorderFrame` UI component that renders an inert eight-piece decoration layer and a content layer. The generated PNG slices live under `apps/web/src/assets/lobby-border-frame`, while existing lobby components keep their business class names so layout, scrolling, and behavior stay stable.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, CSS, PNG assets generated from the user-supplied image with Python/Pillow.

---

## File Structure

- Create: `apps/web/src/components/ui/GothicBorderFrame.tsx` for the reusable frame component.
- Create: `apps/web/src/components/ui/GothicBorderFrame.test.tsx` for component structure and CSS asset tests.
- Modify: `apps/web/src/components/ui/index.tsx` to export `GothicBorderFrame`.
- Modify: `apps/web/src/styles/index.css` to define frame CSS and adjust lobby layout selectors for the new content layer.
- Create: `apps/web/src/assets/lobby-border-frame/*.png` for transparent source and frame slices.
- Modify: `apps/web/src/features/games/components/LobbyRuleSelector.tsx` to wrap the rule column.
- Modify: `apps/web/src/features/games/components/LobbyLineupWorkbench.tsx` to wrap lineup and player columns.
- Modify: `apps/web/src/features/games/components/LobbyActionBar.tsx` to wrap the bottom action bar.
- Modify: `apps/web/src/pages/GamesPage.test.tsx` to assert all four marked regions use the new frame.

### Task 1: Frame Component Tests

**Files:**
- Create: `apps/web/src/components/ui/GothicBorderFrame.test.tsx`

- [ ] **Step 1: Write the failing component test**

```tsx
import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { GothicBorderFrame } from "./GothicBorderFrame";

describe("GothicBorderFrame", () => {
  it("renders a transparent eight-piece gothic border around a content layer", () => {
    render(
      <GothicBorderFrame
        aria-label="大厅边框"
        className="custom-frame"
        contentClassName="custom-content"
      >
        <h2>规则选择</h2>
      </GothicBorderFrame>,
    );

    const frame = screen.getByLabelText("大厅边框");

    expect(frame).toHaveClass(
      "gothic-border-frame",
      "gothic-border-frame-default",
      "custom-frame",
    );
    expect(frame.querySelectorAll(".gothic-border-frame-piece")).toHaveLength(8);
    expect(frame.querySelector(".gothic-border-frame-decoration")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(screen.getByText("规则选择").parentElement).toHaveClass(
      "gothic-border-frame-content",
      "custom-content",
    );
  });

  it("supports compact density for short action bars", () => {
    render(
      <GothicBorderFrame aria-label="底部操作条" as="footer" density="compact">
        操作
      </GothicBorderFrame>,
    );

    expect(screen.getByLabelText("底部操作条").tagName).toBe("FOOTER");
    expect(screen.getByLabelText("底部操作条")).toHaveClass(
      "gothic-border-frame-compact",
    );
  });

  it("uses sliced lobby border assets without stretching the source image", () => {
    const css = readFileSync("src/styles/index.css", "utf8");

    expect(css).toContain('url("../assets/lobby-border-frame/frame-corner-tl.png")');
    expect(css).toContain('url("../assets/lobby-border-frame/frame-edge-top.png")');
    expect(css).toContain('url("../assets/lobby-border-frame/frame-edge-left.png")');
    expect(css).toContain("background-repeat: repeat-x");
    expect(css).toContain("background-repeat: repeat-y");
    expect(css).not.toContain("source-transparent.png\") 0 0 / 100% 100%");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir apps/web test -- --run src/components/ui/GothicBorderFrame.test.tsx`

Expected: FAIL because `./GothicBorderFrame` does not exist.

### Task 2: Lobby Integration Test

**Files:**
- Modify: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: Add failing assertions to the existing lobby workbench test**

Add assertions after each target element is found:

```tsx
expect(ruleColumn).toHaveClass("gothic-border-frame");
expect(ruleColumn.querySelector(".gothic-border-frame-content")).toBeInTheDocument();

expect(lineupColumn).toHaveClass("gothic-border-frame");
expect(lineupColumn.querySelector(".gothic-border-frame-content")).toBeInTheDocument();

expect(playerColumn).toHaveClass("gothic-border-frame");
expect(playerColumn.querySelector(".gothic-border-frame-content")).toBeInTheDocument();

expect(actionBar).toHaveClass("gothic-border-frame", "gothic-border-frame-compact");
expect(actionBar.querySelector(".gothic-border-frame-content")).toBeInTheDocument();
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx -t "renders the three-column lobby workbench"`

Expected: FAIL because the four lobby regions do not yet have `gothic-border-frame`.

### Task 3: Generate Transparent Frame Assets

**Files:**
- Create: `apps/web/src/assets/lobby-border-frame/source-transparent.png`
- Create: `apps/web/src/assets/lobby-border-frame/frame-corner-tl.png`
- Create: `apps/web/src/assets/lobby-border-frame/frame-corner-tr.png`
- Create: `apps/web/src/assets/lobby-border-frame/frame-corner-br.png`
- Create: `apps/web/src/assets/lobby-border-frame/frame-corner-bl.png`
- Create: `apps/web/src/assets/lobby-border-frame/frame-edge-top.png`
- Create: `apps/web/src/assets/lobby-border-frame/frame-edge-right.png`
- Create: `apps/web/src/assets/lobby-border-frame/frame-edge-bottom.png`
- Create: `apps/web/src/assets/lobby-border-frame/frame-edge-left.png`

- [ ] **Step 1: Generate assets from the supplied source image**

Run a Python/Pillow script that:

```python
from pathlib import Path
from PIL import Image

source = Path("/Users/fanqiedanhuatang/Downloads/ChatGPT Image 2026年6月17日 18_09_45.png")
out = Path("apps/web/src/assets/lobby-border-frame")
out.mkdir(parents=True, exist_ok=True)

image = Image.open(source).convert("RGBA")
pixels = image.load()
width, height = image.size

for y in range(height):
    for x in range(width):
        r, g, b, a = pixels[x, y]
        max_channel = max(r, g, b)
        min_channel = min(r, g, b)
        saturation = max_channel - min_channel
        near_white = max_channel > 218 and saturation < 34
        border_band = y < 140 or y > height - 145 or x < 145 or x > width - 145
        if near_white or not border_band:
            pixels[x, y] = (r, g, b, 0)
        else:
            alpha = min(255, max(0, int((235 - max_channel) * 3.5) + saturation * 2))
            pixels[x, y] = (r, g, b, max(alpha, 96))

image.save(out / "source-transparent.png")

crops = {
    "frame-corner-tl.png": (24, 24, 172, 172),
    "frame-corner-tr.png": (width - 172, 24, width - 24, 172),
    "frame-corner-br.png": (width - 172, height - 172, width - 24, height - 24),
    "frame-corner-bl.png": (24, height - 172, 172, height - 24),
    "frame-edge-top.png": (190, 42, width - 190, 96),
    "frame-edge-right.png": (width - 96, 190, width - 42, height - 190),
    "frame-edge-bottom.png": (190, height - 96, width - 190, height - 42),
    "frame-edge-left.png": (42, 190, 96, height - 190),
}

for name, box in crops.items():
    image.crop(box).save(out / name)
```

- [ ] **Step 2: Inspect generated assets**

Run: `file apps/web/src/assets/lobby-border-frame/*.png`

Expected: PNG image data with RGBA color. Open `source-transparent.png` and a contact sheet if the slices need tuning.

### Task 4: Component and Export

**Files:**
- Create: `apps/web/src/components/ui/GothicBorderFrame.tsx`
- Modify: `apps/web/src/components/ui/index.tsx`

- [ ] **Step 1: Implement the minimal component**

```tsx
import type { HTMLAttributes } from "react";

type GothicBorderFrameElement = "article" | "aside" | "div" | "footer" | "section";

export type GothicBorderFrameProps = HTMLAttributes<HTMLElement> & {
  as?: GothicBorderFrameElement;
  contentClassName?: string;
  density?: "default" | "compact";
};

const framePieces = [
  "corner-tl",
  "edge-top",
  "corner-tr",
  "edge-right",
  "corner-br",
  "edge-bottom",
  "corner-bl",
  "edge-left",
] as const;

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function GothicBorderFrame({
  as: Component = "div",
  children,
  className,
  contentClassName,
  density = "default",
  ...props
}: GothicBorderFrameProps) {
  return (
    <Component
      className={cx(
        "gothic-border-frame",
        `gothic-border-frame-${density}`,
        className,
      )}
      {...props}
    >
      <div aria-hidden="true" className="gothic-border-frame-decoration">
        {framePieces.map((piece) => (
          <span
            className={cx("gothic-border-frame-piece", `gothic-border-frame-${piece}`)}
            key={piece}
          />
        ))}
      </div>
      <div className={cx("gothic-border-frame-content", contentClassName)}>
        {children}
      </div>
    </Component>
  );
}
```

- [ ] **Step 2: Export the component**

Add to `apps/web/src/components/ui/index.tsx`:

```ts
export {
  GothicBorderFrame,
  type GothicBorderFrameProps,
} from "./GothicBorderFrame";
```

- [ ] **Step 3: Run the component test**

Run: `pnpm --dir apps/web test -- --run src/components/ui/GothicBorderFrame.test.tsx`

Expected: still FAIL until CSS is added, then PASS after Task 5.

### Task 5: CSS Frame Styles

**Files:**
- Modify: `apps/web/src/styles/index.css`

- [ ] **Step 1: Add frame CSS**

Add CSS before `.gothic-button` definitions:

```css
.gothic-border-frame {
  --gothic-border-frame-corner-inline: 74px;
  --gothic-border-frame-corner-block: 74px;
  --gothic-border-frame-edge-thickness: 28px;
  --gothic-border-frame-content-inset-block: 0.7rem;
  --gothic-border-frame-content-inset-inline: 0.78rem;
  position: relative;
  isolation: isolate;
}

.gothic-border-frame-compact {
  --gothic-border-frame-corner-inline: 62px;
  --gothic-border-frame-corner-block: 48px;
  --gothic-border-frame-edge-thickness: 22px;
  --gothic-border-frame-content-inset-block: 0.46rem;
  --gothic-border-frame-content-inset-inline: 0.58rem;
}

.gothic-border-frame-decoration,
.gothic-border-frame-piece {
  position: absolute;
  pointer-events: none;
}

.gothic-border-frame-decoration {
  inset: 0;
  z-index: 2;
}

.gothic-border-frame-piece {
  display: block;
  background-position: center;
  background-repeat: no-repeat;
  background-size: contain;
  filter: drop-shadow(0 0 7px rgb(0 0 0 / 62%));
}

.gothic-border-frame-content {
  position: relative;
  z-index: 3;
  min-width: 0;
  min-height: 0;
}
```

Then add piece-specific backgrounds and lobby content layer layout.

- [ ] **Step 2: Adjust lobby column/action bar CSS for the content layer**

Move flex alignment to `.gothic-border-frame-content` where needed:

```css
.lobby-workbench-column > .gothic-border-frame-content {
  display: flex;
  min-height: 0;
  flex: 1 1 auto;
  flex-direction: column;
}

.lobby-action-bar > .gothic-border-frame-content {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: end;
  justify-content: space-between;
  gap: 0.72rem;
}
```

- [ ] **Step 3: Run the component test**

Run: `pnpm --dir apps/web test -- --run src/components/ui/GothicBorderFrame.test.tsx`

Expected: PASS.

### Task 6: Apply Frame to Lobby Regions

**Files:**
- Modify: `apps/web/src/features/games/components/LobbyRuleSelector.tsx`
- Modify: `apps/web/src/features/games/components/LobbyLineupWorkbench.tsx`
- Modify: `apps/web/src/features/games/components/LobbyActionBar.tsx`

- [ ] **Step 1: Wrap `LobbyRuleSelector` root**

```tsx
import { GothicBorderFrame, RadioCards } from "../../../components/ui";

return (
  <GothicBorderFrame
    aria-labelledby="lobby-rule-selector-title"
    as="section"
    className="lobby-workbench-column lobby-rule-column"
    data-testid="lobby-rule-column"
  >
    ...
  </GothicBorderFrame>
);
```

- [ ] **Step 2: Wrap lineup and player columns**

```tsx
<GothicBorderFrame
  className="lobby-workbench-column lobby-lineup-column"
  data-testid="lobby-lineup-column"
>
  ...
</GothicBorderFrame>

<GothicBorderFrame
  className="lobby-workbench-column lobby-player-column"
  data-testid="lobby-player-column"
  ref={playerColumnRef}
>
  ...
</GothicBorderFrame>
```

- [ ] **Step 3: Wrap action bar root**

```tsx
<GothicBorderFrame
  as="footer"
  className="lobby-action-bar"
  data-testid="lobby-action-bar"
  density="compact"
>
  ...
</GothicBorderFrame>
```

- [ ] **Step 4: Run lobby integration test**

Run: `pnpm --dir apps/web test -- --run src/pages/GamesPage.test.tsx -t "renders the three-column lobby workbench"`

Expected: PASS.

### Task 7: Full Verification and Visual QA

**Files:**
- Modify only if tests or screenshots reveal a scoped layout issue.

- [ ] **Step 1: Run focused tests**

Run: `pnpm --dir apps/web test -- --run src/components/ui/GothicBorderFrame.test.tsx src/pages/GamesPage.test.tsx`

Expected: PASS.

- [ ] **Step 2: Run web build**

Run: `pnpm --dir apps/web build`

Expected: PASS with Vite build output.

- [ ] **Step 3: Start the dev server**

Run: `pnpm --dir apps/web dev -- --host 127.0.0.1`

Expected: local Vite URL, usually `http://127.0.0.1:5173`.

- [ ] **Step 4: Browser screenshot QA**

Open `/games` at desktop and mobile widths. Confirm:

- The four target regions have the new transparent gothic border.
- The center of each frame is transparent over the existing dark panel background.
- Titles, inputs, buttons, rule cards, seat cards, and player cards do not overlap the corner art.
- Rule and player lists still scroll.
- The bottom action bar uses the compact frame and keeps buttons readable.

- [ ] **Step 5: Commit implementation**

```bash
git add apps/web/src/components/ui/GothicBorderFrame.tsx \
  apps/web/src/components/ui/GothicBorderFrame.test.tsx \
  apps/web/src/components/ui/index.tsx \
  apps/web/src/styles/index.css \
  apps/web/src/assets/lobby-border-frame \
  apps/web/src/features/games/components/LobbyRuleSelector.tsx \
  apps/web/src/features/games/components/LobbyLineupWorkbench.tsx \
  apps/web/src/features/games/components/LobbyActionBar.tsx \
  apps/web/src/pages/GamesPage.test.tsx \
  docs/superpowers/plans/2026-06-17-lobby-transparent-gothic-border.md
git commit -m "feat: add transparent lobby border frame"
```
