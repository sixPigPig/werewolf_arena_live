import { waitFor } from "@testing-library/react";

type ClickUser = {
  click: (element: Element) => Promise<void>;
};

export async function selectAntdOption(
  user: ClickUser,
  control: HTMLElement,
  optionName: string | RegExp,
) {
  await user.click(control);
  const option = await waitFor(() => {
    const candidate = getOpenAntdOptions().find((element) => {
      const text = element.textContent ?? "";
      return typeof optionName === "string"
        ? text.includes(optionName)
        : optionName.test(text);
    });
    if (!candidate) {
      throw new Error(`Ant Design option not found: ${String(optionName)}`);
    }
    return candidate;
  });
  await user.click(option);
}

export function getOpenAntdOptions() {
  return Array.from(
    document.querySelectorAll<HTMLElement>(
      ".ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option",
    ),
  );
}

export function expectAntdSelectLabel(
  control: HTMLElement,
  label: string | RegExp,
) {
  const select = control.closest(".ant-select");
  expect(select).not.toBeNull();
  if (typeof label === "string") {
    expect(select).toHaveTextContent(label);
  } else {
    expect(select?.textContent ?? "").toMatch(label);
  }
}
