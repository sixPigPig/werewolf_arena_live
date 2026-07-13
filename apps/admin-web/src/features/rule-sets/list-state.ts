import type { RuleSetListParams, RuleSetSortField, RuleSetStatus } from "./types";
const STATUSES:RuleSetStatus[]=["draft","published","archived"];
const SORTS:RuleSetSortField[]=["display_order","updated_at","name","created_at"];
const FILTERS=new Set(["q","status","player_count","page_size"]);
export function ruleSetListParamsFromSearch(q:URLSearchParams):RuleSetListParams{return{page:positive(q.get("page"),1),page_size:pageSize(q.get("page_size")),q:optional(q.get("q")),status:enumValue(q.get("status"),STATUSES),player_count:optionalPositive(q.get("player_count")),sort:enumValue(q.get("sort"),SORTS)??"display_order",direction:q.get("direction")==="desc"?"desc":"asc"}}
export function setRuleSetSearchValues(current:URLSearchParams,values:Record<string,string|undefined>){const next=new URLSearchParams(current);let changedFilter=false;for(const[key,value]of Object.entries(values)){const normalized=value?.trim();const old=next.get(key);if(normalized)next.set(key,normalized);else next.delete(key);if(FILTERS.has(key)&&(old??"")!==(normalized??""))changedFilter=true}if(changedFilter&&!Object.prototype.hasOwnProperty.call(values,"page"))next.set("page","1");return next}
function optional(v:string|null){const n=v?.trim();return n||undefined}
function enumValue<T extends string>(v:string|null,a:readonly T[]){return a.includes(v as T)?v as T:undefined}
function positive(v:string|null,f:number){const n=Number(v);return Number.isInteger(n)&&n>0?n:f}
function optionalPositive(v:string|null){if(v===null||v.trim()==="")return undefined;const n=Number(v);return Number.isInteger(n)&&n>0?n:undefined}
function pageSize(v:string|null){const n=positive(v,20);return[10,20,50].includes(n)?n:20}
