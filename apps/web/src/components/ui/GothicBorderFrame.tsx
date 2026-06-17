import {
  createElement,
  forwardRef,
  type HTMLAttributes,
} from "react";

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

export const GothicBorderFrame = forwardRef<HTMLElement, GothicBorderFrameProps>(
  function GothicBorderFrame(
    {
      as: Component = "div",
      children,
      className,
      contentClassName,
      density = "default",
      ...props
    },
    ref,
  ) {
    return createElement(
      Component,
      {
        className: cx(
          "gothic-border-frame",
          `gothic-border-frame-${density}`,
          className,
        ),
        ref,
        ...props,
      },
      <div aria-hidden="true" className="gothic-border-frame-decoration">
        {framePieces.map((piece) => (
          <span
            className={cx(
              "gothic-border-frame-piece",
              `gothic-border-frame-${piece}`,
            )}
            key={piece}
          />
        ))}
      </div>,
      <div className={cx("gothic-border-frame-content", contentClassName)}>
        {children}
      </div>,
    );
  },
);
