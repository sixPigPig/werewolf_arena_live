import { isAdminApiError } from "@/api/problem-details";

export type RuleSetErrorContext = "options" | "list" | "duplicate" | "load" | "save" | "validate" | "reload" | "transition";

const STATUS_COPY: Partial<Record<number, string>> = {
  401: "登录状态已失效，请重新登录。",
  403: "你没有执行此规则操作的权限。",
  404: "没有找到该游戏规则。",
  409: "规则状态已发生变化，本地修改已保留。",
  412: "规则版本已更新，本地修改已保留。",
  422: "提交的规则内容不符合要求，请检查后重试。",
  503: "规则目录暂时不可用，请稍后重试。",
};

const CONTEXT_COPY: Record<RuleSetErrorContext, string> = {
  options: "规则选项暂时不可用，请重新加载。",
  list: "无法读取游戏规则，请稍后重试。",
  duplicate: "无法复制游戏规则，请检查后重试。",
  load: "无法读取游戏规则，请稍后重试。",
  save: "无法保存规则草稿，请检查后重试。",
  validate: "无法校验游戏规则，请稍后重试。",
  reload: "无法重新加载游戏规则，请稍后重试。",
  transition: "无法完成规则操作，请检查后重试。",
};

export function presentRuleSetError(error: unknown, context: RuleSetErrorContext): string {
  if (!isAdminApiError(error)) return CONTEXT_COPY[context];
  if (error.code === "admin_invalid_rule_set_response") return "规则接口响应无效，请稍后重试。";
  if (error.code === "admin_network_error") return "无法连接规则服务，请稍后重试。";
  return STATUS_COPY[error.status] ?? CONTEXT_COPY[context];
}
