# 独立手机版 Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent `apps/mobile-web` React/Vite app for phone-portrait complete Werewolf Arena operation while reusing the existing FastAPI backend.

**Architecture:** Add a new pnpm workspace app beside `apps/web`, with its own routes, CSS, components, API wrappers, and tests. The mobile app talks to the existing `/api/v1/...` endpoints through a local `src/api` layer and uses a flex-based mobile shell with bottom tabs and phone-width constraints.

**Tech Stack:** React 19, TypeScript 6, Vite 8, React Router 7, TanStack Query 5, Tailwind 4, Vitest, Testing Library, FastAPI backend endpoints already exposed by `apps/api`.

---

## File Structure

Create these mobile app files:

- `apps/mobile-web/package.json`: app scripts and dependencies.
- `apps/mobile-web/index.html`: Vite HTML entry.
- `apps/mobile-web/vite.config.ts`: React, Tailwind, proxy, Vitest setup.
- `apps/mobile-web/tsconfig.json`, `apps/mobile-web/tsconfig.app.json`, `apps/mobile-web/tsconfig.node.json`: TypeScript project config copied from the desktop app shape.
- `apps/mobile-web/eslint.config.js`: local ESLint config copied from `apps/web`.
- `apps/mobile-web/src/main.tsx`: React root with Query provider.
- `apps/mobile-web/src/app/App.tsx`: Router provider wrapper.
- `apps/mobile-web/src/lib/query-client.ts`: mobile query defaults.
- `apps/mobile-web/src/tests/setup.ts`: Testing Library and DOM shims.
- `apps/mobile-web/src/styles/index.css`: independent mobile tokens, flex shell, gothic mobile styling.
- `apps/mobile-web/src/routes/index.tsx`, `apps/mobile-web/src/routes/definitions.tsx`: mobile routes.
- `apps/mobile-web/src/layout/MobileAppShell.tsx`: top-level phone-width shell and tab container.
- `apps/mobile-web/src/layout/MobileTabBar.tsx`: bottom tab navigation.
- `apps/mobile-web/src/components/StatusBanner.tsx`: reusable loading, error, empty, and status messages.
- `apps/mobile-web/src/components/FixedActionBar.tsx`: sticky bottom action area above the tab bar.
- `apps/mobile-web/src/components/MobileButton.tsx`: mobile-sized action button.
- `apps/mobile-web/src/api/client.ts`: JSON fetch wrapper and error type.
- `apps/mobile-web/src/api/types.ts`: API response and request types used by mobile pages.
- `apps/mobile-web/src/api/healthApi.ts`, `apps/mobile-web/src/api/gamesApi.ts`, `apps/mobile-web/src/api/playerProfilesApi.ts`: endpoint wrappers.
- `apps/mobile-web/src/api/liveApi.ts`: EventSource builder.
- `apps/mobile-web/src/features/live/useMobileGameRunEvents.ts`: mobile SSE hook.
- `apps/mobile-web/src/pages/GameHomePage.tsx`: game home with one-click start.
- `apps/mobile-web/src/pages/CustomGamePage.tsx`: rule, player, model, confirm wizard.
- `apps/mobile-web/src/pages/LivePage.tsx`: stage-first live view.
- `apps/mobile-web/src/pages/PlayersPage.tsx`: player library for mobile.
- `apps/mobile-web/src/pages/HistoryPage.tsx`: session cards and resume/playback actions.
- `apps/mobile-web/src/pages/PlaybackPage.tsx`: timeline-first replay.
- `apps/mobile-web/src/pages/SettingsPage.tsx`: health, rules, models, local preferences.

Modify these existing files:

- `package.json`: add `dev:mobile`, `build:mobile`, `lint:mobile`, `test:mobile`.
- `Makefile`: add `mobile-web`, include it in `.PHONY`, leave existing `web` unchanged.
- `README.md`: add mobile local-run commands and URL.

Reference but do not import from these desktop files:

- `apps/web/src/main.tsx`
- `apps/web/vite.config.ts`
- `apps/web/src/lib/query-client.ts`
- `apps/web/src/features/games/hooks/useGameRunEvents.ts`
- `apps/web/src/features/games/api/*.ts`
- `apps/web/src/features/games/types.ts`

## Task 1: Scaffold the Independent Mobile Workspace App

**Files:**
- Create: `apps/mobile-web/package.json`
- Create: `apps/mobile-web/index.html`
- Create: `apps/mobile-web/vite.config.ts`
- Create: `apps/mobile-web/tsconfig.json`
- Create: `apps/mobile-web/tsconfig.app.json`
- Create: `apps/mobile-web/tsconfig.node.json`
- Create: `apps/mobile-web/eslint.config.js`
- Create: `apps/mobile-web/src/main.tsx`
- Create: `apps/mobile-web/src/app/App.tsx`
- Create: `apps/mobile-web/src/lib/query-client.ts`
- Create: `apps/mobile-web/src/tests/setup.ts`
- Create: `apps/mobile-web/src/styles/index.css`
- Modify: `package.json`
- Modify: `Makefile`
- Modify: `README.md`

- [ ] **Step 1: Create the app package**

Create `apps/mobile-web/package.json`:

```json
{
  "name": "mobile-web",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 5174",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "preview": "vite preview",
    "test": "vitest"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.99.2",
    "react": "^19.2.5",
    "react-dom": "^19.2.5",
    "react-router-dom": "^7.14.2",
    "zod": "^4.3.6"
  },
  "devDependencies": {
    "@eslint/js": "^9.39.4",
    "@tailwindcss/vite": "^4.2.4",
    "@testing-library/jest-dom": "^6.9.1",
    "@testing-library/react": "^16.3.2",
    "@testing-library/user-event": "^14.6.1",
    "@types/node": "^24.12.2",
    "@types/react": "^19.2.14",
    "@types/react-dom": "^19.2.3",
    "@vitejs/plugin-react": "^6.0.1",
    "eslint": "^9.39.4",
    "eslint-plugin-react-hooks": "^7.1.1",
    "eslint-plugin-react-refresh": "^0.5.2",
    "globals": "^17.5.0",
    "jsdom": "^29.0.2",
    "tailwindcss": "^4.2.4",
    "typescript": "~6.0.2",
    "typescript-eslint": "^8.58.2",
    "vite": "^8.0.9",
    "vitest": "^4.1.5"
  }
}
```

- [ ] **Step 2: Create the Vite HTML entry**

