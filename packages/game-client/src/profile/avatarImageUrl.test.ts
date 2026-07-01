import { describe, expect, it } from "vitest";

import {
  avatarAssetImageUrl,
  resolveAvatarImageUrl,
  systemAvatarAssetIdForAppearance,
} from "./avatarImageUrl";

describe("avatar image URL helpers", () => {
  it("builds API asset URLs with an explicit base URL", () => {
    expect(
      avatarAssetImageUrl("system-gothic-male-1", {
        baseUrl: "https://api.example.test",
      }),
    ).toBe(
      "https://api.example.test/api/v1/player-profiles/avatar-assets/system-gothic-male-1",
    );
  });

  it("resolves avatar_asset_id before legacy URL fields", () => {
    expect(
      resolveAvatarImageUrl(
        {
          avatar_asset_id: "system-gothic-female-2",
          avatar_image_url: "/player-avatars/gothic-male-1.png",
        },
        { baseUrl: "https://api.example.test" },
      ),
    ).toBe(
      "https://api.example.test/api/v1/player-profiles/avatar-assets/system-gothic-female-2",
    );
  });

  it("resolves old system avatar URLs to API asset URLs", () => {
    expect(
      resolveAvatarImageUrl(
        { avatar_image_url: "/player-avatars/gothic-female-1.png" },
        { baseUrl: "https://api.example.test" },
      ),
    ).toBe(
      "https://api.example.test/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
    );
  });

  it("prefixes API relative image URLs", () => {
    expect(
      resolveAvatarImageUrl(
        { avatar_image_url: "/api/v1/player-profiles/avatar-assets/uploaded-abc" },
        { baseUrl: "https://api.example.test" },
      ),
    ).toBe("https://api.example.test/api/v1/player-profiles/avatar-assets/uploaded-abc");
  });

  it("returns an empty string when no avatar is available", () => {
    expect(resolveAvatarImageUrl({}, { baseUrl: "https://api.example.test" })).toBe("");
  });

  it("maps appearance IDs to system avatar asset IDs", () => {
    expect(systemAvatarAssetIdForAppearance("gothic-male-2")).toBe(
      "system-gothic-male-2",
    );
    expect(systemAvatarAssetIdForAppearance("default")).toBeNull();
  });
});
