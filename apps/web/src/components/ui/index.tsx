/* eslint-disable react-refresh/only-export-components */
import {
  cloneElement,
  createContext,
  isValidElement,
  useContext,
  type ButtonHTMLAttributes,
  type ComponentPropsWithoutRef,
  type CSSProperties,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";

import { glassPanelClass } from "./glass";

export {
  Button,
  type ButtonIntent,
  type ButtonProps,
  type ButtonSkin,
} from "./Button";
export { Container, type ContainerProps } from "./Container";
export {
  GothicBorderFrame,
  type GothicBorderFrameProps,
} from "./GothicBorderFrame";
export { GothicPanel, type GothicPanelProps } from "./GothicPanel";

type Tone =
  | "amber"
  | "cyan"
  | "gray"
  | "green"
  | "orange"
  | "pink"
  | "red"
  | "violet";

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

export type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  color?: Tone;
  variant?: "surface" | "soft" | "solid";
};

export function Badge({
  children,
  className,
  color = "gray",
  variant = "surface",
  ...props
}: BadgeProps) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium",
        badgeTone(color, variant),
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
}

function badgeTone(color: Tone, variant: string) {
  const soft = variant !== "solid";
  const tones: Record<Tone, string> = {
    amber: soft
      ? "border-amber-300/35 text-amber-100"
      : "border-amber-300 bg-amber-300 text-slate-950",
    cyan: soft ? "border-cyan-300/35 text-cyan-100" : "border-cyan-300 bg-cyan-300 text-slate-950",
    gray: soft ? "border-slate-400/35 text-slate-100" : "border-slate-200 bg-slate-100 text-slate-950",
    green: soft ? "border-emerald-300/35 text-emerald-100" : "border-emerald-300 bg-emerald-300 text-slate-950",
    orange: soft ? "border-orange-300/35 text-orange-100" : "border-orange-300 bg-orange-300 text-slate-950",
    pink: soft ? "border-pink-300/35 text-pink-100" : "border-pink-300 bg-pink-300 text-slate-950",
    red: soft ? "border-red-300/35 text-red-100" : "border-red-300 bg-red-500 text-white",
    violet: soft ? "border-violet-300/35 text-violet-100" : "border-violet-300 bg-violet-300 text-slate-950",
  };

  return tones[color];
}

type CardProps = HTMLAttributes<HTMLElement> & {
  asChild?: boolean;
  size?: "1" | "2" | "3";
  variant?: "surface" | "soft";
};

export function Card({
  asChild: renderAsChild = false,
  children,
  className,
  size = "2",
  variant: _variant,
  ...props
}: CardProps) {
  void _variant;

  const padding = size === "1" ? "p-3" : size === "3" ? "p-6" : "p-4";
  const classes = cx(
    "rounded-lg text-slate-100",
    glassPanelClass,
    padding,
    className,
  );

  if (renderAsChild) {
    return asChild(children, classes, (fallbackClassName) => (
      <div className={fallbackClassName} {...props}>
        {children}
      </div>
    ));
  }

  return (
    <div className={classes} {...props}>
      {children}
    </div>
  );
}

function CalloutRoot({
  children,
  className,
  color = "gray",
  highContrast: _highContrast,
  size: _size,
  variant: _variant,
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  color?: Tone;
  highContrast?: boolean;
  size?: string;
  variant?: string;
}) {
  void _highContrast;
  void _size;
  void _variant;

  return (
    <div
      className={cx(
        "rounded-md border px-3 py-2 text-sm",
        color === "red"
          ? "border-red-300/35 text-red-100"
          : color === "green"
            ? "border-emerald-300/35 text-emerald-100"
            : "border-slate-300/35 text-slate-100",
        className,
      )}
      role={color === "red" ? "alert" : "status"}
      {...props}
    >
      {children}
    </div>
  );
}

function CalloutText({ children, className, ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p className={cx("leading-6", className)} {...props}>
      {children}
    </p>
  );
}

export const Callout = {
  Root: CalloutRoot,
  Text: CalloutText,
};

export function Text({
  as: Component = "span",
  children,
  className,
  color,
  size,
  weight,
  ...props
}: HTMLAttributes<HTMLElement> & {
  as?: "p" | "span";
  color?: string;
  size?: string;
  weight?: string;
}) {
  const colorClass = color === "gray" ? "text-slate-300" : "";
  const sizeClass = size === "3" ? "text-base" : size === "2" ? "text-sm" : "";
  const weightClass = weight === "bold" ? "font-bold" : weight === "medium" ? "font-medium" : "";

  return (
    <Component className={cx(colorClass, sizeClass, weightClass, className)} {...props}>
      {children}
    </Component>
  );
}

export function Heading({
  as: Component = "h2",
  children,
  className,
  size,
  ...props
}: HTMLAttributes<HTMLHeadingElement> & {
  as?: "h1" | "h2" | "h3" | "h4";
  size?: string;
}) {
  const sizeClass = size === "8" ? "text-5xl" : size === "6" ? "text-2xl" : "text-xl";

  return (
    <Component className={cx("font-semibold", sizeClass, className)} {...props}>
      {children}
    </Component>
  );
}

