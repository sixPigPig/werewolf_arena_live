import { afterEach, describe, expect, it, vi } from "vitest";

import { createPlayerProfile } from "./createPlayerProfile";
import { deletePlayerProfile } from "./deletePlayerProfile";
import { listPlayerProfiles } from "./listPlayerProfiles";
import { uploadPlayerAvatar } from "./uploadPlayerAvatar";
import { updatePlayerProfile } from "./updatePlayerProfile";

const profile = {
  id: "profile-1",
  display_name: "冷静的阿夜",
  model: "deepseek-chat",
  personality_id: "cautious",
  personality_text: "谨慎观察局势。",
  appearance_id: "moonlit",
  avatar_prompt: "银发观察者",
  avatar_image_url: "/api/v1/player-profiles/avatar/profile-1.png",
  avatar_image_mime: "image/png",
  tags: ["控场"],
  created_at: "2026-05-16T08:00:00Z",
  updated_at: "2026-05-16T08:00:00Z",
};

describe("player profiles api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists player profiles", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ profiles: [profile] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const response = await listPlayerProfiles();

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/player-profiles",
      undefined,
    );
    expect(response.profiles[0].display_name).toBe("冷静的阿夜");
  });

  it("creates a player profile with JSON", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(profile), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await createPlayerProfile({
      display_name: "冷静的阿夜",
      model: "deepseek-chat",
      personality_id: "cautious",
      appearance_id: "moonlit",
      avatar_image_url: "/api/v1/player-profiles/avatar/profile-1.png",
      avatar_image_mime: "image/png",
      tags: ["控场"],
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/player-profiles",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: "冷静的阿夜",
          model: "deepseek-chat",
          personality_id: "cautious",
          appearance_id: "moonlit",
          avatar_image_url: "/api/v1/player-profiles/avatar/profile-1.png",
          avatar_image_mime: "image/png",
          tags: ["控场"],
        }),
      }),
    );
  });

  it("uploads a player avatar image as base64 JSON", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          avatar_image_url: "/api/v1/player-profiles/avatar/avatar.png",
          avatar_image_mime: "image/png",
        }),
        {
          status: 201,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    const file = new File([new Uint8Array([137, 80, 78, 71])], "avatar.png", {
      type: "image/png",
    });
    const response = await uploadPlayerAvatar(file);

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/player-profiles/avatar",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    );
    const body = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body));
    expect(body).toEqual({
      filename: "avatar.png",
      content_type: "image/png",
      data_base64: "iVBORw==",
    });
    expect(response.avatar_image_url).toBe(
      "/api/v1/player-profiles/avatar/avatar.png",
    );
  });

  it("updates a player profile by id with JSON", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ...profile, display_name: "阿夜二号" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await updatePlayerProfile("profile-1", { display_name: "阿夜二号" });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/player-profiles/profile-1",
      expect.objectContaining({
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: "阿夜二号" }),
      }),
    );
  });

  it("deletes a player profile by id", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));

    await deletePlayerProfile("profile-1");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/player-profiles/profile-1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
