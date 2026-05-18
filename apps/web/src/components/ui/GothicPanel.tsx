import type { CSSProperties, HTMLAttributes } from "react";

type GothicPanelElement = "article" | "aside" | "div" | "section";

type GothicPanelStyle = CSSProperties & {
  "--gothic-panel-base-opacity"?: number;
};

export type GothicPanelProps = HTMLAttributes<HTMLElement> & {
  as?: GothicPanelElement;
  baseOpacity?: number;
  contentClassName?: string;
  size?: "1" | "2" | "3";
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

const ornaments = ["top", "right", "bottom", "left"] as const;

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function GothicPanel({
  as: Component = "div",
  baseOpacity,
  children,
  className,
  contentClassName,
  size = "2",
  style,
  ...props
}: GothicPanelProps) {
  const panelStyle: GothicPanelStyle = { ...style };

  if (baseOpacity !== undefined) {
    panelStyle["--gothic-panel-base-opacity"] = baseOpacity;
  }

  return (
    <Component
      className={cx("gothic-panel", gothicPanelSizeClass(size), className)}
      style={panelStyle}
      {...props}
    >
      <div aria-hidden="true" className="gothic-panel-center" />
      <div aria-hidden="true" className="gothic-panel-frame">
        {framePieces.map((piece) => (
          <span
            className={cx(
              "gothic-panel-frame-piece",
              `gothic-panel-${piece}`,
            )}
            key={piece}
          />
        ))}
      </div>
      {ornaments.map((ornament) => (
        <div
          aria-hidden="true"
          className={cx(
            "gothic-panel-ornament",
            `gothic-panel-ornament-${ornament}`,
          )}
          key={ornament}
        />
      ))}
      <div className={cx("gothic-panel-content", contentClassName)}>
        {children}
      </div>
    </Component>
  );
}

function gothicPanelSizeClass(size: NonNullable<GothicPanelProps["size"]>) {
  return size === "1"
    ? "gothic-panel-sm"
    : size === "3"
      ? "gothic-panel-lg"
      : "gothic-panel-md";
}
