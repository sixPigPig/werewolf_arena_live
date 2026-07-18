import { AdminApiError } from "@/api/problem-details";
import type { AdminRuleSet, AdminRuleSetDetail, AdminRuleSetList, NonEmptyArray, RuleBadgeBombPolicy, RuleClauseAudience, RuleContract, RuleContractCoverage, RuleRoleId, RuleSetConfig, RuleSetOptions, RuleSetOptionSort, RuleSetRevision, RuleSetStatus, RuleSetUsage, RuleSetValidation, RuleSetWarning, RuleSpeechPolicy, RuleWinCondition } from "./types";

const FORBIDDEN = new Set(["compiled_snapshot", "rule_set_snapshot", "players", "sql", "raw_error"]);
const ROLE_IDS = ["werewolf", "villager", "seer", "guard", "witch", "hunter", "idiot"] as const;
const STATUS = ["draft", "published", "archived"] as const;
const STATES = ["draft", "published", "superseded"] as const;
const WIN_CONDITIONS: readonly RuleWinCondition[] = ["wolves_gte_others", "slaughter_side"];
const SPEECH_POLICIES: readonly RuleSpeechPolicy[] = ["sequential", "sheriff_directed"];
const BADGE_POLICIES: readonly RuleBadgeBombPolicy[] = ["none", "double"];
const RULE_AUDIENCES: readonly RuleClauseAudience[] = ["player_public", "role_private", "internal_only"];
const CONTRACT_COVERAGE: readonly RuleContractCoverage[] = ["covered", "broken"];
const CLAUSE_PRIORITIES = ["P0", "P1", "P2"] as const;
const SORTS: readonly RuleSetOptionSort[] = ["display_order", "-display_order", "updated_at", "-updated_at", "name", "-name", "created_at", "-created_at"];

