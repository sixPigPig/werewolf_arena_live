const MAX_LAYOUT_WIDTH = 480;

export function updateRootFontSize(width = window.innerWidth) {
  const clampedWidth = Math.min(Math.max(width, 320), MAX_LAYOUT_WIDTH);
  document.documentElement.style.fontSize = `${clampedWidth / 10}px`;
}

export function installRootFontSize() {
  updateRootFontSize();
  const handleResize = () => updateRootFontSize();
  window.addEventListener("resize", handleResize);
  window.addEventListener("orientationchange", handleResize);

  return () => {
    window.removeEventListener("resize", handleResize);
    window.removeEventListener("orientationchange", handleResize);
  };
}
