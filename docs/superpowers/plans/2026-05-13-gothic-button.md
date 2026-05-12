# Gothic Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable gothic `Button` skin backed by the provided PNG assets, plus a new standalone component example page that displays every button intent without changing existing pages.

**Architecture:** Extend the existing `Button` component with `skin` and `intent` while leaving the default branch unchanged. Put gothic visuals in global CSS so Vite can bundle the assets, and expose a direct demo route at `/components/buttons` through the central route definition.

**Tech Stack:** React 19, React Router, TypeScript, Vite, Tailwind CSS utility classes, Vitest, Testing Library.

---

### Task 1: Button API And Demo Route Tests

**Files:**
- Create: `apps/web/src/components/ui/Button.test.tsx`
- Modify: `apps/web/src/tests/app.test.tsx`

- [ ] **Step 1: Write failing tests for gothic button API**

Create `apps/web/src/components/ui/Button.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Link } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Button } from ".";

describe("Button", () => {
  it("renders the gothic skin with the requested intent", () => {
    render(
      <Button intent="danger" skin="gothic">
        处决玩家
      </Button>,
    );

    const button = screen.getByRole("button", { name: "处决玩家" });

    expect(button).toHaveClass("gothic-button");
    expect(button).toHaveAttribute("data-intent", "danger");
    expect(screen.getByText("处决玩家")).toHaveClass("gothic-button-label");
  });

  it("keeps gothic classes when rendering as a child link", () => {
    render(
      <MemoryRouter>
        <Button asChild intent="primary" skin="gothic">
          <Link to="/games">开始游戏</Link>
        </Button>
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "开始游戏" });

    expect(link).toHaveClass("gothic-button");
    expect(link).toHaveAttribute("data-intent", "primary");
    expect(link).toHaveAttribute("href", "/games");
  });

  it("maps legacy colors to gothic intent when intent is omitted", () => {
    render(
      <Button color="green" skin="gothic">
        确认
      </Button>,
    );

    expect(screen.getByRole("button", { name: "确认" })).toHaveAttribute(
      "data-intent",
      "success",
    );
  });

  it("preserves the existing loading behavior for gothic buttons", () => {
    render(
      <Button loading skin="gothic">
        继续对局
      </Button>,
    );

    const button = screen.getByRole("button", { name: "处理中..." });

    expect(button).toBeDisabled();
    expect(button).toHaveClass("gothic-button");
  });
});
```

- [ ] **Step 2: Write failing route test for the example page**

Append this test to `apps/web/src/tests/app.test.tsx`:

```tsx
it("routes the gothic button showcase path to the component example page", async () => {
  renderRoute(["/components/buttons"]);

  expect(
    await screen.findByRole("heading", { name: "Gothic Button" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Primary" })).toHaveAttribute(
    "data-intent",
    "primary",
  );
  expect(screen.getByRole("button", { name: "Danger Disabled" })).toBeDisabled();
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
cd apps/web && pnpm test -- --run src/components/ui/Button.test.tsx src/tests/app.test.tsx
```

Expected: FAIL because `skin`, `intent`, `gothic-button-label`, and `/components/buttons` do not exist yet.

### Task 2: Gothic Button Component And Assets

**Files:**
- Modify: `apps/web/src/components/ui/index.tsx`
- Modify: `apps/web/src/styles/index.css`
- Create: `apps/web/src/assets/gothic-buttons/gothic-button-default.png`
- Create: `apps/web/src/assets/gothic-buttons/gothic-button-info.png`
- Create: `apps/web/src/assets/gothic-buttons/gothic-button-primary.png`
- Create: `apps/web/src/assets/gothic-buttons/gothic-button-danger.png`
- Create: `apps/web/src/assets/gothic-buttons/gothic-button-success.png`
- Create: `apps/web/src/assets/gothic-buttons/gothic-button-warning.png`

- [ ] **Step 1: Copy the provided PNG assets into the web app**

Run:

