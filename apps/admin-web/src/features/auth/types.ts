export type AdminRole =
  | "viewer"
  | "content_editor"
  | "operator"
  | "super_admin";

export type AdminUser = {
  id: string;
  email: string;
  display_name: string;
  role: AdminRole;
};

export type AdminSession = {
  user: AdminUser;
  permissions: string[];
  csrf_token: string;
  session_expires_at: string;
};

export type AdminRuntimeMode = "authenticated" | "closed" | "preview";
