import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VirtualPlayerLibrary } from "./VirtualPlayerLibrary";
import { SYSTEM_PLAYER_AVATARS } from "../systemPlayerAvatars";
import type { ModelOption, PlayerProfileRequest } from "../types";

const modelOptions: ModelOption[] = [
  { id: "deepseek-chat", label: "DeepSeek · deepseek-chat" },
];

function renderLibrary(
  overrides: Partial<Parameters<typeof VirtualPlayerLibrary>[0]> = {},
) {
  const props = {
    profiles: [],
    modelOptions,
    isLoading: false,
    isError: false,
    isModelOptionsError: false,
    isSaving: false,
    onUploadAvatar: vi.fn().mockResolvedValue({
      avatar_image_url: "/api/v1/player-profiles/avatar/dropped.png",
      avatar_image_mime: "image/png",
    }),
    onCreateProfile: vi.fn<() => Promise<unknown>>().mockResolvedValue({}),
    onUpdateProfile: vi.fn<() => Promise<unknown>>().mockResolvedValue({}),
    onDeleteProfile: vi.fn<() => Promise<unknown>>().mockResolvedValue({}),
    ...overrides,
  };

  render(<VirtualPlayerLibrary {...props} />);

  return props;
}

describe("VirtualPlayerLibrary", () => {
  it("exposes the create action through a typed callback", async () => {
    const onCreateActionReady = vi.fn();
    renderLibrary({ onCreateActionReady });

    expect(onCreateActionReady).toHaveBeenCalledWith(expect.any(Function));
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
    const openCreate = onCreateActionReady.mock.calls[0][0] as () => void;
    try {
      await act(async () => openCreate());

      const nameInput = screen.getByLabelText("虚拟玩家昵称");
      expect(nameInput).toHaveFocus();
      expect(scrollIntoView).toHaveBeenCalledWith({
        behavior: "smooth",
        block: "start",
      });
    } finally {
      Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
        configurable: true,
        value: originalScrollIntoView,
      });
    }
  });

  it("defaults a new player to a random system avatar", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    const onCreateProfile = vi
      .fn<(request: PlayerProfileRequest) => Promise<unknown>>()
      .mockResolvedValue({});
    renderLibrary({ onCreateProfile });

    await userEvent.click(screen.getByRole("button", { name: "新建虚拟玩家" }));
    expect(
      screen
        .getByTestId("virtual-player-avatar-dropzone")
        .querySelector("img"),
    ).toHaveAttribute("src", SYSTEM_PLAYER_AVATARS[0].imageUrl);

    await userEvent.click(screen.getByRole("button", { name: "保存虚拟玩家" }));

    await waitFor(() =>
      expect(onCreateProfile).toHaveBeenCalledWith(
        expect.objectContaining({
          avatar_image_url: SYSTEM_PLAYER_AVATARS[0].imageUrl,
          avatar_image_mime: "image/png",
        }),
      ),
    );
  });

  it("allows choosing a different system avatar", async () => {
    const onCreateProfile = vi
      .fn<(request: PlayerProfileRequest) => Promise<unknown>>()
      .mockResolvedValue({});
    renderLibrary({ onCreateProfile });

    await userEvent.click(screen.getByRole("button", { name: "新建虚拟玩家" }));
    await userEvent.click(
      screen.getByRole("button", {
        name: `选择内设形象 ${SYSTEM_PLAYER_AVATARS[2].label}`,
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "保存虚拟玩家" }));

    await waitFor(() =>
      expect(onCreateProfile).toHaveBeenCalledWith(
        expect.objectContaining({
          avatar_image_url: SYSTEM_PLAYER_AVATARS[2].imageUrl,
          avatar_image_mime: "image/png",
        }),
      ),
    );
  });

  it("uploads a player avatar when an image file is dropped on the avatar area", async () => {
    const onUploadAvatar = vi.fn().mockResolvedValue({
      avatar_image_url: "/api/v1/player-profiles/avatar/dropped.png",
      avatar_image_mime: "image/png",
    });
    const onCreateProfile = vi
      .fn<(request: PlayerProfileRequest) => Promise<unknown>>()
      .mockResolvedValue({});
    renderLibrary({ onCreateProfile, onUploadAvatar });

    await userEvent.click(screen.getByRole("button", { name: "新建虚拟玩家" }));
    const droppedFile = new File(
      [new Uint8Array([137, 80, 78, 71])],
      "dropped.png",
      { type: "image/png" },
    );

    fireEvent.drop(screen.getByTestId("virtual-player-avatar-dropzone"), {
      dataTransfer: { files: [droppedFile] },
    });

    await waitFor(() => expect(onUploadAvatar).toHaveBeenCalledWith(droppedFile));
    expect(await screen.findByRole("img")).toHaveAttribute(
      "src",
      "/api/v1/player-profiles/avatar/dropped.png",
    );
  });
});
