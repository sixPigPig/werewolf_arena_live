import type { ReactNode } from "react";

import type { ButtonProps } from "../../components/ui";

export type ArenaNavTone = "default" | "nocturne" | "ornate";
export type ArenaNavDensity = "regular" | "compact";
export type ArenaNavBrandMode = "full" | "compact";
export type ArenaNavSurface = "transparent" | "frosted";
export type ArenaNavButtonTone = NonNullable<ButtonProps["color"]>;
export type ArenaNavButtonVariant = NonNullable<ButtonProps["variant"]>;
export type ArenaNavButtonSize = NonNullable<ButtonProps["size"]>;
export type ArenaNavSlot = ReactNode;
