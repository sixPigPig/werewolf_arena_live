import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { VirtualPlayerLibrary } from "./VirtualPlayerLibrary";
import {
  SYSTEM_PLAYER_AVATARS,
  systemPlayerAvatarImageUrl,
} from "../systemPlayerAvatars";
import type {
  ModelOption,
  PlayerProfileRequest,
  VirtualPlayerProfile,
} from "../types";

const modelOptions: ModelOption[] = [
  { id: "deepseek-chat", label: "DeepSeek · deepseek-chat" },
];

type VirtualPlayerLibraryProps = Parameters<typeof VirtualPlayerLibrary>[0];

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
    avatar_asset_id: null,
    avatar_image_url: "",
    avatar_image_mime: "",
    tags: [],
    created_at: "2026-05-16T00:00:00Z",
    updated_at: "2026-05-16T00:00:00Z",
    ...overrides,
  };
}

function renderLibrary(
  overrides: Partial<VirtualPlayerLibraryProps> = {},
) {
  const onCreateActionReady = overrides.onCreateActionReady ?? vi.fn();
  const props: VirtualPlayerLibraryProps = {
    profiles: [],
    modelOptions,
    isLoading: false,
    isError: false,
    isModelOptionsError: false,
    isSaving: false,
    onUploadAvatar: vi.fn().mockResolvedValue({
      avatar_asset_id: "uploaded-dropped",
      avatar_image_url: "/api/v1/player-profiles/avatar/dropped.png",
      avatar_image_mime: "image/png",
    }),
    onCreateProfile: vi.fn<() => Promise<unknown>>().mockResolvedValue({}),
    onUpdateProfile: vi.fn<() => Promise<unknown>>().mockResolvedValue({}),
    onDeleteProfile: vi.fn<() => Promise<unknown>>().mockResolvedValue({}),
    onCreateActionReady,
    ...overrides,
  };

  render(<VirtualPlayerLibrary {...props} />);

  return props;
}