export function parseAdminRuleSet(value: unknown): AdminRuleSet { rejectForbidden(value); return parseRuleSetRecord(value); }
export function parseAdminRuleSetList(value: unknown): AdminRuleSetList { rejectForbidden(value); const r = record(value); const p = record(r.pagination); return { items: array(r.items, "items").map(parseRuleSetRecord), pagination: { page: positive(p.page, "pagination.page"), page_size: positive(p.page_size, "pagination.page_size"), total: nonnegative(p.total, "pagination.total"), pages: nonnegative(p.pages, "pagination.pages") } }; }
export function parseAdminRuleSetDetail(value: unknown): AdminRuleSetDetail { rejectForbidden(value); const r = record(value); const base = parseRuleSetRecord({ ...r, revisions: [] }); return { ...base, revisions: array(r.revisions, "revisions").map(x => ({ ...parseRevision(x), usage: parseUsage(record(x).usage) })), usage: parseUsage(r.usage), warnings: array(r.warnings, "warnings").map(parseWarning), rule_contract: r.rule_contract === null ? null : parseRuleContract(r.rule_contract) }; }
export function parseRuleSetOptions(value: unknown): RuleSetOptions {
  rejectForbidden(value);
  const r = record(value); const c = record(r.constraints);
  const choices = <T extends string>(v: unknown, name: string, allowed: readonly T[]) => {
    const parsed = nonemptyArray(v, name).map((item) => { const q = record(item); return { value: oneOf(q.value, allowed, `${name}.value`), label: string(q.label, `${name}.label`) }; });
    unique(parsed.map((item) => item.value), name);
    return parsed as NonEmptyArray<{ value: T; label: string }>;
  };
  const roles = nonemptyArray(r.roles, "roles").map((item) => {
    const q = record(item); const min = nonnegative(q.min_count, "roles.min_count"); const max = nonnegative(q.max_count, "roles.max_count");
    if (min > max) fail("roles.range");
    return { id: oneOf(q.id, ROLE_IDS, "roles.id") as RuleRoleId, label: string(q.label, "roles.label"), min_count: min, max_count: max };
  });
  unique(roles.map((role) => role.id), "roles");
  if (roles.length !== ROLE_IDS.length || ROLE_IDS.some((id) => !roles.some((role) => role.id === id))) fail("roles.complete");
  const weights = nonemptyArray(r.sheriff_vote_weights, "sheriff_vote_weights").map((item) => positiveNumber(item, "sheriff_vote_weights")); unique(weights, "sheriff_vote_weights");
  const playerMin = positive(c.player_count_min, "constraints.player_count_min"); const playerMax = positive(c.player_count_max, "constraints.player_count_max");
  const reasonMin = positive(c.reason_min_length, "constraints.reason_min_length"); const reasonMax = positive(c.reason_max_length, "constraints.reason_max_length");
  if (playerMin > playerMax) fail("constraints.player_count_range"); if (reasonMin > reasonMax) fail("constraints.reason_range");
  if (roles.some((role) => role.max_count > playerMax)) fail("roles.max_count.player_count_max");
  if (roles.reduce((sum, role) => sum + role.min_count, 0) > playerMax) fail("roles.minima.player_count_max");
  if (roles.reduce((sum, role) => sum + role.max_count, 0) < playerMin) fail("roles.maxima.player_count_min");
  const idPattern = string(c.id_pattern, "constraints.id_pattern"); try { new RegExp(idPattern); } catch { fail("constraints.id_pattern"); }
  return {
    roles: roles as RuleSetOptions["roles"], win_conditions: choices(r.win_conditions, "win_conditions", WIN_CONDITIONS), sheriff_vote_weights: weights as NonEmptyArray<number>,
    speech_policies: choices(r.speech_policies, "speech_policies", SPEECH_POLICIES), sheriff_badge_bomb_policies: choices(r.sheriff_badge_bomb_policies, "sheriff_badge_bomb_policies", BADGE_POLICIES),
    statuses: choices(r.statuses, "statuses", STATUS as readonly RuleSetStatus[]), sorts: choices(r.sorts, "sorts", SORTS),
    constraints: { player_count_min: playerMin, player_count_max: playerMax, tags_max_items: positive(c.tags_max_items, "constraints.tags_max_items"), tag_max_length: positive(c.tag_max_length, "constraints.tag_max_length"), id_pattern: idPattern, reason_min_length: reasonMin, reason_max_length: reasonMax },
  };
}
export function parseRuleSetValidation(value: unknown): RuleSetValidation {
  rejectForbidden(value, true); const r = record(value); if (r.compiled_snapshot !== undefined && r.compiled_snapshot !== null) record(r.compiled_snapshot);
  const valid = boolean(r.valid, "valid"); const contentHash = optionalNullableString(r.content_hash, "content_hash"); const preview = optionalNullableString(r.rule_text_preview, "rule_text_preview"); const ruleContract = r.rule_contract === undefined || r.rule_contract === null ? null : parseRuleContract(r.rule_contract);
  if (valid && (!contentHash || !/^[0-9a-f]{64}$/.test(contentHash) || !preview || !ruleContract?.publish_ready)) fail("valid validation output");
  return { valid, errors: array(r.errors, "errors").map(parseWarning), warnings: array(r.warnings, "warnings").map(parseWarning), content_hash: contentHash, rule_text_preview: preview, rule_contract: ruleContract };
}

