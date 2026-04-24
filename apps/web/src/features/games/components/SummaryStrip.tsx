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
        <p
          className="break-words rounded border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700"
          key={actor}
        >
          <span className="font-medium text-slate-950">{actor}</span>：{summary}
        </p>
      ))}
    </div>
  );
}
