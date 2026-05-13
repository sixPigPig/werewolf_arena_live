import type { MouseEvent, ReactNode } from "react";
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
  disabled,
  loading,
  onClick,
  ...props
}: ArenaNavButtonProps) {
  if (to) {
    const linkAttributes = getSafeLinkAttributes(props);
    const linkIsDisabled = Boolean(disabled || loading);
    const handleLinkClick = (event: MouseEvent<HTMLAnchorElement>) => {
      if (linkIsDisabled) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }

      onClick?.(event as unknown as MouseEvent<HTMLButtonElement>);
    };

    return (
      <Button
        asChild
        color={color}
        disabled={disabled}
        intent={intent}
        loading={loading}
        size={size}
        skin="gothic"
        variant={variant}
        {...props}
      >
        <Link
          aria-label={ariaLabel}
          {...linkAttributes}
          onClick={handleLinkClick}
          tabIndex={linkIsDisabled ? -1 : undefined}
          to={to}
        >
          {children}
        </Link>
      </Button>
    );
  }

  return (
    <Button
      color={color}
      disabled={disabled}
      intent={intent}
      loading={loading}
      onClick={onClick}
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
      key.startsWith("data-") ||
      key.startsWith("aria-")
    ) {
      linkAttributes[key] = value;
    }
  }

  return linkAttributes;
}
