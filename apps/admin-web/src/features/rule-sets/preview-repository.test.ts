import { beforeEach, describe, expect, it } from "vitest";
import { archivePreviewRuleSet, createPreviewRuleSet, duplicatePreviewRuleSet, getPreviewRuleSet, listPreviewRuleSets, publishPreviewRuleSet, resetPreviewRuleSets, restorePreviewRuleSet, setDefaultPreviewRuleSet, updatePreviewRuleSetDraft, validatePreviewRuleSet } from "./preview-repository";
import { ruleSetOptions, standardConfig } from "./test-fixtures";

describe("preview rule-set repository", () => {
  beforeEach(() => resetPreviewRuleSets());

  it("filters, sorts and paginates four official-style fixtures", async () => {
    const page = await listPreviewRuleSets({ page: 1, page_size: 1, q: "classic", status: "published", sort: "display_order", direction: "desc" });
    expect(page.pagination).toEqual({ page: 1, page_size: 1, total: 2, pages: 2 });
    expect(page.items[0].id).toBe("classic_12");
    page.items[0].display_order = 999;
    expect((await getPreviewRuleSet("classic_12")).display_order).not.toBe(999);
  });

  it("returns cloned detail usage and immutable revision history", async () => {
    const before = await getPreviewRuleSet("classic_9");
    expect(before).toMatchObject({ usage: { game_count: expect.any(Number), live_count: expect.any(Number) }, revisions: [{ usage: expect.any(Object) }] });
    before.revisions[0].config!.name = "mutated";
    expect((await getPreviewRuleSet("classic_9")).revisions[0].config!.name).not.toBe("mutated");
  });

  it("creates and duplicates independent drafts", async () => {
    const created = await createPreviewRuleSet({ id: "new_rule", display_order: 8, config: standardConfig });
    expect(created).toMatchObject({ id: "new_rule", status: "draft", lock_version: 1, draft_revision: { revision_no: 1, state: "draft" } });
    const duplicate = await duplicatePreviewRuleSet("classic_9", { expected_source_lock_version: 1, new_rule_set_id: "copy_rule", new_name: "复制规则" });
    expect(duplicate).toMatchObject({ id: "copy_rule", status: "draft", display_order: 1, draft_revision: { config: { name: "复制规则" } } });
  });

  it("updates drafts with lock conflict protection", async () => {
    const current = await getPreviewRuleSet("preview_draft");
    const updated = await updatePreviewRuleSetDraft(current.id, { expected_rule_set_lock_version: current.lock_version, expected_revision_lock_version: current.draft_revision!.lock_version, display_order: 7, config: { ...current.draft_revision!.config!, name: "更新规则" } });
    expect(updated).toMatchObject({ lock_version: 2, draft_revision: { lock_version: 2, config: { name: "更新规则" } } });
    await expect(updatePreviewRuleSetDraft(current.id, { expected_rule_set_lock_version: 1, expected_revision_lock_version: 1, display_order: 7, config: standardConfig })).rejects.toMatchObject({ problem: { status: 409 } });
  });

  it("validates success and errors", async () => {
    const current = await getPreviewRuleSet("preview_draft");
    expect(await validatePreviewRuleSet(current.id, { expected_revision_lock_version: current.draft_revision!.lock_version })).toMatchObject({ valid: true, errors: [], content_hash: expect.any(String) });
    await updatePreviewRuleSetDraft(current.id, { expected_rule_set_lock_version: 1, expected_revision_lock_version: 1, display_order: 3, config: { ...standardConfig, role_counts: { ...standardConfig.role_counts, werewolf: 0 } } });
    expect(await validatePreviewRuleSet(current.id, { expected_revision_lock_version: 2 })).toMatchObject({ valid: false, errors: [{ path: "config.role_counts.werewolf" }] });
  });

  it("publishes a new immutable revision and supersedes the prior published revision", async () => {
    const before = await getPreviewRuleSet("classic_12");
    const withDraft = await updatePreviewRuleSetDraft(before.id, { expected_rule_set_lock_version: before.lock_version, expected_revision_lock_version: null, display_order: before.display_order, config: { ...before.published_revision!.config!, name: "十二人新版" } });
    const published = await publishPreviewRuleSet(before.id, { expected_rule_set_lock_version: withDraft.lock_version, expected_revision_lock_version: withDraft.draft_revision!.lock_version, reason: "发布新版" });
    expect(published).toMatchObject({ status: "published", draft_revision: null, published_revision: { revision_no: 2, state: "published", config: { name: "十二人新版" } } });
    expect(published.revisions.map((r) => r.state)).toEqual(["published", "superseded"]);
  });

  it("sets exactly one default, archives default with replacement, and restores", async () => {
    const twelve = await getPreviewRuleSet("classic_12"); const nine = await getPreviewRuleSet("classic_9");
    await setDefaultPreviewRuleSet(twelve.id, { expected_rule_set_lock_version: twelve.lock_version, previous_default_expected_lock_version: nine.lock_version, reason: "切换默认规则" });
    expect((await listPreviewRuleSets({ page: 1, page_size: 20, sort: "display_order", direction: "asc" })).items.filter((x) => x.is_default).map((x) => x.id)).toEqual(["classic_12"]);
    const currentTwelve = await getPreviewRuleSet(twelve.id); const currentNine = await getPreviewRuleSet(nine.id);
    const archived = await archivePreviewRuleSet(twelve.id, { expected_rule_set_lock_version: currentTwelve.lock_version, replacement_default_rule_set_id: nine.id, replacement_expected_lock_version: currentNine.lock_version, reason: "归档并替换默认" });
    expect(archived.status).toBe("archived"); expect((await getPreviewRuleSet(nine.id)).is_default).toBe(true);
    expect((await restorePreviewRuleSet(twelve.id, { expected_rule_set_lock_version: archived.lock_version, reason: "恢复规则" })).status).toBe("published");
  });

  it("archives and restores draft and published lifecycles without changing revisions", async () => {
    const draft = await getPreviewRuleSet("preview_draft");
    const draftRevision = structuredClone(draft.draft_revision);
    const draftHistory = structuredClone(draft.revisions);
    const archivedDraft = await archivePreviewRuleSet(draft.id, { expected_rule_set_lock_version: draft.lock_version, replacement_default_rule_set_id: null, replacement_expected_lock_version: null, reason: "暂停草稿规则" });
    expect(archivedDraft).toMatchObject({ status: "archived", lock_version: draft.lock_version + 1, draft_revision: draftRevision, revisions: draftHistory });
    const archivedDraftDetail = await getPreviewRuleSet(draft.id);
    expect(archivedDraftDetail).toMatchObject({ status: "archived", draft_revision: draftRevision, revisions: draftHistory });
    const restoredDraft = await restorePreviewRuleSet(draft.id, { expected_rule_set_lock_version: archivedDraft.lock_version, reason: "恢复草稿规则" });
    expect(restoredDraft).toMatchObject({ status: "draft", lock_version: draft.lock_version + 2, draft_revision: draftRevision, revisions: draftHistory });

    const published = await getPreviewRuleSet("classic_12");
    const archivedPublished = await archivePreviewRuleSet(published.id, { expected_rule_set_lock_version: published.lock_version, replacement_default_rule_set_id: null, replacement_expected_lock_version: null, reason: "暂停发布规则" });
    const restoredPublished = await restorePreviewRuleSet(published.id, { expected_rule_set_lock_version: archivedPublished.lock_version, reason: "恢复发布规则" });
    expect(restoredPublished).toMatchObject({ status: "published", lock_version: published.lock_version + 2, published_revision: published.published_revision, revisions: published.revisions });

    const alreadyArchived = await getPreviewRuleSet("archived_rule");
    await expect(archivePreviewRuleSet(alreadyArchived.id, { expected_rule_set_lock_version: alreadyArchived.lock_version, replacement_default_rule_set_id: null, replacement_expected_lock_version: null, reason: "重复归档规则" })).rejects.toMatchObject({ problem: { status: 409, code: "rule_set_unavailable" } });
  });

  it("rejects replacement data for non-default archives and incomplete default replacement pairs", async () => {
    const twelve = await getPreviewRuleSet("classic_12");
    await expect(archivePreviewRuleSet(twelve.id, { expected_rule_set_lock_version: twelve.lock_version, replacement_default_rule_set_id: "classic_9", replacement_expected_lock_version: 1, reason: "归档非默认规则" })).rejects.toMatchObject({ problem: { status: 409, code: "rule_set_unavailable" } });
    await expect(archivePreviewRuleSet(twelve.id, { expected_rule_set_lock_version: twelve.lock_version, replacement_default_rule_set_id: null, replacement_expected_lock_version: 1, reason: "归档非默认规则" })).rejects.toMatchObject({ problem: { status: 422, code: "admin_rule_set_validation_failed" } });
    const nine = await getPreviewRuleSet("classic_9");
    await expect(archivePreviewRuleSet(nine.id, { expected_rule_set_lock_version: nine.lock_version, replacement_default_rule_set_id: "classic_12", replacement_expected_lock_version: null, reason: "归档默认规则" })).rejects.toMatchObject({ problem: { status: 422, code: "admin_rule_set_validation_failed" } });
    await expect(archivePreviewRuleSet(nine.id, { expected_rule_set_lock_version: nine.lock_version, replacement_default_rule_set_id: null, replacement_expected_lock_version: 1, reason: "归档默认规则" })).rejects.toMatchObject({ problem: { status: 422, code: "admin_rule_set_validation_failed" } });
    await expect(archivePreviewRuleSet(nine.id, { expected_rule_set_lock_version: nine.lock_version, replacement_default_rule_set_id: null, replacement_expected_lock_version: null, reason: "归档默认规则" })).rejects.toMatchObject({ problem: { status: 409, code: "default_rule_required" } });
  });

  it("requires an exact published replacement and exact replacement lock when archiving the default", async () => {
    const nine = await getPreviewRuleSet("classic_9");
    await expect(archivePreviewRuleSet(nine.id, { expected_rule_set_lock_version: nine.lock_version, replacement_default_rule_set_id: nine.id, replacement_expected_lock_version: nine.lock_version, reason: "替换默认规则" })).rejects.toMatchObject({ problem: { status: 409, code: "default_rule_required" } });
    await expect(archivePreviewRuleSet(nine.id, { expected_rule_set_lock_version: nine.lock_version, replacement_default_rule_set_id: "preview_draft", replacement_expected_lock_version: 1, reason: "替换默认规则" })).rejects.toMatchObject({ problem: { status: 409, code: "rule_set_unavailable" } });
    await expect(archivePreviewRuleSet(nine.id, { expected_rule_set_lock_version: nine.lock_version, replacement_default_rule_set_id: "classic_12", replacement_expected_lock_version: 99, reason: "替换默认规则" })).rejects.toMatchObject({ problem: { status: 409, code: "rule_set_version_conflict" } });
  });

  it("validates previous-default versions when target is already default", async () => {
    const nine = await getPreviewRuleSet("classic_9");
    await expect(setDefaultPreviewRuleSet(nine.id, { expected_rule_set_lock_version: nine.lock_version, previous_default_expected_lock_version: 99, reason: "确认默认规则" })).rejects.toMatchObject({ problem: { status: 409, code: "rule_set_version_conflict" } });
    await expect(setDefaultPreviewRuleSet(nine.id, { expected_rule_set_lock_version: nine.lock_version, previous_default_expected_lock_version: nine.lock_version, reason: "确认默认规则" })).resolves.toMatchObject({ is_default: true, lock_version: nine.lock_version });
  });

  it("requires the exact previous-default version when changing defaults", async () => {
    const twelve = await getPreviewRuleSet("classic_12");
    await expect(setDefaultPreviewRuleSet(twelve.id, { expected_rule_set_lock_version: twelve.lock_version, previous_default_expected_lock_version: null, reason: "切换默认规则" })).rejects.toMatchObject({ problem: { status: 409, code: "rule_set_version_conflict" } });
    await expect(setDefaultPreviewRuleSet(twelve.id, { expected_rule_set_lock_version: twelve.lock_version, previous_default_expected_lock_version: 99, reason: "切换默认规则" })).rejects.toMatchObject({ problem: { status: 409, code: "rule_set_version_conflict" } });
  });

  it("rejects an extraneous previous-default version when no default exists", async () => {
    resetPreviewRuleSets({ withoutDefault: true });
    const twelve = await getPreviewRuleSet("classic_12");
    await expect(setDefaultPreviewRuleSet(twelve.id, { expected_rule_set_lock_version: twelve.lock_version, previous_default_expected_lock_version: 1, reason: "建立默认规则" })).rejects.toMatchObject({ problem: { status: 409, code: "rule_set_version_conflict" } });
    await expect(setDefaultPreviewRuleSet(twelve.id, { expected_rule_set_lock_version: twelve.lock_version, previous_default_expected_lock_version: null, reason: "建立默认规则" })).resolves.toMatchObject({ is_default: true });
  });

  it("enforces server reason length constraints", async () => {
    const draft = await getPreviewRuleSet("preview_draft");
    await expect(publishPreviewRuleSet(draft.id, { expected_rule_set_lock_version: draft.lock_version, expected_revision_lock_version: draft.draft_revision!.lock_version, reason: "短" })).rejects.toMatchObject({ problem: { status: 422 } });
    expect(ruleSetOptions.constraints.reason_min_length).toBe(3);
  });
});