Create `apps/mobile-web/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <meta name="theme-color" content="#080b10" />
    <title>狼人杀竞技场 · 手机版</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 3: Create Vite and TypeScript config**

Create `apps/mobile-web/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: {
    port: 5174,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/tests/setup.ts",
  },
});
```

Create `apps/mobile-web/tsconfig.json`:

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

Create `apps/mobile-web/tsconfig.app.json`:

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "target": "es2023",
    "lib": ["ES2023", "DOM"],
    "module": "esnext",
    "types": ["vite/client", "vitest/globals"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

Create `apps/mobile-web/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.node.tsbuildinfo",
    "target": "es2023",
    "lib": ["ES2023"],
    "module": "esnext",
    "types": ["node"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 4: Create ESLint config and test setup**

Create `apps/mobile-web/eslint.config.js`:

```js
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
])
```

Create `apps/mobile-web/src/tests/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, "ResizeObserver", {
  configurable: true,
  value: TestResizeObserver,
});

Object.defineProperties(HTMLElement.prototype, {
  hasPointerCapture: {
    configurable: true,
    value: () => false,
  },
  releasePointerCapture: {
    configurable: true,
    value: () => {},
  },
  setPointerCapture: {
    configurable: true,
    value: () => {},
  },
  scrollIntoView: {
    configurable: true,
    value: () => {},
  },
});
```

- [ ] **Step 5: Create the initial React entry**

Create `apps/mobile-web/src/lib/query-client.ts`:

```ts
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
```

Create `apps/mobile-web/src/app/App.tsx`:

```tsx
export function App() {
  return (
    <main className="mobile-app-frame">
      <section className="mobile-page-surface" aria-label="狼人杀竞技场手机版">
        <h1>狼人杀竞技场</h1>
        <p>手机版 Web 正在搭建中</p>
      </section>
    </main>
  );
}
```

Create `apps/mobile-web/src/main.tsx`:

```tsx
import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import { queryClient } from "./lib/query-client";
import "./styles/index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
```

Create `apps/mobile-web/src/styles/index.css`:

```css
@import "tailwindcss";

:root {
  color: #f3eadc;
  background: #080b10;
  font-family: Inter, "Segoe UI", sans-serif;
}

html,
body,
#root {
  min-width: 320px;
  min-height: 100svh;
  margin: 0;
}

body {
  background:
    radial-gradient(circle at 50% 0%, rgb(185 147 92 / 18%), transparent 28rem),
    linear-gradient(180deg, #0d1218 0%, #05070a 100%);
}

button,
input,
select,
textarea {
  font: inherit;
}

.mobile-app-frame {
  display: flex;
  min-height: 100svh;
  justify-content: center;
  background: transparent;
}

.mobile-page-surface {
  width: min(100%, 480px);
  min-height: 100svh;
  padding: 24px;
  box-sizing: border-box;
}
```

- [ ] **Step 6: Add root scripts and Makefile target**

Modify root `package.json` scripts to include:

```json
{
  "dev:web": "pnpm --dir apps/web dev",
  "build:web": "pnpm --dir apps/web build",
  "lint:web": "pnpm --dir apps/web lint",
  "test:web": "pnpm --dir apps/web test -- --run",
  "dev:mobile": "pnpm --dir apps/mobile-web dev",
  "build:mobile": "pnpm --dir apps/mobile-web build",
  "lint:mobile": "pnpm --dir apps/mobile-web lint",
  "test:mobile": "pnpm --dir apps/mobile-web test -- --run"
}
```

Modify `Makefile`:

```makefile
.PHONY: install dev api web mobile-web db-up db-down lint test format

mobile-web:
	cd apps/mobile-web && pnpm dev --host 127.0.0.1 --port 5174
```

Keep the existing `web`, `api`, `lint`, `test`, and `format` commands unchanged in this task.

- [ ] **Step 7: Document the mobile local URL**

Add this section to `README.md` after the existing frontend local run section:

```markdown
### 手机版 Web

手机版 Web 是独立 Vite 应用，复用同一个 FastAPI 后端。

```bash
pnpm --dir apps/mobile-web dev --host 127.0.0.1 --port 5174
```

地址：

```text
http://127.0.0.1:5174
```

开发服务器同样会把 `/api` 代理到 `http://localhost:8000`。
```

- [ ] **Step 8: Install and verify the scaffold**

Run:

```bash
pnpm install
pnpm --dir apps/mobile-web build
```

Expected: `pnpm install` updates `pnpm-lock.yaml`, and the mobile build exits with code 0.

- [ ] **Step 9: Commit scaffold**

```bash
git add package.json pnpm-lock.yaml Makefile README.md apps/mobile-web
git commit -m "feat: scaffold independent mobile web app"
```

## Task 2: Add Mobile Shell, Routes, Tabs, and Core UI Primitives

**Files:**
- Create: `apps/mobile-web/src/routes/definitions.tsx`
- Create: `apps/mobile-web/src/routes/index.tsx`
- Create: `apps/mobile-web/src/layout/MobileAppShell.tsx`
- Create: `apps/mobile-web/src/layout/MobileTabBar.tsx`
- Create: `apps/mobile-web/src/components/MobileButton.tsx`
- Create: `apps/mobile-web/src/components/FixedActionBar.tsx`
- Create: `apps/mobile-web/src/components/StatusBanner.tsx`
- Create: `apps/mobile-web/src/layout/MobileAppShell.test.tsx`
- Modify: `apps/mobile-web/src/app/App.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write the shell and tab test**

Create `apps/mobile-web/src/layout/MobileAppShell.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { routes } from "../routes/definitions";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

describe("MobileAppShell", () => {
  it("renders the phone shell with bottom tabs", () => {
    renderAt("/");

    expect(screen.getByTestId("mobile-app-shell")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "手机版主导航" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "对局" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "玩家" })).toHaveAttribute("href", "/players");
    expect(screen.getByRole("link", { name: "历史" })).toHaveAttribute("href", "/history");
    expect(screen.getByRole("link", { name: "设置" })).toHaveAttribute("href", "/settings");
  });

  it("marks the active bottom tab", () => {
    renderAt("/players");

    const nav = screen.getByRole("navigation", { name: "手机版主导航" });

    expect(within(nav).getByRole("link", { name: "玩家" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "对局" })).not.toHaveAttribute("aria-current");
  });
});
```

- [ ] **Step 2: Run the shell test and verify it fails**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/layout/MobileAppShell.test.tsx
```

Expected: FAIL because `../routes/definitions` and shell components do not exist.

- [ ] **Step 3: Implement core UI primitives**

Create `apps/mobile-web/src/components/MobileButton.tsx`:

```tsx
import type { ButtonHTMLAttributes, ReactNode } from "react";

type MobileButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  tone?: "primary" | "secondary" | "danger";
};

export function MobileButton({
  children,
  className,
  tone = "secondary",
  type = "button",
  ...props
}: MobileButtonProps) {
  return (
    <button
      className={["mobile-button", `mobile-button-${tone}`, className]
        .filter(Boolean)
        .join(" ")}
      type={type}
      {...props}
    >
      {children}
    </button>
  );
}
```

Create `apps/mobile-web/src/components/FixedActionBar.tsx`:

```tsx
import type { ReactNode } from "react";

type FixedActionBarProps = {
  children: ReactNode;
};

export function FixedActionBar({ children }: FixedActionBarProps) {
  return <div className="mobile-fixed-action-bar">{children}</div>;
}
```

Create `apps/mobile-web/src/components/StatusBanner.tsx`:

```tsx
import type { ReactNode } from "react";

type StatusBannerProps = {
  children: ReactNode;
  title: string;
  tone?: "info" | "error" | "success";
};

