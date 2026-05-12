import { Card, DataList } from "../../../components/ui";

import type { DebugItem } from "../types";

type DebugPanelProps = {
  item: DebugItem | null;
};

const PARSED_FIELD_LABELS: Record<string, string> = {
  reasoning: "推理",
  run: "上警选择",
  withdraw: "退水选择",
  sheriff_vote: "警长投票对象",
  speech_order: "发言方向",
  badge: "警徽处理",
  bid: "发言意愿",
  say: "发言内容",
  vote: "投票对象",
  investigate: "查验对象",
  remove: "袭击对象",
  protect: "保护对象",
  summary: "回合总结",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatParsedValue(value: unknown) {
  if (value === null || value === undefined) {
    return "无内容";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2) ?? String(value);
}

function formatParsed(parsed: unknown) {
  if (parsed === null || parsed === undefined) {
    return "无内容";
  }

  if (!isRecord(parsed)) {
    return formatParsedValue(parsed);
  }

  const entries = Object.entries(parsed);
  if (entries.length === 0) {
    return "无内容";
  }

  return entries
    .map(([key, value]) => {
      const label = PARSED_FIELD_LABELS[key] ?? key;
      return `${label}：${formatParsedValue(value)}`;
    })
    .join("\n");
}

export function DebugPanel({ item }: DebugPanelProps) {
  if (!item) {
    return (
      <Card asChild size="2" variant="surface">
        <aside className="text-sm text-slate-600">
          选择一条行动查看模型输入输出
        </aside>
      </Card>
    );
  }

  return (
    <Card asChild size="1">
      <aside>
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-base font-semibold text-slate-950">{item.title}</h2>
        <DataList.Root className="mt-2" size="1">
          <DataList.Item>
            <DataList.Label>轮次</DataList.Label>
            <DataList.Value>{item.roundNumber}</DataList.Value>
          </DataList.Item>
          <DataList.Item>
            <DataList.Label>玩家</DataList.Label>
            <DataList.Value className="break-words">{item.actor}</DataList.Value>
          </DataList.Item>
          <DataList.Item>
            <DataList.Label>选择</DataList.Label>
            <DataList.Value className="break-words">
              {item.choice ?? "无"}
            </DataList.Value>
          </DataList.Item>
        </DataList.Root>
      </div>

      <div className="space-y-4 p-4">
        <DebugBlock label="提示词" value={item.prompt || "无内容"} />
        <DebugBlock label="模型原文" value={item.rawResponse || "无内容"} />
        <DebugBlock label="解析结果" value={formatParsed(item.parsed)} />
      </div>
      </aside>
    </Card>
  );
}

function DebugBlock({ label, value }: { label: string; value: string }) {
  return (
    <section>
      <h3 className="text-xs font-semibold uppercase text-slate-500">{label}</h3>
      <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded border border-slate-500/30 p-3 text-xs leading-5 text-slate-50">
        {value}
      </pre>
    </section>
  );
}
