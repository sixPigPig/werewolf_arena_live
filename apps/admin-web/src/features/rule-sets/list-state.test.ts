import { describe, expect, it } from "vitest";
import { ruleSetListParamsFromSearch, setRuleSetSearchValues } from "./list-state";

describe("rule-set list URL state", () => {
  it("parses and canonically serializes all supported values", () => {
    expect(ruleSetListParamsFromSearch(new URLSearchParams("page=2&page_size=50&q=%20standard%20&status=published&player_count=9&sort=updated_at&direction=desc"))).toEqual({ page:2,page_size:50,q:"standard",status:"published",player_count:9,sort:"updated_at",direction:"desc" });
    expect(setRuleSetSearchValues(new URLSearchParams(), { page:"2", page_size:"50", q:" standard ", status:"published", player_count:"9", sort:"updated_at", direction:"desc" }).toString()).toBe("page=2&page_size=50&q=standard&status=published&player_count=9&sort=updated_at&direction=desc");
  });
  it("uses canonical defaults for invalid values", () => {
    expect(ruleSetListParamsFromSearch(new URLSearchParams("page=0&page_size=17&status=bad&player_count=-1&sort=nope&direction=nope"))).toEqual({ page:1,page_size:20,q:undefined,status:undefined,player_count:undefined,sort:"display_order",direction:"asc" });
  });
  it("resets page when a filter changes but not for sorting or page changes", () => {
    expect(setRuleSetSearchValues(new URLSearchParams("page=7&q=old"), { q:"new" }).get("page")).toBe("1");
    expect(setRuleSetSearchValues(new URLSearchParams("page=7"), { sort:"name" }).get("page")).toBe("7");
    expect(setRuleSetSearchValues(new URLSearchParams("page=7"), { page:"3" }).get("page")).toBe("3");
  });

  it("serializes only known fields and canonicalizes malformed values", () => {
    const result = setRuleSetSearchValues(
      new URLSearchParams("page=7&page_size=50&q=old&status=published&player_count=9&sort=name&direction=desc&unknown=secret"),
      { page: "0", page_size: "17", status: "deleted", player_count: "-1", sort: "unknown", direction: "sideways" },
    );

    expect(result.toString()).toBe("page=1&page_size=20&q=old&sort=display_order&direction=asc");
  });

  it("resets the page after canonicalizing a filter update", () => {
    expect(
      setRuleSetSearchValues(new URLSearchParams("page=7&status=published"), { status: "deleted" }).toString(),
    ).toBe("page=1&page_size=20&sort=display_order&direction=asc");
  });
});
