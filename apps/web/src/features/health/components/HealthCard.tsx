import { useQuery } from "@tanstack/react-query";

import { getHealth } from "../api/getHealth";

export function HealthCard() {
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
  });

  if (healthQuery.isPending) {
    return <p className="text-slate-300">Checking API...</p>;
  }

  if (healthQuery.isError) {
    return <p className="text-rose-300">API unavailable</p>;
  }

  return (
    <div className="rounded-2xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">
      API status: <span className="font-semibold">{healthQuery.data.status}</span>
    </div>
  );
}
