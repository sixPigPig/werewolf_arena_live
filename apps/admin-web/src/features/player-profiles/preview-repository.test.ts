import {
  getPreviewPlayerProfile,
  getPreviewPlayerProfileOptions,
  listPreviewPlayerProfiles,
  resetPreviewPlayerProfiles,
  transitionPreviewPlayerProfile,
  updatePreviewPlayerProfile,
} from "@/features/player-profiles/preview-repository";

const listParams = {
  page: 1,
  page_size: 20,
  sort: "updated_at" as const,
  direction: "desc" as const,
};

describe("preview player repository", () => {
  beforeEach(() => resetPreviewPlayerProfiles());

  it("uses only local or data resources and never API image URLs", async () => {
    const list = await listPreviewPlayerProfiles(listParams);
    const options = await getPreviewPlayerProfileOptions();
    expect(list.items).toHaveLength(3);
    expect(
      [...list.items.map((item) => item.avatar_image_url), ...options.appearances.map((item) => item.avatar_image_url)]
        .filter(Boolean)
        .every((url) => url.startsWith("data:")),
    ).toBe(true);
  });

  it("mirrors version and lifecycle constraints", async () => {
    await expect(
      transitionPreviewPlayerProfile(
        "preview-draft-1",
        "archive",
        { expected_version: 2, reason: "状态不允许" },
      ),
    ).rejects.toMatchObject({ status: 409 });
    await expect(
      updatePreviewPlayerProfile("preview-draft-1", {
        expected_version: 2,
        featured: true,
      }),
    ).rejects.toMatchObject({ status: 422 });
    await expect(
      updatePreviewPlayerProfile("preview-archived-1", {
        expected_version: 7,
        display_name: "不应成功",
      }),
    ).rejects.toMatchObject({ status: 409 });
  });

  it("requires an audit reason and performs legal transitions", async () => {
    await expect(
      transitionPreviewPlayerProfile(
        "preview-draft-1",
        "publish",
        { expected_version: 2, reason: "短" },
      ),
    ).rejects.toMatchObject({ status: 422 });

    const published = await transitionPreviewPlayerProfile(
      "preview-draft-1",
      "publish",
      { expected_version: 2, reason: "内容审核通过" },
    );
    expect(published).toMatchObject({ status: "published", version: 3 });

    const archived = await transitionPreviewPlayerProfile(
      published.id,
      "archive",
      { expected_version: 3, reason: "内容已下线" },
    );
    expect(archived).toMatchObject({
      status: "archived",
      version: 4,
      featured: false,
    });

    const restored = await transitionPreviewPlayerProfile(
      archived.id,
      "restore",
      { expected_version: 4, reason: "重新审核通过" },
    );
    expect(restored).toMatchObject({ status: "published", version: 5 });
    expect(restored.published_at).not.toBeNull();
    expect(restored.published_by).toBe("preview-super-admin");
    expect(await getPreviewPlayerProfile(restored.id)).toEqual(restored);
  });

  it("returns current_version on optimistic conflicts", async () => {
    await updatePreviewPlayerProfile("preview-draft-1", {
      expected_version: 2,
      display_name: "服务端更新",
    });
    await expect(
      updatePreviewPlayerProfile("preview-draft-1", {
        expected_version: 2,
        display_name: "过期更新",
      }),
    ).rejects.toMatchObject({
      code: "admin_player_profile_version_conflict",
      currentVersion: 3,
      status: 409,
    });
  });
});
