import "@testing-library/jest-dom/vitest";
import "antd-mobile/es/global";
import { configure } from "@testing-library/react";

configure({ asyncUtilTimeout: 3000 });

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
