import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Button, type ButtonProps } from "../../components/ui";

type ArenaNavButtonProps = Omit<
  ButtonProps,
  "asChild" | "children" | "size" | "skin"
> & {
  ariaLabel?: string;
  children: ReactNode;
  size?: ButtonProps["size"];
  to?: string;
};

export function ArenaNavButton({
  ariaLabel,
  children,
  color = "gray",
  intent,
  size = "1",
  to,
  type = "button",
  variant = "surface",
  ...props
}: ArenaNavButtonProps) {
  if (to) {
    return (
      <Button
        asChild
        color={color}
        intent={intent}
        size={size}
        skin="gothic"
        variant={variant}
      >
        <Link aria-label={ariaLabel} to={to}>
          {children}
        </Link>
      </Button>
    );
  }

  return (
    <Button
      color={color}
      intent={intent}
      size={size}
      skin="gothic"
      type={type}
      variant={variant}
      {...props}
    >
      {children}
    </Button>
  );
}