export function parseRuleContract(value: unknown): RuleContract {
  const r = record(value);
  const coverageStatus = oneOf(r.coverage_status, CONTRACT_COVERAGE, "rule_contract.coverage_status");
  const publishReady = boolean(r.publish_ready, "rule_contract.publish_ready");
  const missingP0 = stringArray(r.missing_p0_clause_ids, "rule_contract.missing_p0_clause_ids");
  const brokenConstraints = stringArray(r.broken_engine_constraint_ids, "rule_contract.broken_engine_constraint_ids");
  const clauses = array(r.clauses, "rule_contract.clauses").map((item) => {
    const clause = record(item);
    const audience = oneOf(clause.audience, RULE_AUDIENCES, "rule_contract.clauses.audience");
    const clauseCoverage = oneOf(clause.coverage_status, CONTRACT_COVERAGE, "rule_contract.clauses.coverage_status");
    const uncovered = stringArray(clause.uncovered_engine_constraint_ids, "rule_contract.clauses.uncovered_engine_constraint_ids");
    const modelRuleText = clause.model_rule_text === null ? null : string(clause.model_rule_text, "rule_contract.clauses.model_rule_text");
    if ((audience === "internal_only") !== (modelRuleText === null)) fail("rule_contract.clauses.model_rule_text.audience");
    if ((clauseCoverage === "covered") !== (uncovered.length === 0)) fail("rule_contract.clauses.coverage");
    return {
      clause_id: string(clause.clause_id, "rule_contract.clauses.clause_id"),
      priority: oneOf(clause.priority, CLAUSE_PRIORITIES, "rule_contract.clauses.priority"),
      roles: stringArray(clause.roles, "rule_contract.clauses.roles"),
      phases: stringArray(clause.phases, "rule_contract.clauses.phases"),
      actions: stringArray(clause.actions, "rule_contract.clauses.actions"),
      audience,
      engine_constraint_ids: nonemptyStringArray(clause.engine_constraint_ids, "rule_contract.clauses.engine_constraint_ids"),
      model_rule_text: modelRuleText,
      coverage_status: clauseCoverage,
      uncovered_engine_constraint_ids: uncovered,
    };
  });
  unique(clauses.map((clause) => clause.clause_id), "rule_contract.clauses"); unique(missingP0, "rule_contract.missing_p0_clause_ids"); unique(brokenConstraints, "rule_contract.broken_engine_constraint_ids");
  if (publishReady !== (coverageStatus === "covered")) fail("rule_contract.publish_ready");
  if (publishReady && (missingP0.length || brokenConstraints.length || clauses.some((clause) => clause.coverage_status !== "covered"))) fail("rule_contract.publish_ready.coverage");
  const canonicalHash = string(r.canonical_hash, "rule_contract.canonical_hash"); if (!/^[0-9a-f]{64}$/.test(canonicalHash)) fail("rule_contract.canonical_hash");
  return { schema_version: positive(r.schema_version, "rule_contract.schema_version"), revision_id: string(r.revision_id, "rule_contract.revision_id"), canonical_hash: canonicalHash, coverage_status: coverageStatus, publish_ready: publishReady, missing_p0_clause_ids: missingP0, broken_engine_constraint_ids: brokenConstraints, clauses };
}