async function openCreateEditor(props: VirtualPlayerLibraryProps) {
  const onCreateActionReady = props.onCreateActionReady as ReturnType<typeof vi.fn>;
  const openCreate = onCreateActionReady.mock.calls.at(-1)?.[0] as
    | (() => void)
    | undefined;

  expect(openCreate).toBeTypeOf("function");
  await act(async () => openCreate?.());
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
    const props = renderLibrary({ onCreateProfile });

    await openCreateEditor(props);
    expect(
      screen
        .getByTestId("virtual-player-avatar-dropzone")
        .querySelector("img"),
    ).toHaveAttribute(
      "src",
      systemPlayerAvatarImageUrl(SYSTEM_PLAYER_AVATARS[0]),
    );

    await userEvent.click(screen.getByRole("button", { name: "保存虚拟玩家" }));

    await waitFor(() =>
      expect(onCreateProfile).toHaveBeenCalledWith(
        expect.objectContaining({
          avatar_asset_id: SYSTEM_PLAYER_AVATARS[0].assetId,
          avatar_image_url: systemPlayerAvatarImageUrl(SYSTEM_PLAYER_AVATARS[0]),
          avatar_image_mime: "image/png",
        }),
      ),
    );
  });

  it("builds a new player nickname from werewolf-themed materials without auto AI", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    const onGenerateAiDraft = vi.fn().mockResolvedValue({
      display_name: "月蚀归票",
    });
    const props = renderLibrary({ onGenerateAiDraft });

    await openCreateEditor(props);

    expect(screen.getByLabelText("虚拟玩家昵称")).toHaveValue("夜幕听风");
    expect(onGenerateAiDraft).not.toHaveBeenCalled();
  });

  it("generates a player nickname from AI only when requested", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    const onGenerateAiDraft = vi.fn().mockResolvedValue({
      display_name: "月蚀归票",
    });
    const props = renderLibrary({
      onGenerateAiDraft,
      profiles: [profile({ display_name: "夜幕听风" })],
    });

    await openCreateEditor(props);
    expect(onGenerateAiDraft).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "AI 生成昵称" }));

    await waitFor(() =>
      expect(screen.getByLabelText("虚拟玩家昵称")).toHaveValue("月蚀归票"),
    );
    expect(onGenerateAiDraft).toHaveBeenCalledWith({
      mode: "name",
      existing_names: [],
    });
  });

  it("saves rich virtual player settings from the dedicated editor", async () => {
    const user = userEvent.setup();
    const onCreateProfile = vi.fn().mockResolvedValue({});
    const props = renderLibrary({ onCreateProfile });

    await openCreateEditor(props);
    await user.clear(screen.getByLabelText("一句话简介"));
    await user.type(screen.getByLabelText("一句话简介"), "逻辑控场玩家");
    await user.clear(screen.getByLabelText("背景故事"));
    await user.type(screen.getByLabelText("背景故事"), "长期复盘高阶狼人杀对局。");
    await user.clear(screen.getByLabelText("发言风格"));
    await user.type(screen.getByLabelText("发言风格"), "分点列证据，最后给结论。");
    await user.clear(screen.getByLabelText("常用表达"));
    await user.type(screen.getByLabelText("常用表达"), "我先拆视角，票型不对劲");
    await user.selectOptions(screen.getByLabelText("策略模板"), "logic_leader");
    await user.clear(screen.getByLabelText("领导倾向"));
    await user.type(screen.getByLabelText("领导倾向"), "5");
    await user.clear(screen.getByLabelText("示例发言"));
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

  it("renders the reference browse layout with a filter rail and card matrix", () => {
    renderLibrary({
      profiles: [
        profile({
          id: "profile-layout",
          display_name: "冷锋拆阵",
          tags: ["控场"],
        }),
      ],
    });

    const library = screen.getByTestId("virtual-player-library");
    const browseLayout = library.querySelector(".virtual-player-library-browser");
    const filterRail = screen.getByRole("complementary", {
      name: "虚拟玩家筛选",
    });
    const cardList = screen.getByRole("list", { name: "虚拟玩家列表" });

    expect(browseLayout).toContainElement(filterRail);
    expect(browseLayout).toContainElement(cardList);
    expect(filterRail).toHaveClass("virtual-player-library-filter-rail");
    expect(cardList.parentElement).toHaveClass(
      "virtual-player-library-card-matrix",
    );
    expect(screen.getByText("冷锋拆阵")).toBeInTheDocument();
  });

  it("renders the full appearance image in the player card portrait area", () => {
    renderLibrary({
      profiles: [
        profile({
          id: "profile-full-portrait",
          display_name: "整图阿夜",
          avatar_image_url: "/api/v1/player-profiles/avatar/full.png",
          avatar_image_mime: "image/png",
        }),
      ],
    });

    const image = screen.getByRole("img", { name: "整图阿夜 人物形象" });
    const portrait = image.closest(".virtual-player-card-portrait");

    expect(portrait).toBeInTheDocument();
    expect(portrait).toHaveAttribute("data-display", "full-image");
  });

  it("resolves database avatar asset URLs in player card portraits", () => {
    renderLibrary({
      profiles: [
        profile({
          id: "profile-asset-portrait",
          display_name: "资产阿夜",
          avatar_asset_id: "system-gothic-female-2",
          avatar_image_url: "/player-avatars/gothic-female-2.png",
          avatar_image_mime: "image/png",
        }),
      ],
    });

    expect(
      screen.getByRole("img", { name: "资产阿夜 人物形象" }),
    ).toHaveAttribute(
      "src",
      "/api/v1/player-profiles/avatar-assets/system-gothic-female-2",
    );
  });

  it("shows backend default personality text in the prompt preview when personality text is blank", async () => {
    const user = userEvent.setup();
    const props = renderLibrary();

    await openCreateEditor(props);
    await user.selectOptions(screen.getByLabelText("性格"), "cautious");

    expect(
      screen.getByText(/谨慎保守，优先收集信息，避免过早暴露关键判断。/),
    ).toBeInTheDocument();
  });

  it("normalizes empty and out-of-range tendency values before saving", async () => {
    const user = userEvent.setup();
    const onCreateProfile = vi.fn().mockResolvedValue({});
    const props = renderLibrary({ onCreateProfile });

    await openCreateEditor(props);
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

  it("opens profile edits in a dialog", async () => {
    const user = userEvent.setup();
    renderLibrary({
      profiles: [
        profile({
          id: "profile-dialog-edit",
          display_name: "弹窗阿夜",
        }),
      ],
    });

    await user.click(screen.getByRole("button", { name: "编辑 弹窗阿夜" }));

    expect(
      screen.getByRole("dialog", { name: "编辑虚拟玩家" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("虚拟玩家昵称")).toHaveValue("弹窗阿夜");
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

    await user.type(screen.getByLabelText("搜索虚拟玩家"), "逻辑带队");

    expect(screen.getByText("逻辑阿夜")).toBeInTheDocument();
    expect(screen.queryByText("社交月白")).not.toBeInTheDocument();
  });

  it("sorts recent virtual player cards by parsed timestamps with missing dates last", () => {
    renderLibrary({
      profiles: [
        profile({
          id: "profile-missing-date",
          display_name: "无日期阿夜",
          updated_at: undefined as unknown as string,
        }),
        profile({
          id: "profile-early-offset",
          display_name: "早场月白",
          updated_at: "2026-05-18T01:00:00+08:00",
        }),
        profile({
          id: "profile-late-utc",
          display_name: "晚场司南",
          updated_at: "2026-05-17T20:00:00Z",
        }),
      ],
    });

    const cards = screen.getAllByRole("listitem");
    expect(cards[0]).toHaveTextContent("晚场司南");
    expect(cards[1]).toHaveTextContent("早场月白");
    expect(cards[2]).toHaveTextContent("无日期阿夜");
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

    const favoritesButton = screen.getByRole("button", { name: "只看收藏" });
    expect(favoritesButton).toHaveAttribute("aria-pressed", "false");

    await user.click(favoritesButton);

    expect(favoritesButton).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("收藏阿夜")).toBeInTheDocument();
    expect(screen.queryByText("普通月白")).not.toBeInTheDocument();
  });

  it("allows choosing a different system avatar", async () => {
    const onCreateProfile = vi
      .fn<(request: PlayerProfileRequest) => Promise<unknown>>()
      .mockResolvedValue({});
    const props = renderLibrary({ onCreateProfile });

    await openCreateEditor(props);
    await userEvent.click(
      screen.getByRole("button", {
        name: `选择内设形象 ${SYSTEM_PLAYER_AVATARS[2].label}`,
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "保存虚拟玩家" }));

    await waitFor(() =>
      expect(onCreateProfile).toHaveBeenCalledWith(
        expect.objectContaining({
          avatar_asset_id: SYSTEM_PLAYER_AVATARS[2].assetId,
          avatar_image_url: systemPlayerAvatarImageUrl(SYSTEM_PLAYER_AVATARS[2]),
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
    const props = renderLibrary({ onCreateProfile, onUploadAvatar });

    await openCreateEditor(props);
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
