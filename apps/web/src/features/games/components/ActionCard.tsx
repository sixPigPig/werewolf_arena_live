import { Flex, RadioCards, Text } from "@radix-ui/themes";
import type { ComponentProps } from "react";

import type { DebugItem } from "../types";

type ActionCardGroupProps = {
  ariaLabel: string;
  className?: string;
  columns?: ComponentProps<typeof RadioCards.Root>["columns"];
  emptyText?: string;
  items: DebugItem[];
  selectedItem: DebugItem | null;
  onSelect: (item: DebugItem) => void;
};

export function ActionCardGroup({
  ariaLabel,
  className,
  columns,
  emptyText,
  items,
  selectedItem,
  onSelect,
}: ActionCardGroupProps) {
  if (items.length === 0) {
    return emptyText ? (
      <p className={`${className ?? ""} text-sm text-slate-500`.trim()}>
        {emptyText}
      </p>
    ) : null;
  }

  const selectedValue = selectedItem?.id ?? "";

  return (
    <RadioCards.Root
      aria-label={ariaLabel}
      className={className}
      columns={columns}
      color="gray"
      gap="2"
      highContrast
      onValueChange={(value) => {
        const item = items.find((candidate) => candidate.id === value);
        if (item) {
          onSelect(item);
        }
      }}
      value={selectedValue}
      variant="surface"
    >
      {items.map((item) => {
        return (
          <RadioCards.Item
            aria-label={`${item.title} ${item.actor} 选择 ${item.choice ?? "无"}`}
            className="min-h-[4.5rem]"
            key={item.id}
            value={item.id}
          >
            <Flex direction="column" width="100%" height="100%">
              <Text
                as="span"
                className="break-words leading-5 text-slate-950"
                size="2"
                weight="bold"
              >
                {item.title}
              </Text>
              <Text
                as="span"
                className="min-w-0 break-words leading-5 text-slate-600"
                size="2"
              >
                {item.actor} 选择 {item.choice ?? "无"}
              </Text>
            </Flex>
          </RadioCards.Item>
        );
      })}
    </RadioCards.Root>
  );
}