function parseRuleSetRecord(value: unknown): AdminRuleSet { const r=record(value); return { id:string(r.id,"id"), status:oneOf(r.status,STATUS,"status"), is_default:boolean(r.is_default,"is_default"), display_order:nonnegative(r.display_order,"display_order"), lock_version:positive(r.lock_version,"lock_version"), draft_revision:r.draft_revision===null?null:parseRevision(r.draft_revision), published_revision:r.published_revision===null?null:parseRevision(r.published_revision), revisions:array(r.revisions,"revisions").map(parseRevision), created_at:date(r.created_at,"created_at"), updated_at:date(r.updated_at,"updated_at") }; }
function parseRevision(value: unknown): RuleSetRevision { const r=record(value); return { id:string(r.id,"revision.id"),rule_set_id:string(r.rule_set_id,"revision.rule_set_id"),revision_no:positive(r.revision_no,"revision.revision_no"),state:oneOf(r.state,STATES,"revision.state"),schema_version:positive(r.schema_version,"revision.schema_version"),content_hash:nullableString(r.content_hash,"revision.content_hash"),lock_version:positive(r.lock_version,"revision.lock_version"),config:r.config===null?null:parseConfig(r.config),player_count:nonnegative(r.player_count,"revision.player_count"),role_summary:typeof r.role_summary === "string" ? r.role_summary : fail("revision.role_summary"),created_at:date(r.created_at,"revision.created_at"),updated_at:date(r.updated_at,"revision.updated_at"),published_at:nullableDate(r.published_at,"revision.published_at"),published_by:nullableString(r.published_by,"revision.published_by") }; }
function parseConfig(value:unknown):RuleSetConfig { const r=record(value), counts=record(r.role_counts); return { name:string(r.name,"config.name"),description:typeof r.description === "string"?r.description:fail("config.description"),complexity:string(r.complexity,"config.complexity"),estimated_duration:string(r.estimated_duration,"config.estimated_duration"),rule_tags:array(r.rule_tags,"config.rule_tags").map(x=>string(x,"config.rule_tags")),role_counts:Object.fromEntries(ROLE_IDS.map(id=>[id,nonnegative(counts[id],`config.role_counts.${id}`)])) as RuleSetConfig["role_counts"],win_condition:oneOf(r.win_condition,["wolves_gte_others","slaughter_side"] as const,"config.win_condition"),sheriff_enabled:boolean(r.sheriff_enabled,"config.sheriff_enabled"),sheriff_vote_weight:number(r.sheriff_vote_weight,"config.sheriff_vote_weight"),speech_policy:oneOf(r.speech_policy,["sequential","sheriff_directed"] as const,"config.speech_policy"),werewolf_self_explosion_enabled:boolean(r.werewolf_self_explosion_enabled,"config.werewolf_self_explosion_enabled"),sheriff_badge_bomb_policy:oneOf(r.sheriff_badge_bomb_policy,["none","double"] as const,"config.sheriff_badge_bomb_policy") }; }
function parseUsage(v:unknown):RuleSetUsage{const r=record(v);return{game_count:nonnegative(r.game_count,"usage.game_count"),live_count:nonnegative(r.live_count,"usage.live_count")}}
function parseWarning(v:unknown):RuleSetWarning{const r=record(v);return{code:string(r.code,"warning.code"),path:string(r.path,"warning.path"),message:string(r.message,"warning.message")}}
function stringArray(v:unknown,n:string):string[]{return array(v,n).map((item)=>string(item,n))}
function nonemptyStringArray(v:unknown,n:string):string[]{const values=stringArray(v,n);return values.length?values:fail(n)}
function rejectForbidden(value:unknown,allowValidationRoot=false,path="root"):void { if(Array.isArray(value)){value.forEach((x,i)=>rejectForbidden(x,false,`${path}[${i}]`));return;} if(!isRecord(value))return; for(const [key,child] of Object.entries(value)){if(allowValidationRoot&&path==="root"&&key==="compiled_snapshot")continue;if(FORBIDDEN.has(key))fail(`${path}.${key}`);rejectForbidden(child,false,`${path}.${key}`)} }
function isRecord(v:unknown):v is Record<string,unknown>{return typeof v==="object"&&v!==null&&!Array.isArray(v)}
function record(v:unknown):Record<string,unknown>{return isRecord(v)?v:fail("object")}
function array(v:unknown,n:string):unknown[]{return Array.isArray(v)?v:fail(n)}
function nonemptyArray(v:unknown,n:string):[unknown,...unknown[]]{const values=array(v,n);return values.length>0?values as [unknown,...unknown[]]:fail(n)}
function string(v:unknown,n:string):string{return typeof v==="string"&&v.length>0?v:fail(n)}
function nullableString(v:unknown,n:string):string|null{return v===null?null:string(v,n)}
function optionalNullableString(v:unknown,n:string):string|null{return v===undefined||v===null?null:string(v,n)}
function number(v:unknown,n:string):number{return typeof v==="number"&&Number.isFinite(v)?v:fail(n)}
function positiveNumber(v:unknown,n:string):number{const x=number(v,n);return x>0?x:fail(n)}
function integer(v:unknown,n:string):number{const x=number(v,n);return Number.isInteger(x)?x:fail(n)}
function positive(v:unknown,n:string):number{const x=integer(v,n);return x>0?x:fail(n)}
function nonnegative(v:unknown,n:string):number{const x=integer(v,n);return x>=0?x:fail(n)}
function boolean(v:unknown,n:string):boolean{return typeof v==="boolean"?v:fail(n)}
function oneOf<T extends string>(v:unknown,allowed:readonly T[],n:string):T{return typeof v==="string"&&allowed.includes(v as T)?v as T:fail(n)}
function date(v:unknown,n:string):string{const x=string(v,n);return !Number.isNaN(Date.parse(x))?x:fail(n)}
function nullableDate(v:unknown,n:string):string|null{return v===null?null:date(v,n)}
function unique(values: readonly unknown[], name: string):void{if(new Set(values).size!==values.length)fail(`${name}.duplicate`)}
function fail(detail:string):never{throw new AdminApiError({problem:{type:"about:blank",code:"admin_invalid_rule_set_response",title:"规则接口响应无效",status:502,detail,request_id:null}})}
