import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VirtualPlayerLibrary } from "./VirtualPlayerLibrary";
import { SYSTEM_PLAYER_AVATARS } from "../systemPlayerAvatars";
import type {
  ModelOption,
  PlayerProfileRequest,
  VirtualPlayerProfile,
} from "../types";

const modelOptions: ModelOption[] = [
  { id: "deepseek-chat", label: "DeepSeek · deepseek-chat" },
];

function profile(
  overrides: Partial<VirtualPlayerProfile>,
): VirtualPlayerProfile {
  return {
    id: "profile-1",
    owner_user_id: null,
    display_name: "冷静的阿夜",
    model: "deepseek-chat",
    personality_id: "cautious",
    personality_text: "谨慎观察局势。",
    short_description: "逻辑控场玩家",
    background_story: "",
    speaking_style: "",
    catchphrases: [],
    strategy_profile: "logic_leader",
    risk_tolerance: 3,
    bluffing_tendency: 3,
    trust_tendency: 3,
    leadership_tendency: 3,
    talkativeness: 3,
    example_messages: [],
    favorite: false,
    appearance_id: "default",
    avatar_prompt: "",
    avatar_image_url: "",
    avatar_image_mime: "",
    tags: [],
    created_at: "2026-05-16T00:00:00Z",
    updated_at: "2026-05-16T00:00:00Z",
    ...overrides,
  };
}

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

  it("saves rich virtual player settings from the dedicated editor", async () => {
    const user = userEvent.setup();
    const onCreateProfile = vi.fn().mockResolvedValue({});
    renderLibrary({ onCreateProfile });

    await user.click(screen.getByRole("button", { name: "新建虚拟玩家" }));
    await user.type(screen.getByLabelText("一句话简介"), "逻辑控场玩家");
    await user.type(screen.getByLabelText("背景故事"), "长期复盘高阶狼人杀对局。");
    await user.type(screen.getByLabelText("发言风格"), "分点列证据，最后给结论。");
    await user.type(screen.getByLabelText("常用表达"), "我先拆视角，票型不对劲");
    await user.selectOptions(screen.getByLabelText("策略模板"), "logic_leader");
    await user.clear(screen.getByLabelText("领导倾向"));
    await user.type(screen.getByLabelText("领导倾向"), "5");
    await user.type(screen.getByLabelText("示例发言"), "我认为 3 号视角漏了一层。");

    await user.click(screen.getByRole("button", { name: "保存虚拟玩家" }));

    expect(onCreateProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        short_description: "逻辑控场玩家",
        background_story: "长期复盘高阶狼人杀对局。",
        speaking_style: "分点列证据，最后给结论。",
        catchphrases: ["我先拆视角", "票型不对劲"],
        strategy_profile: "logic_leader",
        leadership_tendency: 5,
        example_messages: ["我认为 3 号视角漏了一层。"],
      }),
    );
  });

  it("shows backend default personality text in the prompt preview when personality text is blank", async () => {
    const user = userEvent.setup();
    renderLibrary();

    await user.click(screen.getByRole("button", { name: "新建虚拟玩家" }));
    await user.selectOptions(screen.getByLabelText("性格"), "cautious");

    expect(
      screen.getByText(/谨慎保守，优先收集信息，避免过早暴露关键判断。/),
    ).toBeInTheDocument();
  });

  it("normalizes empty and out-of-range tendency values before saving", async () => {
    const user = userEvent.setup();
    const onCreateProfile = vi.fn().mockResolvedValue({});
    renderLibrary({ onCreateProfile });

    await user.click(screen.getByRole("button", { name: "新建虚拟玩家" }));
    await user.clear(screen.getByLabelText("冒险倾向"));
    await user.clear(screen.getByLabelText("领导倾向"));
    await user.type(screen.getByLabelText("领导倾向"), "9");
    await user.click(screen.getByRole("button", { name: "保存虚拟玩家" }));

    expect(onCreateProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        risk_tolerance: 3,
        leadership_tendency: 5,
      }),
    );
  });

  it("copies a profile with rich virtual player fields", async () => {
    const user = userEvent.setup();
    const onCreateProfile = vi.fn().mockResolvedValue({});
    renderLibrary({
      onCreateProfile,
      profiles: [
        profile({
          id: "profile-rich-copy",
          display_name: "复制源阿夜",
          short_description: "社交控场",
          background_story: "长期观察关系线。",
          speaking_style: "先听姿态，再拆票型。",
          catchphrases: ["我先看关系线", "这票不自然"],
          strategy_profile: "social_reader",
          risk_tolerance: 2,
          bluffing_tendency: 4,
          trust_tendency: 5,
          leadership_tendency: 3,
          talkativeness: 4,
          example_messages: ["这轮我更看重 2 和 5 的互动。"],
          favorite: true,
        }),
      ],
    });

    await user.click(screen.getByRole("button", { name: "复制 复制源阿夜" }));

    await waitFor(() =>
      expect(onCreateProfile).toHaveBeenCalledWith(
        expect.objectContaining({
          display_name: "复制源阿夜 副本",
          short_description: "社交控场",
          background_story: "长期观察关系线。",
          speaking_style: "先听姿态，再拆票型。",
          catchphrases: ["我先看关系线", "这票不自然"],
          strategy_profile: "social_reader",
          risk_tolerance: 2,
          bluffing_tendency: 4,
          trust_tendency: 5,
          leadership_tendency: 3,
          talkativeness: 4,
          example_messages: ["这轮我更看重 2 和 5 的互动。"],
          favorite: true,
        }),
      ),
    );
  });

  it("updates an edited profile with rich virtual player fields", async () => {
    const user = userEvent.setup();
    const onUpdateProfile = vi.fn().mockResolvedValue({});
    renderLibrary({
      onUpdateProfile,
      profiles: [
        profile({
          id: "profile-rich-edit",
          display_name: "编辑源阿夜",
          short_description: "逻辑站边",
          background_story: "复盘过多场高阶局。",
          speaking_style: "旧发言风格",
          catchphrases: ["先拆视角", "票型有问题"],
          strategy_profile: "logic_leader",
          risk_tolerance: 4,
          bluffing_tendency: 2,
          trust_tendency: 3,
          leadership_tendency: 5,
          talkativeness: 4,
          example_messages: ["我认为 3 号视角漏了一层。"],
          favorite: true,
        }),
      ],
    });

    await user.click(screen.getByRole("button", { name: "编辑 编辑源阿夜" }));
    await user.clear(screen.getByLabelText("发言风格"));
    await user.type(screen.getByLabelText("发言风格"), "更新后先列证据再站边。");
    await user.click(screen.getByRole("button", { name: "保存虚拟玩家" }));

    await waitFor(() =>
      expect(onUpdateProfile).toHaveBeenCalledWith(
        "profile-rich-edit",
        expect.objectContaining({
          short_description: "逻辑站边",
          background_story: "复盘过多场高阶局。",
          speaking_style: "更新后先列证据再站边。",
          catchphrases: ["先拆视角", "票型有问题"],
          strategy_profile: "logic_leader",
          risk_tolerance: 4,
          bluffing_tendency: 2,
          trust_tendency: 3,
          leadership_tendency: 5,
          talkativeness: 4,
          example_messages: ["我认为 3 号视角漏了一层。"],
          favorite: true,
        }),
      ),
    );
  });

  it("filters virtual player cards with compact search", async () => {
    const user = userEvent.setup();
    renderLibrary({
      profiles: [
        profile({
          id: "profile-logic",
          display_name: "逻辑阿夜",
          short_description: "票型复盘控场",
          strategy_profile: "logic_leader",
          tags: ["控场"],
        }),
        profile({
          id: "profile-social",
          display_name: "社交月白",
          model: "MiniMax-M2.7",
          personality_id: "balanced",
          short_description: "情绪阅读玩家",
          strategy_profile: "social_reader",
          tags: ["关系线"],
        }),
      ],
    });

    expect(screen.getByText("逻辑阿夜")).toBeInTheDocument();
    expect(screen.getByText("社交月白")).toBeInTheDocument();

    await user.type(screen.getByLabelText("搜索虚拟玩家"), "logic_leader");

    expect(screen.getByText("逻辑阿夜")).toBeInTheDocument();
    expect(screen.queryByText("社交月白")).not.toBeInTheDocument();
  });

  it("filters virtual player cards to favorites only", async () => {
    const user = userEvent.setup();
    renderLibrary({
      profiles: [
        profile({
          id: "profile-favorite",
          display_name: "收藏阿夜",
          favorite: true,
        }),
        profile({
          id: "profile-normal",
          display_name: "普通月白",
          favorite: false,
        }),
      ],
    });

    await user.click(screen.getByRole("button", { name: "只看收藏" }));

    expect(screen.getByText("收藏阿夜")).toBeInTheDocument();
    expect(screen.queryByText("普通月白")).not.toBeInTheDocument();
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