export function StatusBanner({
  children,
  title,
  tone = "info",
}: StatusBannerProps) {
  return (
    <section className={`mobile-status-banner mobile-status-banner-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <h2>{title}</h2>
      <div>{children}</div>
    </section>
  );
}
```

- [ ] **Step 4: Implement shell and tab navigation**

Create `apps/mobile-web/src/layout/MobileTabBar.tsx`:

```tsx
import { NavLink } from "react-router-dom";

const tabs = [
  { label: "对局", to: "/", end: true },
  { label: "玩家", to: "/players" },
  { label: "历史", to: "/history" },
  { label: "设置", to: "/settings" },
];

export function MobileTabBar() {
  return (
    <nav aria-label="手机版主导航" className="mobile-tab-bar">
      {tabs.map((tab) => (
        <NavLink
          className={({ isActive }) =>
            ["mobile-tab-link", isActive ? "mobile-tab-link-active" : null]
              .filter(Boolean)
              .join(" ")
          }
          end={tab.end}
          key={tab.to}
          to={tab.to}
        >
          <span aria-hidden="true" className="mobile-tab-mark" />
          <span>{tab.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
```

Create `apps/mobile-web/src/layout/MobileAppShell.tsx`:

```tsx
import { Outlet } from "react-router-dom";

import { MobileTabBar } from "./MobileTabBar";

export function MobileAppShell() {
  return (
    <div className="mobile-app-frame">
      <div className="mobile-app-shell" data-testid="mobile-app-shell">
        <header className="mobile-top-bar">
          <p className="mobile-kicker">Werewolf Arena</p>
          <h1>狼人杀竞技场</h1>
        </header>
        <main className="mobile-content-region">
          <Outlet />
        </main>
        <MobileTabBar />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Implement starter routes**

Create `apps/mobile-web/src/routes/definitions.tsx`:

```tsx
import type { RouteObject } from "react-router-dom";

import { MobileAppShell } from "../layout/MobileAppShell";

function StarterPage({ title }: { title: string }) {
  return (
    <section className="mobile-page-section">
      <h2>{title}</h2>
      <p>路由已就绪，当前页面用于验证移动端导航和页面壳。</p>
    </section>
  );
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <MobileAppShell />,
    children: [
      { index: true, element: <StarterPage title="对局" /> },
      { path: "players", element: <StarterPage title="玩家" /> },
      { path: "history", element: <StarterPage title="历史" /> },
      { path: "settings", element: <StarterPage title="设置" /> },
      { path: "custom-game", element: <StarterPage title="自定义开局" /> },
      { path: "live/:runId", element: <StarterPage title="实时直播" /> },
      { path: "playback/:sessionId", element: <StarterPage title="手机复盘" /> },
    ],
  },
];
```

Create `apps/mobile-web/src/routes/index.tsx`:

```tsx
import { createBrowserRouter } from "react-router-dom";

import { routes } from "./definitions";

export { routes } from "./definitions";

export function createAppRouter() {
  return createBrowserRouter(routes);
}

export const router = createAppRouter();
```

Modify `apps/mobile-web/src/app/App.tsx`:

```tsx
import { RouterProvider } from "react-router-dom";

import { router } from "../routes";

export function App() {
  return <RouterProvider router={router} />;
}
```

- [ ] **Step 6: Add mobile shell CSS**

Append to `apps/mobile-web/src/styles/index.css`:

```css
.mobile-app-shell {
  display: flex;
  flex-direction: column;
  width: min(100%, 480px);
  min-height: 100svh;
  background:
    linear-gradient(180deg, rgb(11 16 22 / 94%), rgb(5 7 10 / 98%)),
    radial-gradient(circle at 50% 0%, rgb(185 147 92 / 16%), transparent 18rem);
  box-shadow: 0 0 80px rgb(0 0 0 / 42%);
}

.mobile-top-bar {
  flex: 0 0 auto;
  padding: calc(14px + env(safe-area-inset-top)) 18px 10px;
  border-bottom: 1px solid rgb(185 147 92 / 22%);
}

.mobile-top-bar h1,
.mobile-page-section h2 {
  margin: 0;
  color: #ead8bf;
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 1.28rem;
  line-height: 1.2;
}

.mobile-kicker {
  margin: 0 0 3px;
  color: #9fb0bd;
  font-size: 0.72rem;
  letter-spacing: 0;
  text-transform: uppercase;
}

.mobile-content-region {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 14px 14px calc(82px + env(safe-area-inset-bottom));
}

.mobile-page-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mobile-tab-bar {
  position: fixed;
  right: max(0px, calc((100vw - 480px) / 2));
  bottom: 0;
  left: max(0px, calc((100vw - 480px) / 2));
  z-index: 20;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  width: min(100%, 480px);
  margin: 0 auto;
  padding: 6px 8px calc(8px + env(safe-area-inset-bottom));
  border-top: 1px solid rgb(185 147 92 / 32%);
  background: rgb(5 7 10 / 94%);
  backdrop-filter: blur(12px) saturate(130%);
}

.mobile-tab-link {
  display: flex;
  min-width: 0;
  min-height: 48px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 8px;
  color: #aeb9c3;
  font-size: 0.82rem;
  text-decoration: none;
}

.mobile-tab-link-active {
  color: #f3dfbf;
  background: rgb(185 147 92 / 14%);
}

.mobile-tab-mark {
  width: 7px;
  height: 7px;
  border: 1px solid currentColor;
  transform: rotate(45deg);
}

.mobile-button {
  min-height: 44px;
  border: 1px solid rgb(185 147 92 / 42%);
  border-radius: 8px;
  padding: 0 14px;
  color: #f4e6d0;
  background: rgb(18 25 31 / 88%);
}

.mobile-button-primary {
  color: #10151b;
  background: #c99d5f;
}

.mobile-button-danger {
  border-color: rgb(182 62 54 / 64%);
  background: rgb(89 24 22 / 82%);
}

.mobile-fixed-action-bar {
  position: sticky;
  bottom: 0;
  display: flex;
  gap: 10px;
  padding: 10px 0 0;
  background: linear-gradient(180deg, transparent, #070a0e 34%);
}

.mobile-status-banner {
  border: 1px solid rgb(119 137 150 / 34%);
  border-radius: 8px;
  padding: 12px;
  background: rgb(13 20 28 / 86%);
}

.mobile-status-banner h2 {
  margin: 0 0 4px;
  font-size: 0.95rem;
}

.mobile-status-banner-error {
  border-color: rgb(182 62 54 / 58%);
}
```

- [ ] **Step 7: Run the shell test and build**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/layout/MobileAppShell.test.tsx
pnpm --dir apps/mobile-web build
```

Expected: both commands PASS.

- [ ] **Step 8: Commit shell and routes**

```bash
git add apps/mobile-web/src
git commit -m "feat: add mobile shell and tab routes"
```

## Task 3: Add API Client, Types, and Endpoint Wrappers

**Files:**
- Create: `apps/mobile-web/src/api/client.ts`
- Create: `apps/mobile-web/src/api/types.ts`
- Create: `apps/mobile-web/src/api/healthApi.ts`
- Create: `apps/mobile-web/src/api/gamesApi.ts`
- Create: `apps/mobile-web/src/api/playerProfilesApi.ts`
- Create: `apps/mobile-web/src/api/client.test.ts`
- Create: `apps/mobile-web/src/api/gamesApi.test.ts`

- [ ] **Step 1: Write API client tests**

Create `apps/mobile-web/src/api/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiFetch", () => {
  it("returns parsed JSON for successful responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 })));

    await expect(apiFetch<{ status: string }>("/api/v1/health")).resolves.toEqual({ status: "ok" });
  });

  it("raises ApiError with status and detail for failed responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Player profile database unavailable" }), { status: 503 })));

    await expect(apiFetch("/api/v1/player-profiles")).rejects.toMatchObject({
      name: "ApiError",
      status: 503,
      detail: "Player profile database unavailable",
    });
  });
});
```

- [ ] **Step 2: Run client tests and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/api/client.test.ts
```

Expected: FAIL because `src/api/client.ts` does not exist.

- [ ] **Step 3: Implement API client**

Create `apps/mobile-web/src/api/client.ts`:

```ts
export class ApiError extends Error {
  detail: string;
  status: number;

  constructor(message: string, status: number, detail: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

type ErrorBody = {
  detail?: unknown;
};

function normalizeDetail(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => normalizeDetail(item)).join("；");
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  return "请求失败";
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    let body: ErrorBody = {};
    try {
      body = (await response.json()) as ErrorBody;
    } catch {
      body = {};
    }
    const detail = normalizeDetail(body.detail);
    throw new ApiError(detail, response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
```

- [ ] **Step 4: Add mobile API types**

Create `apps/mobile-web/src/api/types.ts`:

```ts
export type HealthResponse = {
  status: string;
};

export type RoleSpecSummary = {
  role: string;
  count: number;
  team?: string;
  model_group?: string;
  category?: string;
};

export type RuleSetSummary = {
  id: string;
  version: string;
  name: string;
  description?: string;
  player_count: number;
  roles: RoleSpecSummary[];
  sheriff_enabled?: boolean;
  role_summary?: string;
  estimated_duration?: string;
};

export type RuleSetsResponse = {
  rule_sets: RuleSetSummary[];
};

export type ModelOption = {
  id: string;
  label: string;
};

export type ModelOptionsResponse = {
  models: ModelOption[];
};

export type PlayerProfile = {
  id: string;
  display_name: string;
  model: string;
  personality_id: string;
  appearance_id: string;
  avatar_image_url: string;
  short_description: string;
  favorite: boolean;
  tags: string[];
  updated_at: string;
};

export type PlayerProfileListResponse = {
  profiles: PlayerProfile[];
};

export type CreatePlayerConfigRequest = {
  seat: number;
  profile_id?: string;
  name?: string;
  display_name?: string;
  model?: string;
};

export type CreateGameRunRequest = {
  villager_model?: string;
  werewolf_model?: string;
  seed?: number;
  max_rounds?: number;
  rule_set_id?: string;
  player_configs?: CreatePlayerConfigRequest[];
};

export type GameRunStatus = "queued" | "running" | "completed" | "failed";

export type GameRun = {
  run_id: string;
  session_id: string;
  status: GameRunStatus;
  winner?: string | null;
  error?: string | null;
  rule_set?: RuleSetSummary;
};

export type GameSessionSummary = {
  session_id: string;
  status: "complete" | "partial";
  winner: string | null;
  round_count: number;
  created_at: string | null;
  rule_set?: RuleSetSummary | null;
  resumable?: boolean;
};

export type GameSessionsResponse = {
  sessions: GameSessionSummary[];
};

export type LiveGameEvent = {
  id: number;
  type: string;
  payload?: Record<string, unknown>;
  timestamp?: string;
};

export type GamePlaybackResponse = {
  session_id: string;
  timeline?: Array<{
    id?: string;
    title?: string;
    text?: string;
    round?: number;
  }>;
};
```

- [ ] **Step 5: Implement endpoint wrappers**

Create `apps/mobile-web/src/api/healthApi.ts`:

```ts
import { apiFetch } from "./client";
import type { HealthResponse } from "./types";

export function getHealth() {
  return apiFetch<HealthResponse>("/api/v1/health");
}
```

Create `apps/mobile-web/src/api/gamesApi.ts`:

```ts
import { apiFetch } from "./client";
import type {
  CreateGameRunRequest,
  GamePlaybackResponse,
  GameRun,
  GameSessionsResponse,
  ModelOptionsResponse,
  RuleSetsResponse,
} from "./types";

export function listGames() {
  return apiFetch<GameSessionsResponse>("/api/v1/games");
}

export function listRuleSets() {
  return apiFetch<RuleSetsResponse>("/api/v1/games/rule-sets");
}

export function listModelOptions() {
  return apiFetch<ModelOptionsResponse>("/api/v1/games/model-options");
}

export function createGameRun(request: CreateGameRunRequest) {
  return apiFetch<GameRun>("/api/v1/games/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function getGameRun(runId: string) {
  return apiFetch<GameRun>(`/api/v1/games/runs/${runId}`);
}

export function resumeGameRun(sessionId: string) {
  return apiFetch<GameRun>(`/api/v1/games/${sessionId}/resume`, {
    method: "POST",
  });
}

export function getGamePlayback(sessionId: string) {
  return apiFetch<GamePlaybackResponse>(`/api/v1/games/${sessionId}/playback`);
}
```

Create `apps/mobile-web/src/api/playerProfilesApi.ts`:

```ts
import { apiFetch } from "./client";
import type { PlayerProfileListResponse } from "./types";

export function listPlayerProfiles() {
  return apiFetch<PlayerProfileListResponse>("/api/v1/player-profiles");
}
```

Create `apps/mobile-web/src/api/liveApi.ts`:

```ts
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export function createRunEventSource(runId: string, afterId?: number) {
  const params = afterId === undefined ? "" : `?after_id=${afterId}`;
  return new EventSource(`${API_BASE_URL}/api/v1/games/runs/${runId}/events${params}`);
}
```

- [ ] **Step 6: Write endpoint wrapper test**

Create `apps/mobile-web/src/api/gamesApi.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { createGameRun, listRuleSets } from "./gamesApi";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("gamesApi", () => {
  it("lists rule sets from the existing backend path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ rule_sets: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await listRuleSets();

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games/rule-sets", undefined);
  });

  it("creates game runs through the existing backend path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ run_id: "run_1", session_id: "session_1", status: "queued" }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);

    await createGameRun({ rule_set_id: "classic_12", max_rounds: 8 });

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rule_set_id: "classic_12", max_rounds: 8 }),
    });
  });
});
```

- [ ] **Step 7: Run API tests**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/api
pnpm --dir apps/mobile-web build
```

Expected: tests and build PASS.

- [ ] **Step 8: Commit API layer**

```bash
git add apps/mobile-web/src/api
git commit -m "feat: add mobile API client"
```

## Task 4: Implement Game Home and One-Click Start

**Files:**
- Create: `apps/mobile-web/src/pages/GameHomePage.tsx`
- Create: `apps/mobile-web/src/pages/GameHomePage.test.tsx`
- Modify: `apps/mobile-web/src/routes/definitions.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write game home tests**

Create `apps/mobile-web/src/pages/GameHomePage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { GameHomePage } from "./GameHomePage";

const navigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigate };
});