export function Flex({
  children,
  className,
  direction,
  gap,
  height,
  width,
  wrap,
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  direction?: "column" | "row";
  gap?: "1" | "2" | "3";
  height?: string;
  width?: string;
  wrap?: "wrap" | "nowrap";
}) {
  const style: CSSProperties = {
    height,
    width,
    ...props.style,
  };

  return (
    <div
      className={cx(
        "flex",
        direction === "column" ? "flex-col" : "flex-row",
        gap === "1" ? "gap-1" : gap === "2" ? "gap-2" : gap === "3" ? "gap-3" : "",
        wrap === "wrap" ? "flex-wrap" : "",
        className,
      )}
      {...props}
      style={style}
    >
      {children}
    </div>
  );
}

type RadioCardsContextValue = {
  value: string;
  onValueChange: (value: string) => void;
};

const RadioCardsContext = createContext<RadioCardsContextValue | null>(null);

type ResponsiveColumns = {
  initial?: string;
  sm?: string;
  md?: string;
  xl?: string;
};

function RadioCardsRoot({
  children,
  className,
  columns,
  color: _color,
  gap: _gap,
  highContrast: _highContrast,
  onValueChange,
  value,
  variant: _variant,
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  columns?: ResponsiveColumns;
  color?: Tone;
  gap?: string;
  highContrast?: boolean;
  onValueChange: (value: string) => void;
  value: string;
  variant?: string;
}) {
  void _color;
  void _gap;
  void _highContrast;
  void _variant;

  return (
    <RadioCardsContext.Provider value={{ value, onValueChange }}>
      <div
        className={cx("grid gap-2", columnClasses(columns), className)}
        role="radiogroup"
        {...props}
      >
        {children}
      </div>
    </RadioCardsContext.Provider>
  );
}

function columnClasses(columns?: ResponsiveColumns) {
  if (!columns) {
    return "";
  }

  return cx(
    columns.initial === "1" && "grid-cols-1",
    columns.initial === "2" && "grid-cols-2",
    columns.initial === "3" && "grid-cols-3",
    columns.sm === "2" && "sm:grid-cols-2",
    columns.sm === "3" && "sm:grid-cols-3",
    columns.md === "2" && "md:grid-cols-2",
    columns.md === "3" && "md:grid-cols-3",
    columns.xl === "3" && "xl:grid-cols-3",
  );
}

