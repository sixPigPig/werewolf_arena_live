import type { ReactNode } from "react";

type StatusBannerProps = {
  children: ReactNode;
  title: string;
  tone?: "info" | "error" | "success";
};

export function StatusBanner({
  children,
  title,
  tone = "info",
}: StatusBannerProps) {
  return (
    <section className={`mobile-status-banner mobile-status-banner-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <h2>{title}</h2>
      <div>{children}</div>
    </section>
  );
}
