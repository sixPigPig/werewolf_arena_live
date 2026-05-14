import {
  cloneElement,
  isValidElement,
  type ButtonHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";

type ButtonTone =
  | "amber"
  | "cyan"
  | "gray"
  | "green"
  | "orange"
  | "pink"
  | "red"
  | "violet";

export type ButtonIntent =
  | "default"
  | "info"
  | "primary"
  | "danger"
  | "success"
  | "warning";

export type ButtonSkin = "default" | "gothic";

type ChildWithClassName = {
  className?: string;
  children?: ReactNode;
  [key: string]: unknown;
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  asChild?: boolean;
  color?: ButtonTone;
  highContrast?: boolean;
  intent?: ButtonIntent;
  loading?: boolean;
  size?: "1" | "2" | "3";
  skin?: ButtonSkin;
  variant?: "solid" | "surface" | "soft";
};

export function Button({
  asChild: renderAsChild = false,
  children,
  className,
  color = "gray",
  disabled,
  highContrast,
  intent,
  loading,
  size = "2",
  skin = "default",
  type = "button",
  variant = "solid",
  ...props
}: ButtonProps) {
  const content = loading ? "处理中..." : children;

  if (skin === "gothic") {
    const gothicIntent = resolveGothicIntent(intent, color);
    const classes = cx(
      "gothic-button",
      gothicButtonSizeClass(size),
      className,
    );

    if (renderAsChild) {
      return renderGothicAsChild(children, classes, gothicIntent, {
        disabled: Boolean(disabled || loading),
        loading,
      });
    }

    return (
      <button
        className={classes}
        data-intent={gothicIntent}
        disabled={disabled || loading}
        type={type}
        {...props}
      >
        {renderGothicContent(content)}
      </button>
    );
  }

  const sizeClass = buttonSizeClass(size);
  const toneClass = buttonTone(color, variant, Boolean(highContrast));
  const classes = cx(
    "inline-flex shrink-0 items-center justify-center gap-2 rounded-md border font-semibold transition focus:outline-none focus:ring-2 focus:ring-amber-300/70 disabled:cursor-not-allowed disabled:opacity-55",
    sizeClass,
    toneClass,
    className,
  );

  if (renderAsChild) {
    return asChild(content, classes, (fallbackClassName) => (
      <span className={fallbackClassName}>{content}</span>
    ));
  }

  return (
    <button
      className={classes}
      disabled={disabled || loading}
      type={type}
      {...props}
    >
      {content}
    </button>
  );
}

const gothicIntentFromColor: Record<ButtonTone, ButtonIntent> = {
  amber: "warning",
  cyan: "info",
  gray: "default",
  green: "success",
  orange: "warning",
  pink: "primary",
  red: "danger",
  violet: "primary",
};

function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function mergeChildClassName(
  child: ReactElement<{ className?: string }>,
  className: string,
) {
  return cloneElement(child, {
    className: cx(className, child.props.className),
  });
}

function asChild(
  children: ReactNode,
  className: string,
  fallback: (className: string) => ReactElement,
) {
  if (isValidElement<{ className?: string }>(children)) {
    return mergeChildClassName(children, className);
  }

  return fallback(className);
}

function resolveGothicIntent(
  intent: ButtonIntent | undefined,
  color: ButtonTone,
) {
  return intent ?? gothicIntentFromColor[color];
}

function buttonSizeClass(size: NonNullable<ButtonProps["size"]>) {
  return size === "1" ? "h-8 px-3 text-sm" : size === "3" ? "h-12 px-5" : "h-10 px-4";
}

function gothicButtonSizeClass(size: NonNullable<ButtonProps["size"]>) {
  return size === "1"
    ? "gothic-button-sm"
    : size === "3"
      ? "gothic-button-lg"
      : "gothic-button-md";
}

function renderGothicContent(content: ReactNode) {
  return (
    <span className="gothic-button-content">
      <span className="gothic-button-label">{content}</span>
    </span>
  );
}

function renderGothicAsChild(
  children: ReactNode,
  className: string,
  intent: ButtonIntent,
  options: { disabled: boolean; loading?: boolean },
) {
  if (isValidElement<ChildWithClassName>(children)) {
    return cloneElement(children, {
      "aria-disabled": options.disabled || undefined,
      children: renderGothicContent(
        options.loading ? "处理中..." : children.props.children,
      ),
      className: cx(className, children.props.className),
      "data-intent": intent,
    });
  }

  return (
    <span
      aria-disabled={options.disabled || undefined}
      className={className}
      data-intent={intent}
    >
      {renderGothicContent(options.loading ? "处理中..." : children)}
    </span>
  );
}

function buttonTone(
  color: ButtonTone,
  variant: string,
  highContrast: boolean,
) {
  if (highContrast || variant === "solid") {
    if (color === "amber") {
      return "border-amber-300/65 bg-amber-300 text-slate-950 hover:bg-amber-200";
    }
    if (color === "red") {
      return "border-red-300/65 bg-red-500 text-white hover:bg-red-400";
    }

    return "border-slate-200/70 bg-slate-100 text-slate-950 hover:bg-white";
  }

  if (color === "amber") {
    return "border-amber-300/35 bg-transparent text-amber-100 hover:border-amber-200/65";
  }
  if (color === "red") {
    return "border-red-300/35 bg-transparent text-red-100 hover:border-red-200/65";
  }

  return "border-slate-500/35 bg-transparent text-slate-100 hover:border-slate-200/65";
}