vi.mock("../api/gamesApi", () => ({
  createGameRun: vi.fn(async () => ({ run_id: "run_mobile_1", session_id: "session_mobile_1", status: "queued" })),
  listGames: vi.fn(async () => ({ sessions: [{ session_id: "session_recent", status: "complete", winner: "villagers", round_count: 3, created_at: "2026-06-18T00:00:00Z" }] })),
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <GameHomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("GameHomePage", () => {
  it("starts a default game and navigates to live view", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "一键开局" }));

    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith("/live/run_mobile_1");
    });
  });

  it("shows recent game status", async () => {
    renderPage();

    expect(await screen.findByText("最近对局")).toBeInTheDocument();
    expect(screen.getByText("session_recent")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run game home tests and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/GameHomePage.test.tsx
```

Expected: FAIL because `GameHomePage.tsx` does not exist.

- [ ] **Step 3: Implement the game home page**

Create `apps/mobile-web/src/pages/GameHomePage.tsx`:

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";

import { createGameRun, listGames } from "../api/gamesApi";
import { MobileButton } from "../components/MobileButton";
import { StatusBanner } from "../components/StatusBanner";

function formatWinner(winner: string | null) {
  if (!winner) {
    return "未记录胜方";
  }
  return winner === "werewolves" ? "狼人胜利" : winner === "villagers" ? "好人胜利" : winner;
}

export function GameHomePage() {
  const navigate = useNavigate();
  const gamesQuery = useQuery({
    queryKey: ["mobile-games"],
    queryFn: listGames,
  });
  const startGame = useMutation({
    mutationFn: () => createGameRun({ max_rounds: 8, player_configs: [] }),
    onSuccess: (run) => {
      navigate(`/live/${run.run_id}`);
    },
  });
  const recentGame = gamesQuery.data?.sessions[0];

  return (
    <section className="mobile-page-section">
      <section className="mobile-hero-panel">
        <p className="mobile-kicker">大厅</p>
        <h2>今晚开一局</h2>
        <p>使用默认规则和玩家池快速发起对局，或进入自定义流程配置阵容。</p>
        <div className="mobile-home-actions">
          <MobileButton
            disabled={startGame.isPending}
            onClick={() => startGame.mutate()}
            tone="primary"
          >
            {startGame.isPending ? "开局中..." : "一键开局"}
          </MobileButton>
          <Link className="mobile-link-button" to="/custom-game">
            自定义开局
          </Link>
        </div>
      </section>

      {startGame.isError ? (
        <StatusBanner title="开局失败" tone="error">
          后端、玩家库或模型配置暂时不可用。请检查设置页状态后重试。
        </StatusBanner>
      ) : null}

      <section className="mobile-card">
        <h2>最近对局</h2>
        {gamesQuery.isPending ? <p>正在读取最近对局...</p> : null}
        {gamesQuery.isError ? <p>无法读取历史对局。</p> : null}
        {recentGame ? (
          <article className="mobile-list-row">
            <div>
              <strong>{recentGame.session_id}</strong>
              <p>{formatWinner(recentGame.winner)} · {recentGame.round_count} 轮</p>
            </div>
            <Link to={`/playback/${recentGame.session_id}`}>复盘</Link>
          </article>
        ) : null}
        {!gamesQuery.isPending && !recentGame ? <p>还没有历史对局。</p> : null}
      </section>
    </section>
  );
}
```

- [ ] **Step 4: Wire game home into routes**

Modify `apps/mobile-web/src/routes/definitions.tsx` so the index route uses `GameHomePage`:

```tsx
import type { RouteObject } from "react-router-dom";

import { MobileAppShell } from "../layout/MobileAppShell";
import { GameHomePage } from "../pages/GameHomePage";

function StarterPage({ title }: { title: string }) {
  return (
    <section className="mobile-page-section">
      <h2>{title}</h2>
      <p>路由已就绪，当前页面用于验证移动端导航和页面壳。</p>
    </section>
  );
}

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <MobileAppShell />,
    children: [
      { index: true, element: <GameHomePage /> },
      { path: "players", element: <StarterPage title="玩家" /> },
      { path: "history", element: <StarterPage title="历史" /> },
      { path: "settings", element: <StarterPage title="设置" /> },
      { path: "custom-game", element: <StarterPage title="自定义开局" /> },
      { path: "live/:runId", element: <StarterPage title="实时直播" /> },
      { path: "playback/:sessionId", element: <StarterPage title="手机复盘" /> },
    ],
  },
];
```

- [ ] **Step 5: Add page CSS**

Append to `apps/mobile-web/src/styles/index.css`:

```css
.mobile-hero-panel,
.mobile-card {
  border: 1px solid rgb(185 147 92 / 38%);
  border-radius: 8px;
  padding: 14px;
  background:
    linear-gradient(180deg, rgb(25 33 38 / 86%), rgb(9 13 18 / 92%)),
    radial-gradient(circle at 50% 0%, rgb(185 147 92 / 12%), transparent 14rem);
}

.mobile-hero-panel p,
.mobile-card p {
  margin: 6px 0 0;
  color: #bcc7d0;
}

.mobile-home-actions {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  margin-top: 14px;
}

.mobile-link-button {
  display: flex;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgb(185 147 92 / 34%);
  border-radius: 8px;
  color: #f3dfbf;
  text-decoration: none;
}

.mobile-list-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  padding: 12px 0 0;
}

.mobile-list-row strong,
.mobile-list-row p {
  overflow-wrap: anywhere;
}
```

- [ ] **Step 6: Run page tests and build**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/GameHomePage.test.tsx src/layout/MobileAppShell.test.tsx
pnpm --dir apps/mobile-web build
```

Expected: tests and build PASS.

- [ ] **Step 7: Commit game home**

```bash
git add apps/mobile-web/src
git commit -m "feat: add mobile game home"
```

## Task 5: Implement Custom Game Wizard

**Files:**
- Create: `apps/mobile-web/src/pages/CustomGamePage.tsx`
- Create: `apps/mobile-web/src/pages/CustomGamePage.test.tsx`
- Modify: `apps/mobile-web/src/routes/definitions.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write custom game tests**

Create `apps/mobile-web/src/pages/CustomGamePage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { CustomGamePage } from "./CustomGamePage";

const navigate = vi.fn();
const createGameRun = vi.fn(async () => ({ run_id: "custom_run", session_id: "custom_session", status: "queued" }));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navigate };
});

vi.mock("../api/gamesApi", () => ({
  createGameRun: (...args: unknown[]) => createGameRun(...args),
  listModelOptions: vi.fn(async () => ({ models: [{ id: "deepseek-v4-flash", label: "DeepSeek" }] })),
  listRuleSets: vi.fn(async () => ({ rule_sets: [{ id: "classic_12", version: "1", name: "经典 12 人", player_count: 12, roles: [] }] })),
}));

vi.mock("../api/playerProfilesApi", () => ({
  listPlayerProfiles: vi.fn(async () => ({ profiles: [{ id: "p1", display_name: "夜鸦", model: "deepseek-v4-flash", personality_id: "balanced", appearance_id: "default", avatar_image_url: "", short_description: "冷静", favorite: true, tags: ["默认"], updated_at: "2026-06-18T00:00:00Z" }] })),
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CustomGamePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CustomGamePage", () => {
  it("creates a game with selected rule and player", async () => {
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("经典 12 人");
    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.click(await screen.findByRole("checkbox", { name: /夜鸦/ }));
    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.click(screen.getByRole("button", { name: "确认开局" }));

    await waitFor(() => {
      expect(createGameRun).toHaveBeenCalledWith({
        rule_set_id: "classic_12",
        villager_model: "deepseek-v4-flash",
        werewolf_model: "deepseek-v4-flash",
        max_rounds: 8,
        player_configs: [{ seat: 1, profile_id: "p1" }],
      });
      expect(navigate).toHaveBeenCalledWith("/live/custom_run");
    });
  });
});
```

- [ ] **Step 2: Run wizard tests and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/CustomGamePage.test.tsx
```

Expected: FAIL because `CustomGamePage.tsx` does not exist.

- [ ] **Step 3: Implement custom game wizard**

Create `apps/mobile-web/src/pages/CustomGamePage.tsx`:

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { createGameRun, listModelOptions, listRuleSets } from "../api/gamesApi";
import { listPlayerProfiles } from "../api/playerProfilesApi";
import { FixedActionBar } from "../components/FixedActionBar";
import { MobileButton } from "../components/MobileButton";
import { StatusBanner } from "../components/StatusBanner";

const stepTitles = ["规则预设", "玩家选择", "模型和轮数", "确认开局"];

export function CustomGamePage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null);
  const [selectedProfileIds, setSelectedProfileIds] = useState<string[]>([]);
  const [maxRounds, setMaxRounds] = useState(8);
  const rulesQuery = useQuery({ queryKey: ["mobile-rule-sets"], queryFn: listRuleSets });
  const modelsQuery = useQuery({ queryKey: ["mobile-model-options"], queryFn: listModelOptions });
  const playersQuery = useQuery({ queryKey: ["mobile-player-profiles"], queryFn: listPlayerProfiles });
  const firstRule = rulesQuery.data?.rule_sets[0];
  const activeRuleId = selectedRuleId ?? firstRule?.id ?? "";
  const firstModel = modelsQuery.data?.models[0]?.id ?? "";
  const selectedPlayers = useMemo(
    () => playersQuery.data?.profiles.filter((profile) => selectedProfileIds.includes(profile.id)) ?? [],
    [playersQuery.data?.profiles, selectedProfileIds],
  );
  const mutation = useMutation({
    mutationFn: () =>
      createGameRun({
        rule_set_id: activeRuleId,
        villager_model: firstModel,
        werewolf_model: firstModel,
        max_rounds: maxRounds,
        player_configs: selectedPlayers.map((profile, index) => ({
          seat: index + 1,
          profile_id: profile.id,
        })),
      }),
    onSuccess: (run) => navigate(`/live/${run.run_id}`),
  });

  const canContinue = step === 0 ? Boolean(activeRuleId) : step === 1 ? selectedPlayers.length > 0 : true;

  const toggleProfile = (profileId: string) => {
    setSelectedProfileIds((current) =>
      current.includes(profileId)
        ? current.filter((id) => id !== profileId)
        : [...current, profileId],
    );
  };

  return (
    <section className="mobile-page-section">
      <header className="mobile-card">
        <p className="mobile-kicker">自定义开局</p>
        <h2>{stepTitles[step]}</h2>
        <p>第 {step + 1} 步，共 4 步</p>
      </header>

      {mutation.isError ? (
        <StatusBanner title="开局失败" tone="error">
          无法创建对局。请确认规则、玩家库和模型配置可用。
        </StatusBanner>
      ) : null}

      {step === 0 ? (
        <section className="mobile-card">
          {rulesQuery.data?.rule_sets.map((rule) => (
            <label className="mobile-choice-row" key={rule.id}>
              <input
                checked={activeRuleId === rule.id}
                name="rule"
                onChange={() => setSelectedRuleId(rule.id)}
                type="radio"
              />
              <span>
                <strong>{rule.name}</strong>
                <small>{rule.player_count} 人 · {rule.estimated_duration ?? "标准时长"}</small>
              </span>
            </label>
          ))}
        </section>
      ) : null}

      {step === 1 ? (
        <section className="mobile-card">
          {playersQuery.data?.profiles.map((profile) => (
            <label className="mobile-choice-row" key={profile.id}>
              <input
                checked={selectedProfileIds.includes(profile.id)}
                onChange={() => toggleProfile(profile.id)}
                type="checkbox"
              />
              <span>
                <strong>{profile.display_name}</strong>
                <small>{profile.short_description || profile.model}</small>
              </span>
            </label>
          ))}
        </section>
      ) : null}

      {step === 2 ? (
        <section className="mobile-card">
          <label className="mobile-field">
            <span>模型</span>
            <select value={firstModel} disabled>
              <option value={firstModel}>{modelsQuery.data?.models[0]?.label ?? "默认模型"}</option>
            </select>
          </label>
          <label className="mobile-field">
            <span>最大轮数</span>
            <input min={1} max={20} onChange={(event) => setMaxRounds(Number(event.target.value))} type="number" value={maxRounds} />
          </label>
        </section>
      ) : null}

      {step === 3 ? (
        <section className="mobile-card">
          <p>规则：{rulesQuery.data?.rule_sets.find((rule) => rule.id === activeRuleId)?.name ?? activeRuleId}</p>
          <p>玩家：{selectedPlayers.map((profile) => profile.display_name).join("、")}</p>
          <p>最大轮数：{maxRounds}</p>
        </section>
      ) : null}

      <FixedActionBar>
        {step > 0 ? <MobileButton onClick={() => setStep((value) => value - 1)}>上一步</MobileButton> : null}
        {step < 3 ? (
          <MobileButton disabled={!canContinue} onClick={() => setStep((value) => value + 1)} tone="primary">
            下一步
          </MobileButton>
        ) : (
          <MobileButton disabled={mutation.isPending || !activeRuleId} onClick={() => mutation.mutate()} tone="primary">
            {mutation.isPending ? "开局中..." : "确认开局"}
          </MobileButton>
        )}
      </FixedActionBar>
    </section>
  );
}
```

- [ ] **Step 4: Wire custom route**

Modify `apps/mobile-web/src/routes/definitions.tsx` imports and custom route:

```tsx
import { CustomGamePage } from "../pages/CustomGamePage";
```

Replace the `custom-game` route element:

```tsx
{ path: "custom-game", element: <CustomGamePage /> },
```

- [ ] **Step 5: Add wizard CSS**

Append to `apps/mobile-web/src/styles/index.css`:

```css
.mobile-choice-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 54px;
  border-bottom: 1px solid rgb(119 137 150 / 20%);
}

.mobile-choice-row:last-child {
  border-bottom: 0;
}

.mobile-choice-row span {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.mobile-choice-row small {
  color: #9fb0bd;
}

.mobile-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.mobile-field input,
.mobile-field select {
  min-height: 44px;
  border: 1px solid rgb(119 137 150 / 38%);
  border-radius: 8px;
  padding: 0 12px;
  color: #f3eadc;
  background: #0d141c;
}
```

- [ ] **Step 6: Run wizard tests and build**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/CustomGamePage.test.tsx
pnpm --dir apps/mobile-web build
```

Expected: tests and build PASS.

- [ ] **Step 7: Commit custom game wizard**

```bash
git add apps/mobile-web/src
git commit -m "feat: add mobile custom game flow"
```

## Task 6: Implement Mobile Live SSE Hook and Stage-First Live Page

**Files:**
- Create: `apps/mobile-web/src/features/live/useMobileGameRunEvents.ts`
- Create: `apps/mobile-web/src/features/live/useMobileGameRunEvents.test.tsx`
- Create: `apps/mobile-web/src/pages/LivePage.tsx`
- Create: `apps/mobile-web/src/pages/LivePage.test.tsx`
- Modify: `apps/mobile-web/src/routes/definitions.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write live hook test**

Create `apps/mobile-web/src/features/live/useMobileGameRunEvents.test.tsx`:

```tsx
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useMobileGameRunEvents } from "./useMobileGameRunEvents";

type Listener = (event: MessageEvent) => void;

class MockEventSource {
  static instances: MockEventSource[] = [];
  listeners: Record<string, Listener[]> = {};
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners[type] = [...(this.listeners[type] ?? []), listener];
  }

  close = vi.fn();

  emit(type: string, data: unknown) {
    for (const listener of this.listeners[type] ?? []) {
      listener(new MessageEvent(type, { data: JSON.stringify(data) }));
    }
  }
}

afterEach(() => {
  MockEventSource.instances = [];
  vi.unstubAllGlobals();
});

describe("useMobileGameRunEvents", () => {
  it("collects events and closes after terminal events", async () => {
    vi.stubGlobal("EventSource", MockEventSource);
    const { result } = renderHook(() => useMobileGameRunEvents("run_1"));

    MockEventSource.instances[0].onopen?.();
    MockEventSource.instances[0].emit("phase_started", { id: 1, type: "phase_started", payload: { phase: "day" } });
    MockEventSource.instances[0].emit("game_completed", { id: 2, type: "game_completed", payload: { winner: "villagers" } });

    await waitFor(() => {
      expect(result.current.connectionState).toBe("closed");
      expect(result.current.events).toHaveLength(2);
    });
    expect(MockEventSource.instances[0].close).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run live hook test and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/features/live/useMobileGameRunEvents.test.tsx
```

Expected: FAIL because the hook does not exist.

- [ ] **Step 3: Implement live hook**

Create `apps/mobile-web/src/features/live/useMobileGameRunEvents.ts`:

```ts
import { useEffect, useMemo, useState } from "react";

import { createRunEventSource } from "../../api/liveApi";
import type { LiveGameEvent } from "../../api/types";

export type MobileConnectionState =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "error"
  | "closed";

const EVENT_TYPES = [
  "run_created",
  "run_started",
  "game_started",
  "round_started",
  "phase_started",
  "action_requested",
  "model_response_delta",
  "action_parsed",
  "state_updated",
  "game_completed",
  "game_failed",
];

type StreamState = {
  runId: string | undefined;
  events: LiveGameEvent[];
  connectionState: MobileConnectionState;
};

export function useMobileGameRunEvents(runId: string | undefined) {
  const [streamState, setStreamState] = useState<StreamState>(() => ({
    runId,
    events: [],
    connectionState: runId ? "connecting" : "idle",
  }));

  if (streamState.runId !== runId) {
    setStreamState({
      runId,
      events: [],
      connectionState: runId ? "connecting" : "idle",
    });
  }

  useEffect(() => {
    if (!runId) {
      return;
    }

    let isActive = true;
    let lastEventId: number | undefined;
    let source: EventSource | null = null;
    let reconnectTimer: number | undefined;

    const closeSource = () => {
      if (!source) {
        return;
      }
      source.onopen = null;
      source.onerror = null;
      source.close();
      source = null;
    };

    const handleEvent = (message: MessageEvent) => {
      if (!isActive) {
        return;
      }
      let event: LiveGameEvent;
      try {
        event = JSON.parse(message.data) as LiveGameEvent;
      } catch {
        setStreamState((current) =>
          current.runId === runId ? { ...current, connectionState: "error" } : current,
        );
        return;
      }
      lastEventId = event.id;
      const isTerminal = event.type === "game_completed" || event.type === "game_failed";
      setStreamState((current) => {
        if (current.runId !== runId) {
          return current;
        }
        const nextEvents = current.events.some((item) => item.id === event.id)
          ? current.events
          : [...current.events, event].sort((a, b) => a.id - b.id);
        return {
          ...current,
          events: nextEvents,
          connectionState: isTerminal ? "closed" : current.connectionState,
        };
      });
      if (isTerminal) {
        isActive = false;
        closeSource();
      }
    };

    const connect = () => {
      closeSource();
      source = createRunEventSource(runId, lastEventId);
      source.onopen = () => {
        if (isActive) {
          setStreamState((current) =>
            current.runId === runId ? { ...current, connectionState: "open" } : current,
          );
        }
      };
      source.onerror = () => {
        if (!isActive) {
          return;
        }
        setStreamState((current) =>
          current.runId === runId ? { ...current, connectionState: "reconnecting" } : current,
        );
        closeSource();
        reconnectTimer = window.setTimeout(connect, 1200);
      };
      for (const eventType of EVENT_TYPES) {
        source.addEventListener(eventType, handleEvent);
      }
    };

    connect();

    return () => {
      isActive = false;
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
      }
      closeSource();
      setStreamState((current) =>
        current.runId === runId ? { ...current, connectionState: "closed" } : current,
      );
    };
  }, [runId]);

  const events = streamState.runId === runId ? streamState.events : [];
  const latestEvent = useMemo(() => events.at(-1) ?? null, [events]);
  const connectionState = streamState.runId === runId
    ? streamState.connectionState
    : runId
      ? "connecting"
      : "idle";

  return { connectionState, events, latestEvent };
}
```

- [ ] **Step 4: Write live page test**

Create `apps/mobile-web/src/pages/LivePage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { LivePage } from "./LivePage";

vi.mock("../api/gamesApi", () => ({
  getGameRun: vi.fn(async () => ({ run_id: "run_live", session_id: "session_live", status: "running", rule_set: { id: "classic_12", version: "1", name: "经典 12 人", player_count: 12, roles: [] } })),
}));

vi.mock("../features/live/useMobileGameRunEvents", () => ({
  useMobileGameRunEvents: () => ({
    connectionState: "open",
    latestEvent: { id: 1, type: "phase_started", payload: { phase: "day", round: 2 } },
    events: [{ id: 1, type: "phase_started", payload: { phase: "day", round: 2 } }],
  }),
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/live/run_live"]}>
        <Routes>
          <Route path="/live/:runId" element={<LivePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LivePage", () => {
  it("renders stage-first live information", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "实时舞台" })).toBeInTheDocument();
    expect(screen.getByText("连接正常")).toBeInTheDocument();
    expect(screen.getByText("phase_started")).toBeInTheDocument();
    expect(screen.getByText("经典 12 人")).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Implement live page and route**

Create `apps/mobile-web/src/pages/LivePage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { getGameRun } from "../api/gamesApi";
import { MobileButton } from "../components/MobileButton";
import { StatusBanner } from "../components/StatusBanner";
import { useMobileGameRunEvents } from "../features/live/useMobileGameRunEvents";

function connectionLabel(state: string) {
  if (state === "open") {
    return "连接正常";
  }
  if (state === "connecting") {
    return "正在连接";
  }
  if (state === "reconnecting") {
    return "正在重连";
  }
  if (state === "error") {
    return "连接中断";
  }
  return "连接已关闭";
}

export function LivePage() {
  const { runId } = useParams();
  const runQuery = useQuery({
    queryKey: ["mobile-game-run", runId],
    queryFn: () => getGameRun(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 15000;
    },
  });
  const { connectionState, events, latestEvent } = useMobileGameRunEvents(runId);
  const run = runQuery.data;
  const isTerminal = run?.status === "completed" || run?.status === "failed";

  return (
    <section className="mobile-page-section">
      <header className="mobile-live-header">
        <div>
          <p className="mobile-kicker">{run?.rule_set?.name ?? "实时对局"}</p>
          <h2>实时舞台</h2>
        </div>
        <span className="mobile-live-status">{connectionLabel(connectionState)}</span>
      </header>

      {runQuery.isError ? (
        <StatusBanner title="无法读取实时对局" tone="error">
          这个 run 不存在或后端暂时不可用。
        </StatusBanner>
      ) : null}

      <section className="mobile-stage-card">
        <p className="mobile-kicker">当前事件</p>
        <strong>{latestEvent?.type ?? "等待事件"}</strong>
        <p>{latestEvent ? JSON.stringify(latestEvent.payload ?? {}) : "后台正在准备对局。"}</p>
      </section>

      <section className="mobile-card">
        <h2>玩家快捷席位</h2>
        <div className="mobile-seat-strip" aria-label="玩家快捷席位">
          {Array.from({ length: run?.rule_set?.player_count ?? 12 }, (_, index) => (
            <span key={index + 1}>{index + 1}</span>
          ))}
        </div>
      </section>

      <section className="mobile-card">
        <h2>关键事件</h2>
        {events.slice(-3).map((event) => (
          <p key={event.id}>{event.id}. {event.type}</p>
        ))}
        {events.length === 0 ? <p>还没有收到事件。</p> : null}
      </section>

      {isTerminal && run ? (
        <Link className="mobile-link-button" to={`/playback/${run.session_id}`}>
          查看复盘
        </Link>
      ) : (
        <MobileButton onClick={() => window.location.reload()}>重连</MobileButton>
      )}
    </section>
  );
}
```

Modify `apps/mobile-web/src/routes/definitions.tsx` imports and live route:

```tsx
import { LivePage } from "../pages/LivePage";
```

Replace the live route:

```tsx
{ path: "live/:runId", element: <LivePage /> },
```

- [ ] **Step 6: Add live CSS**

Append to `apps/mobile-web/src/styles/index.css`:

```css
.mobile-live-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.mobile-live-header h2 {
  margin: 0;
  color: #ead8bf;
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 1.2rem;
}

.mobile-live-status {
  flex: 0 0 auto;
  border: 1px solid rgb(185 147 92 / 38%);
  border-radius: 999px;
  padding: 6px 10px;
  color: #f3dfbf;
  font-size: 0.78rem;
}

.mobile-stage-card {
  min-height: 160px;
  border: 1px solid rgb(185 147 92 / 56%);
  border-radius: 8px;
  padding: 16px;
  background:
    linear-gradient(180deg, rgb(31 39 44 / 88%), rgb(8 12 17 / 94%)),
    radial-gradient(circle at 50% 0%, rgb(201 157 95 / 16%), transparent 12rem);
}

.mobile-stage-card strong {
  display: block;
  margin-top: 8px;
  color: #f4e6d0;
  font-size: 1.1rem;
  overflow-wrap: anywhere;
}

.mobile-stage-card p {
  overflow-wrap: anywhere;
}

.mobile-seat-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 6px;
}

.mobile-seat-strip span {
  display: flex;
  aspect-ratio: 1;
  align-items: center;
  justify-content: center;
  border: 1px solid rgb(119 137 150 / 38%);
  border-radius: 8px;
  background: #101820;
}
```

- [ ] **Step 7: Run live tests and build**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/features/live/useMobileGameRunEvents.test.tsx src/pages/LivePage.test.tsx
pnpm --dir apps/mobile-web build
```

Expected: tests and build PASS.

- [ ] **Step 8: Commit live page**

```bash
git add apps/mobile-web/src
git commit -m "feat: add mobile live stage"
```

## Task 7: Implement Players, History, Playback, and Settings Pages

**Files:**
- Create: `apps/mobile-web/src/pages/PlayersPage.tsx`
- Create: `apps/mobile-web/src/pages/HistoryPage.tsx`
- Create: `apps/mobile-web/src/pages/PlaybackPage.tsx`
- Create: `apps/mobile-web/src/pages/SettingsPage.tsx`
- Create: `apps/mobile-web/src/pages/MobileSecondaryPages.test.tsx`
- Modify: `apps/mobile-web/src/routes/definitions.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write secondary page tests**

Create `apps/mobile-web/src/pages/MobileSecondaryPages.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { HistoryPage } from "./HistoryPage";
import { PlaybackPage } from "./PlaybackPage";
import { PlayersPage } from "./PlayersPage";
import { SettingsPage } from "./SettingsPage";

vi.mock("../api/playerProfilesApi", () => ({
  listPlayerProfiles: vi.fn(async () => ({ profiles: [{ id: "p1", display_name: "夜鸦", model: "deepseek-v4-flash", personality_id: "balanced", appearance_id: "default", avatar_image_url: "", short_description: "冷静观察者", favorite: true, tags: ["默认"], updated_at: "2026-06-18T00:00:00Z" }] })),
}));

vi.mock("../api/gamesApi", () => ({
  getGamePlayback: vi.fn(async () => ({ session_id: "session_1", timeline: [{ id: "t1", title: "第一夜", text: "夜幕降临", round: 1 }] })),
  listGames: vi.fn(async () => ({ sessions: [{ session_id: "session_1", status: "complete", winner: "villagers", round_count: 4, created_at: "2026-06-18T00:00:00Z", resumable: false }] })),
  listModelOptions: vi.fn(async () => ({ models: [{ id: "deepseek-v4-flash", label: "DeepSeek" }] })),
  listRuleSets: vi.fn(async () => ({ rule_sets: [{ id: "classic_12", version: "1", name: "经典 12 人", player_count: 12, roles: [] }] })),
}));

vi.mock("../api/healthApi", () => ({
  getHealth: vi.fn(async () => ({ status: "ok" })),
}));

function renderWithClient(ui: ReactNode, path = "/") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("mobile secondary pages", () => {
  it("renders player library", async () => {
    renderWithClient(<PlayersPage />);
    expect(await screen.findByText("夜鸦")).toBeInTheDocument();
  });

  it("renders history cards", async () => {
    renderWithClient(<HistoryPage />);
    expect(await screen.findByText("session_1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "复盘" })).toHaveAttribute("href", "/playback/session_1");
  });

  it("renders playback timeline", async () => {
    renderWithClient(
      <Routes>
        <Route path="/playback/:sessionId" element={<PlaybackPage />} />
      </Routes>,
      "/playback/session_1",
    );
    expect(await screen.findByText("第一夜")).toBeInTheDocument();
  });

  it("renders settings health and defaults", async () => {
    renderWithClient(<SettingsPage />);
    expect(await screen.findByText("API 正常")).toBeInTheDocument();
    expect(screen.getByText("经典 12 人")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run secondary tests and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/MobileSecondaryPages.test.tsx
```

Expected: FAIL because page files do not exist.

- [ ] **Step 3: Implement players page**

Create `apps/mobile-web/src/pages/PlayersPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listPlayerProfiles } from "../api/playerProfilesApi";
import { StatusBanner } from "../components/StatusBanner";

export function PlayersPage() {
  const playersQuery = useQuery({
    queryKey: ["mobile-player-profiles"],
    queryFn: listPlayerProfiles,
  });

  return (
    <section className="mobile-page-section">
      <header className="mobile-card">
        <p className="mobile-kicker">玩家库</p>
        <h2>虚拟玩家</h2>
        <p>浏览玩家档案，并从自定义开局中挑选阵容。</p>
      </header>

      {playersQuery.isError ? (
        <StatusBanner title="玩家库不可用" tone="error">
          玩家档案数据库暂时不可用，请稍后重试。
        </StatusBanner>
      ) : null}

      <section className="mobile-card">
        {playersQuery.isPending ? <p>正在读取玩家库...</p> : null}
        {playersQuery.data?.profiles.map((profile) => (
          <article className="mobile-list-row" key={profile.id}>
            <div>
              <strong>{profile.display_name}</strong>
              <p>{profile.short_description || profile.model}</p>
            </div>
            <span>{profile.favorite ? "常用" : "档案"}</span>
          </article>
        ))}
        {playersQuery.data?.profiles.length === 0 ? <p>暂无玩家档案。</p> : null}
      </section>

      <Link className="mobile-link-button" to="/custom-game">
        用这些玩家开局
      </Link>
    </section>
  );
}
```

- [ ] **Step 4: Implement history page**

Create `apps/mobile-web/src/pages/HistoryPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listGames } from "../api/gamesApi";
import { StatusBanner } from "../components/StatusBanner";

export function HistoryPage() {
  const gamesQuery = useQuery({
    queryKey: ["mobile-games"],
    queryFn: listGames,
  });

  return (
    <section className="mobile-page-section">
      <header className="mobile-card">
        <p className="mobile-kicker">历史</p>
        <h2>对局记录</h2>
      </header>

      {gamesQuery.isError ? (
        <StatusBanner title="历史不可用" tone="error">
          无法读取历史对局，请确认后端正在运行。
        </StatusBanner>
      ) : null}

      <section className="mobile-card">
        {gamesQuery.isPending ? <p>正在读取历史...</p> : null}
        {gamesQuery.data?.sessions.map((session) => (
          <article className="mobile-list-row" key={session.session_id}>
            <div>
              <strong>{session.session_id}</strong>
              <p>{session.round_count} 轮 · {session.winner ?? "未记录胜方"}</p>
            </div>
            <Link to={`/playback/${session.session_id}`}>复盘</Link>
          </article>
        ))}
        {gamesQuery.data?.sessions.length === 0 ? <p>暂无历史对局。</p> : null}
      </section>
    </section>
  );
}
```

- [ ] **Step 5: Implement playback page**

Create `apps/mobile-web/src/pages/PlaybackPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { getGamePlayback } from "../api/gamesApi";
import { StatusBanner } from "../components/StatusBanner";

export function PlaybackPage() {
  const { sessionId } = useParams();
  const playbackQuery = useQuery({
    queryKey: ["mobile-playback", sessionId],
    queryFn: () => getGamePlayback(sessionId!),
    enabled: Boolean(sessionId),
  });
  const timeline = playbackQuery.data?.timeline ?? [];

  return (
    <section className="mobile-page-section">
      <header className="mobile-card">
        <p className="mobile-kicker">复盘</p>
        <h2>{sessionId}</h2>
      </header>

      {playbackQuery.isError ? (
        <StatusBanner title="复盘不可用" tone="error">
          无法读取这场对局的复盘。
        </StatusBanner>
      ) : null}

      <section className="mobile-card">
        {playbackQuery.isPending ? <p>正在读取复盘...</p> : null}
        {timeline.map((item, index) => (
          <article className="mobile-timeline-item" key={item.id ?? index}>
            <strong>{item.title ?? `事件 ${index + 1}`}</strong>
            <p>{item.text ?? ""}</p>
          </article>
        ))}
        {!playbackQuery.isPending && timeline.length === 0 ? <p>这场对局暂无移动端时间线。</p> : null}
      </section>
    </section>
  );
}
```

- [ ] **Step 6: Implement settings page**

Create `apps/mobile-web/src/pages/SettingsPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";

import { getHealth } from "../api/healthApi";
import { listModelOptions, listRuleSets } from "../api/gamesApi";
import { StatusBanner } from "../components/StatusBanner";

export function SettingsPage() {
  const healthQuery = useQuery({ queryKey: ["mobile-health"], queryFn: getHealth });
  const rulesQuery = useQuery({ queryKey: ["mobile-rule-sets"], queryFn: listRuleSets });
  const modelsQuery = useQuery({ queryKey: ["mobile-model-options"], queryFn: listModelOptions });

  return (
    <section className="mobile-page-section">
      <header className="mobile-card">
        <p className="mobile-kicker">设置</p>
        <h2>连接与默认项</h2>
      </header>

      {healthQuery.isError ? (
        <StatusBanner title="API 不可用" tone="error">
          当前无法连接后端。
        </StatusBanner>
      ) : (
        <StatusBanner title={healthQuery.data?.status === "ok" ? "API 正常" : "正在检查"} tone="success">
          后端地址使用当前 Vite 代理的 `/api`。
        </StatusBanner>
      )}

      <section className="mobile-card">
        <h2>默认规则</h2>
        <p>{rulesQuery.data?.rule_sets[0]?.name ?? "正在读取规则..."}</p>
      </section>

      <section className="mobile-card">
        <h2>默认模型</h2>
        <p>{modelsQuery.data?.models[0]?.label ?? "正在读取模型..."}</p>
      </section>
    </section>
  );
}
```

- [ ] **Step 7: Wire routes**

Modify `apps/mobile-web/src/routes/definitions.tsx` imports:

```tsx
import { HistoryPage } from "../pages/HistoryPage";
import { PlaybackPage } from "../pages/PlaybackPage";
import { PlayersPage } from "../pages/PlayersPage";
import { SettingsPage } from "../pages/SettingsPage";
```

Replace route elements:

```tsx
{ path: "players", element: <PlayersPage /> },
{ path: "history", element: <HistoryPage /> },
{ path: "settings", element: <SettingsPage /> },
{ path: "playback/:sessionId", element: <PlaybackPage /> },
```

- [ ] **Step 8: Add secondary page CSS**

Append to `apps/mobile-web/src/styles/index.css`:

```css
.mobile-timeline-item {
  position: relative;
  padding: 0 0 14px 16px;
  border-left: 1px solid rgb(185 147 92 / 34%);
}

.mobile-timeline-item::before {
  position: absolute;
  top: 3px;
  left: -5px;
  width: 9px;
  height: 9px;
  content: "";
  border: 1px solid rgb(185 147 92 / 72%);
  background: #101820;
  transform: rotate(45deg);
}

.mobile-timeline-item strong {
  display: block;
  color: #f3dfbf;
}
```

- [ ] **Step 9: Run secondary page tests and build**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/MobileSecondaryPages.test.tsx
pnpm --dir apps/mobile-web build
```

Expected: tests and build PASS.

- [ ] **Step 10: Commit secondary pages**

```bash
git add apps/mobile-web/src
git commit -m "feat: add mobile secondary pages"
```

## Task 8: Full Validation, Responsive QA, and Documentation Cleanup

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Inspect: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Update architecture docs**

Add `apps/mobile-web` to `docs/architecture.md`:

```markdown
- `apps/mobile-web`: independent Vite React mobile SPA consuming the same API, optimized for phone portrait layouts on `http://localhost:5174`
```

Add this request-flow note:

```markdown
The mobile SPA uses the same `/api/v1/...` backend paths as the desktop SPA through its own Vite proxy. It owns its routes and CSS independently from `apps/web`.
```

- [ ] **Step 2: Run all mobile checks**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run
pnpm --dir apps/mobile-web lint
pnpm --dir apps/mobile-web build
```

Expected: all commands PASS.

- [ ] **Step 3: Run existing desktop web checks**

Run:

```bash
pnpm --dir apps/web test -- --run
pnpm --dir apps/web build
```

Expected: both commands PASS, proving the mobile app did not break the existing web.

- [ ] **Step 4: Start mobile dev server for visual QA**

Run:

```bash
pnpm --dir apps/mobile-web dev --host 127.0.0.1 --port 5174
```

Expected: Vite reports local URL `http://127.0.0.1:5174/`.

- [ ] **Step 5: Visual QA checklist**

Open `http://127.0.0.1:5174/` and inspect these viewport widths:

```text
360x740
390x844
430x932
480x900
```

Confirm:

- Bottom tabs stay visible and do not cover the final content row.
- The one-click start button is at least 44px tall.
- The custom wizard action bar remains usable on all four widths.
- The live page stage card appears before seat and event summaries.
- Long session IDs and player names wrap inside cards without horizontal overflow.
- Viewports wider than 480px center the mobile shell.

- [ ] **Step 6: Stop dev server**

Stop the foreground Vite server with `Ctrl-C`.

Expected: the terminal returns to the shell prompt.

- [ ] **Step 7: Commit validation docs**

```bash
git add README.md docs/architecture.md
git commit -m "docs: document mobile web runtime"
```

- [ ] **Step 8: Final status check**

Run:

```bash
git status --short
```

Expected: no unstaged or uncommitted changes from the mobile implementation.
