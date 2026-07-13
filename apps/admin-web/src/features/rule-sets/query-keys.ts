import type { RuleSetListParams } from "./types";
export const ruleSetKeys = { all: ["rule-sets"] as const, lists: ["rule-sets","list"] as const, list: (params:RuleSetListParams) => ["rule-sets","list",params] as const, details: ["rule-sets","detail"] as const, detail: (id:string) => ["rule-sets","detail",id] as const, options: ["rule-sets","options"] as const };
