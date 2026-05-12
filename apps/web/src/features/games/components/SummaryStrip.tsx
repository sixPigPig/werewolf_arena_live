import { Card } from "../../../components/ui";

type SummaryStripProps = {
  summaries: Record<string, string>;
};

export function SummaryStrip({ summaries }: SummaryStripProps) {
  const entries = Object.entries(summaries);

  if (entries.length === 0) {
    return <p className="text-sm text-slate-500">无总结记录</p>;
  }

  return (
    <div className="grid gap-2">
      {entries.map(([actor, summary]) => (
        <Card asChild key={actor} size="1" variant="surface">
          <p className="break-words text-sm text-slate-700">
            <span className="font-medium text-slate-950">{actor}</span>：
            {summary}
          </p>
        </Card>
      ))}
    </div>
  );
}
