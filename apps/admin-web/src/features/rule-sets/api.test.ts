import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import { adminApiFetch } from "@/api/client";

vi.mock("@/api/client", () => ({ adminApiFetch: vi.fn() }));
vi.mock("./parsers", () => ({ parseAdminRuleSet: (x: unknown) => x, parseAdminRuleSetDetail: (x: unknown) => x, parseAdminRuleSetList: (x: unknown) => x, parseRuleSetOptions: (x: unknown) => x, parseRuleSetValidation: (x: unknown) => x }));
const fetchMock = vi.mocked(adminApiFetch);
const csrf = "csrf";
const body = { x: 1 } as never;

describe("rule set API", () => {
  beforeEach(() => fetchMock.mockReset().mockResolvedValue({}));
  it("uses exact GET paths and forwards AbortSignal", async () => {
    const signal = new AbortController().signal;
    await api.getRuleSetOptions(signal);
    await api.listAdminRuleSets({ page: 2, page_size: 20, q: "标准", status: "draft", player_count: 9, sort: "updated_at", direction: "desc" }, signal);
    await api.getAdminRuleSet("id/with space", signal);
    expect(fetchMock.mock.calls).toEqual([
      ["/api/v1/admin/rule-set-options", { signal }],
      ["/api/v1/admin/rule-sets?page=2&page_size=20&q=%E6%A0%87%E5%87%86&status=draft&player_count=9&sort=-updated_at", { signal }],
      ["/api/v1/admin/rule-sets/id%2Fwith%20space", { signal }],
    ]);
  });
  it("uses exact write endpoints, methods, headers and bodies", async () => {
    await api.createAdminRuleSet(body, csrf);
    await api.updateAdminRuleSetDraft("a/b", body, csrf);
    await api.validateAdminRuleSet("a/b", body, csrf);
    await api.publishAdminRuleSet("a/b", body, csrf);
    await api.archiveAdminRuleSet("a/b", body, csrf);
    await api.restoreAdminRuleSet("a/b", body, csrf);
    await api.setDefaultAdminRuleSet("a/b", body, csrf);
    await api.duplicateAdminRuleSet("a/b", body, csrf);
    const expected = [
      ["/api/v1/admin/rule-sets", "POST"], ["/api/v1/admin/rule-sets/a%2Fb/draft", "PATCH"],
      ["/api/v1/admin/rule-sets/a%2Fb/validate", "POST"], ["/api/v1/admin/rule-sets/a%2Fb/publish", "POST"],
      ["/api/v1/admin/rule-sets/a%2Fb/archive", "POST"], ["/api/v1/admin/rule-sets/a%2Fb/restore", "POST"],
      ["/api/v1/admin/rule-sets/a%2Fb/set-default", "POST"], ["/api/v1/admin/rule-sets/a%2Fb/duplicate", "POST"],
    ];
    expected.forEach(([path, method], i) => expect(fetchMock.mock.calls[i]).toEqual([path, { method, headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify(body) }]));
  });
});
