import type { CSSProperties, HTMLAttributes } from "react";

type ContainerElement = "article" | "aside" | "div" | "section";

type GothicNightContainerStyle = CSSProperties & {
  "--gothic-night-container-base-opacity"?: number;
};

export type ContainerProps = HTMLAttributes<HTMLElement> & {
  as?: ContainerElement;
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

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function Container({
  as: Component = "div",
  baseOpacity,
  children,
  className,
  contentClassName,
  size = "2",
  style,
  ...props
}: ContainerProps) {
  const containerStyle: GothicNightContainerStyle = { ...style };

  if (baseOpacity !== undefined) {
    containerStyle["--gothic-night-container-base-opacity"] = baseOpacity;
  }

  return (
    <Component
      className={cx(
        "gothic-night-container",
        gothicNightContainerSizeClass(size),
        className,
      )}
      style={containerStyle}
      {...props}
    >
      <div aria-hidden="true" className="gothic-night-container-center" />
      <div aria-hidden="true" className="gothic-night-container-frame">
        {framePieces.map((piece) => (
          <span
            className={cx(
              "gothic-night-container-frame-piece",
              `gothic-night-container-${piece}`,
            )}
            key={piece}
          />
        ))}
      </div>
      <div aria-hidden="true" className="gothic-night-container-moon" />
      <div aria-hidden="true" className="gothic-night-container-branch-left" />
      <div aria-hidden="true" className="gothic-night-container-branch-right" />
      <div aria-hidden="true" className="gothic-night-container-smoke-bottom" />
      <div className={cx("gothic-night-container-content", contentClassName)}>
        {children}
      </div>
    </Component>
  );
}

function gothicNightContainerSizeClass(
  size: NonNullable<ContainerProps["size"]>,
) {
  return size === "1"
    ? "gothic-night-container-sm"
    : size === "3"
      ? "gothic-night-container-lg"
      : "gothic-night-container-md";
}
