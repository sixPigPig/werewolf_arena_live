import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { routes } from "../routes";
import { renderWithClient } from "../tests/renderWithClient";
import { JudgeVoiceAssetsPage } from "./JudgeVoiceAssetsPage";

const listResponse = {
  audio_format: "mp3",
  sample_rate: 24000,
  lines: [
    {
      id: "night_start",
      text: "夜晚降临，所有玩家请闭眼。",
      category: "夜晚",
      filename: "night_start.mp3",
      public_url: "/judge-voice/night_start.mp3",
      exists: true,
      byte_size: 1234,
      template_id: null,
      template_text: null,
      seat_number: null,
    },
    {
      id: "speech_prompt_seat_01",
      text: "1号玩家请发言。",
      category: "发言",
      filename: "speech_prompt_seat_01.mp3",
      public_url: "/judge-voice/speech_prompt_seat_01.mp3",
      exists: false,
      byte_size: null,
      template_id: "speech_prompt",
      template_text: "{玩家}请发言。",
      seat_number: 1,
    },
    {
      id: "speech_prompt_seat_10",
      text: "10号玩家请发言。",
      category: "发言",
      filename: "speech_prompt_seat_10.mp3",
      public_url: "/judge-voice/speech_prompt_seat_10.mp3",
      exists: true,
      byte_size: 4321,
      template_id: "speech_prompt",
      template_text: "{玩家}请发言。",
      seat_number: 10,
    },
    {
      id: "speech_prompt_seat_12",
      text: "12号玩家请发言。",
      category: "发言",
      filename: "speech_prompt_seat_12.mp3",
      public_url: "/judge-voice/speech_prompt_seat_12.mp3",
      exists: true,
      byte_size: 4567,
      template_id: "speech_prompt",
      template_text: "{玩家}请发言。",
      seat_number: 12,
    },
  ],
};

describe("JudgeVoiceAssetsPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders judge lines with generation status and audio preview", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(listResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithClient(<JudgeVoiceAssetsPage />);

    expect(
      await screen.findByRole("heading", { name: "法官语音资产" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("night_start")).toBeInTheDocument();
    expect(screen.getByText("夜晚降临，所有玩家请闭眼。")).toBeInTheDocument();
    expect(screen.getByText("已生成")).toBeInTheDocument();
    expect(screen.getByText("已生成 2 / 3")).toBeInTheDocument();
    expect(screen.getByLabelText("试听 night_start")).toHaveAttribute(
      "src",
      "/judge-voice/night_start.mp3",
    );
    expect(screen.getByRole("button", { name: /\{玩家\}请发言。/ })).toBeInTheDocument();
    expect(screen.queryByText("speech_prompt_seat_10")).not.toBeInTheDocument();
  });

  it("expands player template panels to reveal seat-number voice lines", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(listResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithClient(<JudgeVoiceAssetsPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: /\{玩家\}请发言。/ }),
    );

    expect(screen.getByText("speech_prompt_seat_10")).toBeInTheDocument();
    expect(screen.getByText("10号玩家请发言。")).toBeInTheDocument();
    expect(screen.getByLabelText("试听 speech_prompt_seat_10")).toHaveAttribute(
      "src",
      "/judge-voice/speech_prompt_seat_10.mp3",
    );
  });

  it("generates missing judge voice assets", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fetchSpy
      .mockResolvedValueOnce(
        new Response(JSON.stringify(listResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ...listResponse,
            generated_ids: ["dawn_peaceful"],
            skipped_ids: ["night_start"],
            manifest_path: "/tmp/manifest.json",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(listResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    renderWithClient(<JudgeVoiceAssetsPage />);

    await userEvent.click(
      await screen.findByRole("button", { name: "生成缺失语音" }),
    );

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/v1/judge-voice-lines/generate",
        expect.objectContaining({
          body: JSON.stringify({ force: false }),
          method: "POST",
        }),
      );
    });
    expect(await screen.findByText("已生成 1 条，跳过 1 条。")).toBeInTheDocument();
  });

  it("registers the judge voice asset route", () => {
    expect(routes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ path: "/judge-voice-assets" }),
      ]),
    );
  });
});
