import { adminApiFetch } from "@/api/client";
import { parseAdminRuleSet, parseAdminRuleSetDetail, parseAdminRuleSetList, parseRuleSetOptions, parseRuleSetValidation } from "./parsers";
import type { ArchiveRuleSetRequest, CreateRuleSetRequest, DuplicateRuleSetRequest, PublishRuleSetRequest, RuleSetListParams, RuleSetTransitionRequest, SetDefaultRuleSetRequest, UpdateRuleSetDraftRequest, ValidateRuleSetRequest } from "./types";

const PATH = "/api/v1/admin/rule-sets";
export async function getRuleSetOptions(signal?:AbortSignal){return parseRuleSetOptions(await adminApiFetch<unknown>("/api/v1/admin/rule-set-options",{signal}))}
export async function listAdminRuleSets(params:RuleSetListParams,signal?:AbortSignal){const q=new URLSearchParams({page:String(params.page),page_size:String(params.page_size)});append(q,"q",params.q);append(q,"status",params.status);if(params.player_count!==undefined)q.set("player_count",String(params.player_count));q.set("sort",`${params.direction==="desc"?"-":""}${params.sort}`);return parseAdminRuleSetList(await adminApiFetch<unknown>(`${PATH}?${q}`,{signal}))}
export async function getAdminRuleSet(id:string,signal?:AbortSignal){return parseAdminRuleSetDetail(await adminApiFetch<unknown>(`${PATH}/${encodeURIComponent(id)}`,{signal}))}
export async function createAdminRuleSet(body:CreateRuleSetRequest,csrf:string){return write(PATH,"POST",body,csrf,parseAdminRuleSet)}
export async function updateAdminRuleSetDraft(id:string,body:UpdateRuleSetDraftRequest,csrf:string){return write(action(id,"draft"),"PATCH",body,csrf,parseAdminRuleSet)}
export async function validateAdminRuleSet(id:string,body:ValidateRuleSetRequest,csrf:string){return write(action(id,"validate"),"POST",body,csrf,parseRuleSetValidation)}
export async function publishAdminRuleSet(id:string,body:PublishRuleSetRequest,csrf:string){return write(action(id,"publish"),"POST",body,csrf,parseAdminRuleSet)}
export async function archiveAdminRuleSet(id:string,body:ArchiveRuleSetRequest,csrf:string){return write(action(id,"archive"),"POST",body,csrf,parseAdminRuleSet)}
export async function restoreAdminRuleSet(id:string,body:RuleSetTransitionRequest,csrf:string){return write(action(id,"restore"),"POST",body,csrf,parseAdminRuleSet)}
export async function setDefaultAdminRuleSet(id:string,body:SetDefaultRuleSetRequest,csrf:string){return write(action(id,"set-default"),"POST",body,csrf,parseAdminRuleSet)}
export async function duplicateAdminRuleSet(id:string,body:DuplicateRuleSetRequest,csrf:string){return write(action(id,"duplicate"),"POST",body,csrf,parseAdminRuleSet)}
function action(id:string,name:string){return `${PATH}/${encodeURIComponent(id)}/${encodeURIComponent(name)}`}
async function write<T>(path:string,method:"POST"|"PATCH",body:unknown,csrf:string,parse:(v:unknown)=>T){return parse(await adminApiFetch<unknown>(path,{method,headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify(body)}))}
function append(q:URLSearchParams,key:string,value:string|undefined){const v=value?.trim();if(v)q.set(key,v)}