function RadioCardsItem({
  children,
  className,
  value,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { value: string }) {
  const context = useContext(RadioCardsContext);
  const checked = context?.value === value;

  return (
    <button
      aria-checked={checked}
      className={cx(
        "rounded-md border p-3 text-left transition focus:outline-none focus:ring-2 focus:ring-amber-300/70",
        checked
          ? "border-amber-200 ring-1 ring-amber-200/70"
          : "border-slate-200/30 hover:border-slate-100/70",
        className,
      )}
      onClick={() => context?.onValueChange(value)}
      role="radio"
      type="button"
      {...props}
    >
      {children}
    </button>
  );
}

export const RadioCards = {
  Root: RadioCardsRoot,
  Item: RadioCardsItem,
};

export const TextField = {
  Root({
    className,
    ...props
  }: InputHTMLAttributes<HTMLInputElement>) {
    return (
      <input
        className={cx(
          "h-10 rounded-md border border-slate-300/35 bg-transparent px-3 text-slate-100 outline-none placeholder:text-slate-300/70 focus:ring-2 focus:ring-amber-300/70",
          className,
        )}
        {...props}
      />
    );
  },
};

type TabsContextValue = {
  value: string;
  onValueChange?: (value: string) => void;
};

const TabsContext = createContext<TabsContextValue | null>(null);

function TabsRoot({
  children,
  onValueChange,
  value,
}: {
  children: ReactNode;
  onValueChange?: (value: string) => void;
  value: string;
}) {
  return (
    <TabsContext.Provider value={{ value, onValueChange }}>
      {children}
    </TabsContext.Provider>
  );
}

function TabsList({
  children,
  className,
  justify: _justify,
  ...props
}: HTMLAttributes<HTMLDivElement> & { justify?: string }) {
  void _justify;

  return (
    <div className={cx("flex gap-2", className)} role="tablist" {...props}>
      {children}
    </div>
  );
}

function TabsTrigger({
  children,
  className,
  value,
}: ButtonHTMLAttributes<HTMLButtonElement> & { value: string }) {
  const context = useContext(TabsContext);
  const selected = context?.value === value;

  return (
    <button
      aria-selected={selected}
      className={cx(
        "rounded-md border px-3 py-1.5 text-sm font-medium transition",
        selected
          ? "border-amber-200 text-amber-100"
          : "border-slate-300/25 text-slate-300",
        className,
      )}
      onClick={() => context?.onValueChange?.(value)}
      role="tab"
      type="button"
    >
      {children}
    </button>
  );
}

function TabsContent({
  children,
  className,
  value,
  ...props
}: HTMLAttributes<HTMLDivElement> & { value: string }) {
  const context = useContext(TabsContext);

  if (context?.value !== value) {
    return null;
  }

  return (
    <div className={className} role="tabpanel" {...props}>
      {children}
    </div>
  );
}

export const Tabs = {
  Root: TabsRoot,
  List: TabsList,
  Trigger: TabsTrigger,
  Content: TabsContent,
};

export function Switch({
  checked,
  className,
  onCheckedChange,
}: {
  checked: boolean;
  className?: string;
  color?: Tone;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <button
      aria-checked={checked}
      className={cx(
        "relative h-5 w-9 rounded-full border transition focus:outline-none focus:ring-2 focus:ring-amber-300/70",
        checked ? "border-amber-200" : "border-slate-400/50",
        className,
      )}
      onClick={() => onCheckedChange(!checked)}
      role="switch"
      type="button"
    >
      <span
        aria-hidden="true"
        className={cx(
          "absolute top-1/2 h-3.5 w-3.5 -translate-y-1/2 rounded-full bg-slate-100 transition",
          checked ? "left-[1.1rem]" : "left-0.5",
        )}
      />
    </button>
  );
}

function SegmentedControlRoot({
  children,
  onValueChange,
  value,
}: {
  children: ReactNode;
  "aria-label"?: string;
  onValueChange: (value: string) => void;
  value: string;
}) {
  return (
    <RadioCardsContext.Provider value={{ value, onValueChange }}>
      <div className="inline-flex overflow-hidden rounded-md border border-slate-500/35">
        {children}
      </div>
    </RadioCardsContext.Provider>
  );
}

function SegmentedControlItem({
  children,
  value,
}: {
  children: ReactNode;
  value: string;
}) {
  const context = useContext(RadioCardsContext);
  const selected = context?.value === value;

  return (
    <button
      aria-pressed={selected}
      className={cx(
        "h-9 px-3 text-sm font-semibold",
        selected ? "text-amber-100" : "text-slate-300",
      )}
      onClick={() => context?.onValueChange(value)}
      type="button"
    >
      {children}
    </button>
  );
}

export const SegmentedControl = {
  Root: SegmentedControlRoot,
  Item: SegmentedControlItem,
};

export const DataList = {
  Root({
    children,
    className,
    size: _size,
  }: HTMLAttributes<HTMLDListElement> & { size?: string }) {
    void _size;

    return <dl className={cx("grid gap-1 text-sm", className)}>{children}</dl>;
  },
  Item({ children }: HTMLAttributes<HTMLDivElement>) {
    return <div className="grid grid-cols-[4rem_minmax(0,1fr)] gap-2">{children}</div>;
  },
  Label({ children }: HTMLAttributes<HTMLElement>) {
    return <dt className="text-slate-400">{children}</dt>;
  },
  Value({ children, className }: HTMLAttributes<HTMLElement>) {
    return <dd className={cx("text-slate-100", className)}>{children}</dd>;
  },
};

export const Table = {
  Root({
    children,
    className,
    size: _size,
    variant: _variant,
  }: HTMLAttributes<HTMLTableElement> & { size?: string; variant?: string }) {
    void _size;
    void _variant;

    return (
      <table className={cx("w-full border-collapse text-sm", className)}>
        {children}
      </table>
    );
  },
  Header({ children }: HTMLAttributes<HTMLTableSectionElement>) {
    return <thead className="border-b border-slate-200/25 text-left text-slate-300">{children}</thead>;
  },
  Body({ children }: HTMLAttributes<HTMLTableSectionElement>) {
    return <tbody>{children}</tbody>;
  },
  Row({ children }: HTMLAttributes<HTMLTableRowElement>) {
    return <tr className="border-b border-slate-200/15 last:border-b-0">{children}</tr>;
  },
  ColumnHeaderCell({ children }: HTMLAttributes<HTMLTableCellElement>) {
    return <th className="px-2 py-2 font-semibold">{children}</th>;
  },
  Cell({ children, className }: HTMLAttributes<HTMLTableCellElement>) {
    return <td className={cx("px-2 py-2 text-slate-100", className)}>{children}</td>;
  },
};

export function Progress({
  max = 100,
  value = 0,
}: ComponentPropsWithoutRef<"progress"> & { color?: Tone }) {
  const percent = Math.max(0, Math.min(100, (Number(value) / Number(max)) * 100));

  return (
    <div className="h-2 overflow-hidden rounded-full border border-cyan-300/30">
      <div
        className="h-full rounded-full bg-cyan-300"
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}

export function SelectField({
  children,
  className,
  ...props
}: ComponentPropsWithoutRef<"select">) {
  return (
    <select
      className={cx(
        "h-10 rounded-md border border-slate-300/35 bg-transparent px-3 text-slate-100 outline-none focus:ring-2 focus:ring-amber-300/70",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}

export function Option(props: ComponentPropsWithoutRef<"option">) {
  return <option {...props} />;
}
