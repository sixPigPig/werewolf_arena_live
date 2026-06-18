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
