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
    const linkAttributes = getSafeLinkAttributes(props);

    return (
      <Button
        asChild
        color={color}
        intent={intent}
        size={size}
        skin="gothic"
        variant={variant}
        {...props}
      >
        <Link aria-label={ariaLabel} {...linkAttributes} to={to}>
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

function getSafeLinkAttributes(props: ButtonProps) {
  const linkAttributes: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(props)) {
    if (
      key === "onClick" ||
      key.startsWith("data-") ||
      key.startsWith("aria-")
    ) {
      linkAttributes[key] = value;
    }
  }

  return linkAttributes;
}
