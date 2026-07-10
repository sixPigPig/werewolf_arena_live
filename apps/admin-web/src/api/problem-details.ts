export type AdminProblemDetails = {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  request_id: string | null;
  current_version?: number;
  errors?: AdminFieldError[];
};

export type AdminFieldError = {
  field: string;
  message: string;
};

type AdminApiErrorOptions = {
  cause?: unknown;
  problem: AdminProblemDetails;
};

export class AdminApiError extends Error {
  readonly code: string;
  readonly problem: AdminProblemDetails;
  readonly requestId: string | null;
  readonly status: number;
  readonly currentVersion: number | null;
  readonly fieldErrors: AdminFieldError[];

  constructor({ cause, problem }: AdminApiErrorOptions) {
    super(problem.detail || problem.title, { cause });
    this.name = "AdminApiError";
    this.code = problem.code;
    this.problem = problem;
    this.requestId = problem.request_id;
    this.status = problem.status;
    this.currentVersion = problem.current_version ?? null;
    this.fieldErrors = problem.errors ?? [];
  }
}

export function isAdminApiError(
  error: unknown,
  status?: number,
): error is AdminApiError {
  return (
    error instanceof AdminApiError &&
    (status === undefined || error.status === status)
  );
}

export function normalizeProblemDetails(
  value: unknown,
  fallback: {
    status: number;
    statusText?: string;
    requestId?: string | null;
  },
): AdminProblemDetails {
  const record = isRecord(value) ? value : {};
  const status =
    fallback.status > 0
      ? fallback.status
      : (numberValue(record.status) ?? fallback.status);
  const title =
    stringValue(record.title) ??
    stringValue(fallback.statusText) ??
    (status > 0 ? `请求失败（${status}）` : "无法连接后台服务");

  return {
    type: stringValue(record.type) ?? "about:blank",
    title,
    status,
    detail: stringValue(record.detail) ?? title,
    code:
      stringValue(record.code) ??
      (status > 0 ? "admin_request_failed" : "admin_network_error"),
    request_id:
      stringValue(record.request_id) ?? fallback.requestId ?? null,
    ...(positiveInteger(record.current_version) !== undefined
      ? { current_version: positiveInteger(record.current_version) }
      : {}),
    ...(normalizeFieldErrors(record.errors).length > 0
      ? { errors: normalizeFieldErrors(record.errors) }
      : {}),
  };
}

function normalizeFieldErrors(value: unknown): AdminFieldError[] {
  if (Array.isArray(value)) {
    return value.flatMap((item) => {
      if (!isRecord(item)) {
        return [];
      }
      const field = stringValue(item.field) ?? stringValue(item.loc);
      const message = stringValue(item.message) ?? stringValue(item.msg);
      return field && message ? [{ field, message }] : [];
    });
  }
  if (!isRecord(value)) {
    return [];
  }
  return Object.entries(value).flatMap(([field, messages]) => {
    if (typeof messages === "string") {
      return [{ field, message: messages }];
    }
    if (!Array.isArray(messages)) {
      return [];
    }
    return messages.flatMap((message) =>
      typeof message === "string" ? [{ field, message }] : [],
    );
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function positiveInteger(value: unknown) {
  return typeof value === "number" && Number.isInteger(value) && value > 0
    ? value
    : undefined;
}
