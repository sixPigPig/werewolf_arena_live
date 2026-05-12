import { Callout } from "../../../components/ui";
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
    <Callout.Root color="green" highContrast variant="surface">
      <Callout.Text>
        API status: <span className="font-semibold">{healthQuery.data.status}</span>
      </Callout.Text>
    </Callout.Root>
  );
}
