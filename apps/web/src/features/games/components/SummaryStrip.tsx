import { Card } from "../../../components/ui";

type SummaryStripProps = {
  summaries: Record<string, string>;
  publicSummary?: string | null;
};

export function SummaryStrip({ summaries, publicSummary }: SummaryStripProps) {
  const publicText = publicSummary?.trim();
  if (publicText) {
    return (
      <Card asChild size="1" variant="surface">
        <p className="break-words text-sm text-slate-700">{publicText}</p>
      </Card>
    );
  }

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
