export type AdminAuditEvent = {
  id: string;
  actor: { id: string; email: string; display_name: string } | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  result: string;
  reason: string | null;
  request_id: string | null;
  created_at: string;
};

export type AdminAuditList = {
  items: AdminAuditEvent[];
  pagination: { page: number; page_size: number; total: number; pages: number };
};

export type AdminAuditParams = {
  page: number;
  page_size: number;
  q?: string;
  action?: string;
  result?: string;
  resource_type?: string;
  created_from?: string;
  created_to?: string;
  direction: "asc" | "desc";
};
