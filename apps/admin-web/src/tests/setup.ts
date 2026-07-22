import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

configure({ asyncUtilTimeout: 10_000 });

const browserGetComputedStyle = window.getComputedStyle.bind(window);
window.getComputedStyle = (element: Element) => browserGetComputedStyle(element);

Object.defineProperty(window, "matchMedia", {
  configurable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    addEventListener: vi.fn(),
    addListener: vi.fn(),
    dispatchEvent: vi.fn(),
    matches: false,
    media: query,
    onchange: null,
    removeEventListener: vi.fn(),
    removeListener: vi.fn(),
  })),
  writable: true,
});

class TestResizeObserver implements ResizeObserver {
  disconnect = vi.fn();
  observe = vi.fn();
  unobserve = vi.fn();
}

vi.stubGlobal("ResizeObserver", TestResizeObserver);
