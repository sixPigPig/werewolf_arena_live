import type { DebugItem } from "../types";

type DebugPanelProps = {
  item: DebugItem | null;
};

function formatParsed(parsed: unknown) {
  if (parsed === null || parsed === undefined) {
    return "无内容";
  }

  return JSON.stringify(parsed, null, 2);
}

export function DebugPanel({ item }: DebugPanelProps) {
  if (!item) {
    return (
      <aside className="rounded border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-600">
        选择一条行动查看模型输入输出
      </aside>
    );
  }

  return (
    <aside className="rounded border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-base font-semibold text-slate-950">{item.title}</h2>
        <dl className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-600">
          <div>
            <dt className="font-medium text-slate-500">Round</dt>
            <dd>{item.roundNumber}</dd>
          </div>
          <div>
            <dt className="font-medium text-slate-500">Actor</dt>
            <dd className="break-words">{item.actor}</dd>
          </div>
          <div className="col-span-2">
            <dt className="font-medium text-slate-500">Choice</dt>
            <dd className="break-words">{item.choice ?? "无"}</dd>
          </div>
        </dl>
      </div>

      <div className="space-y-4 p-4">
        <DebugBlock label="Prompt" value={item.prompt || "无内容"} />
        <DebugBlock label="Raw Response" value={item.rawResponse || "无内容"} />
        <DebugBlock label="Parsed Result" value={formatParsed(item.parsed)} />
      </div>
    </aside>
  );
}

function DebugBlock({ label, value }: { label: string; value: string }) {
  return (
    <section>
      <h3 className="text-xs font-semibold uppercase text-slate-500">{label}</h3>
      <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-3 text-xs leading-5 text-slate-50">
        {value}
      </pre>
    </section>
  );
}
