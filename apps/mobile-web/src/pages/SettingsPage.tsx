import { useQuery } from "@tanstack/react-query";

import { listModelOptions, listRuleSets } from "../api/gamesApi";
import { getHealth } from "../api/healthApi";
import { StatusBanner } from "../components/StatusBanner";

export function SettingsPage() {
  const healthQuery = useQuery({
    queryFn: getHealth,
    queryKey: ["mobile-health"],
  });
  const rulesQuery = useQuery({
    queryFn: listRuleSets,
    queryKey: ["mobile-rule-sets"],
  });
  const modelsQuery = useQuery({
    queryFn: listModelOptions,
    queryKey: ["mobile-model-options"],
  });

  return (
    <section className="mobile-page-section">
      <header className="mobile-card">
        <p className="mobile-kicker">设置</p>
        <h2>连接与默认项</h2>
      </header>

      {healthQuery.isError ? (
        <StatusBanner title="API 不可用" tone="error">
          <p>当前无法连接后端。</p>
        </StatusBanner>
      ) : (
        <StatusBanner
          title={healthQuery.data?.status === "ok" ? "API 正常" : "正在检查"}
          tone="success"
        >
          <p>后端地址使用当前 Vite 代理的 /api。</p>
        </StatusBanner>
      )}

      <section className="mobile-card">
        <h2>默认规则</h2>
        <p>{rulesQuery.data?.rule_sets[0]?.name ?? "正在读取规则..."}</p>
      </section>

      <section className="mobile-card">
        <h2>默认模型</h2>
        <p>{modelsQuery.data?.models[0]?.label ?? "正在读取模型..."}</p>
      </section>
    </section>
  );
}
