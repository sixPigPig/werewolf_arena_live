import { isAdminApiError } from "@/api/problem-details";

export function adminOperationErrorDescription(
  error: unknown,
  fallback: string,
) {
  if (!isAdminApiError(error)) {
    return error instanceof Error && error.message ? error.message : fallback;
  }

  const metadata = [
    error.code ? `错误码：${error.code}` : null,
    error.requestId ? `请求编号：${error.requestId}` : null,
  ].filter(Boolean);
  const detail =
    error.problem.title && error.problem.title !== error.message
      ? `${error.problem.title}：${error.message}`
      : error.message;

  return metadata.length > 0
    ? `${detail}（${metadata.join("；")}）`
    : detail;
}