```bash
mkdir -p apps/web/src/assets/gothic-buttons
cp /Users/fanqiedanhuatang/Documents/Codex/2026-05-12/imagegen-users-fanqiedanhuatang-codex-skills-system/output/imagegen/gothic-buttons-by-type/gothic-button-default.png apps/web/src/assets/gothic-buttons/gothic-button-default.png
cp /Users/fanqiedanhuatang/Documents/Codex/2026-05-12/imagegen-users-fanqiedanhuatang-codex-skills-system/output/imagegen/gothic-buttons-by-type/gothic-button-info.png apps/web/src/assets/gothic-buttons/gothic-button-info.png
cp /Users/fanqiedanhuatang/Documents/Codex/2026-05-12/imagegen-users-fanqiedanhuatang-codex-skills-system/output/imagegen/gothic-buttons-by-type/gothic-button-primary.png apps/web/src/assets/gothic-buttons/gothic-button-primary.png
cp /Users/fanqiedanhuatang/Documents/Codex/2026-05-12/imagegen-users-fanqiedanhuatang-codex-skills-system/output/imagegen/gothic-buttons-by-type/gothic-button-danger.png apps/web/src/assets/gothic-buttons/gothic-button-danger.png
cp /Users/fanqiedanhuatang/Documents/Codex/2026-05-12/imagegen-users-fanqiedanhuatang-codex-skills-system/output/imagegen/gothic-buttons-by-type/gothic-button-success.png apps/web/src/assets/gothic-buttons/gothic-button-success.png
cp /Users/fanqiedanhuatang/Documents/Codex/2026-05-12/imagegen-users-fanqiedanhuatang-codex-skills-system/output/imagegen/gothic-buttons-by-type/gothic-button-warning.png apps/web/src/assets/gothic-buttons/gothic-button-warning.png
```

- [ ] **Step 2: Extend the Button type and render branch**

Add `ButtonIntent`, `ButtonSkin`, `gothicIntentFromColor`, `buttonSizeClass`, `gothicButtonSizeClass`, and `gothicButtonClasses` in `apps/web/src/components/ui/index.tsx`. Update `ButtonProps` with `intent?: ButtonIntent` and `skin?: ButtonSkin`. In `Button`, if `skin === "gothic"`, render the same element/asChild behavior with `className` containing `gothic-button`, `data-intent`, and child content wrapped in `<span className="gothic-button-label">`.

- [ ] **Step 3: Add gothic button CSS**

Append CSS to `apps/web/src/styles/index.css` defining `.gothic-button`, `.gothic-button-label`, size modifiers, intent image variables, hover, active, focus-visible, and disabled states. Use `border-image-slice` and `border-image-source` variables from the spec.

- [ ] **Step 4: Run Button tests**

Run:

```bash
cd apps/web && pnpm test -- --run src/components/ui/Button.test.tsx
```

Expected: PASS.

### Task 3: Component Example Page

**Files:**
- Create: `apps/web/src/pages/ComponentButtonShowcasePage.tsx`
- Modify: `apps/web/src/routes/definitions.tsx`

- [ ] **Step 1: Create the standalone page**

Create `ComponentButtonShowcasePage` with a first-screen component showcase, not a marketing page. It should render all six intents, three sizes, disabled buttons, loading buttons, full-width buttons, and an `asChild` link example.

- [ ] **Step 2: Register a direct route**

Add `ComponentButtonShowcasePage` to `apps/web/src/routes/definitions.tsx` and register:

```tsx
{
  path: "/components/buttons",
  element: <ComponentButtonShowcasePage />,
}
```

Place it before `"/games/:sessionId"` to avoid route ambiguity.

- [ ] **Step 3: Run route tests**

Run:

```bash
cd apps/web && pnpm test -- --run src/tests/app.test.tsx
```

Expected: PASS.

### Task 4: Verification And Visual Check

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
cd apps/web && pnpm test -- --run src/components/ui/Button.test.tsx src/tests/app.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run build**

Run:

```bash
cd apps/web && pnpm build
```

Expected: PASS.

- [ ] **Step 3: Start the local web server**

Run:

```bash
cd apps/web && pnpm dev -- --host 127.0.0.1
```

Expected: Vite serves a local URL, normally `http://127.0.0.1:5173/`.

- [ ] **Step 4: Open the demo route and inspect**

Open:

```text
http://127.0.0.1:5173/components/buttons
```

Expected: page shows the gothic button component matrix. Six intents use different provided PNGs, text is readable, disabled/loading states are obvious, and layout does not overlap at desktop or mobile widths.
