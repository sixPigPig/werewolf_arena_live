import { screen } from "@testing-library/react";

export async function expectAdminNotification(title: string | RegExp) {
  const titleElement = await screen.findByText(title, {
    selector: ".ant-notification-notice-title",
  });
  const notice = titleElement.closest<HTMLElement>(".ant-notification-notice");

  expect(notice).not.toBeNull();
  expect(
    titleElement.closest(".ant-notification-bottomRight"),
  ).not.toBeNull();
  return notice!;
}
