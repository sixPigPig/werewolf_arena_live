import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Badge, Button, Callout, Heading, Text } from "../components/ui";
import {
  generateJudgeVoiceLines,
  listJudgeVoiceLines,
  type GenerateJudgeVoiceLinesResponse,
  type JudgeVoiceAsset,
} from "../features/judgeVoice/api";

const queryKey = ["judge-voice-lines"];

export function JudgeVoiceAssetsPage() {
  const queryClient = useQueryClient();
  const [lastResult, setLastResult] =
    useState<GenerateJudgeVoiceLinesResponse | null>(null);
  const { data, isError, isPending } = useQuery({
    queryKey,
    queryFn: listJudgeVoiceLines,
  });
  const missingCount = useMemo(
    () => data?.lines.filter((line) => !line.exists).length ?? 0,
    [data?.lines],
  );
  const generatedCount = (data?.lines.length ?? 0) - missingCount;
  const generation = useMutation({
    mutationFn: generateJudgeVoiceLines,
    onSuccess: (result) => {
      setLastResult(result);
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  return (
    <main className="min-h-screen px-4 py-6 text-slate-100 sm:px-6 lg:px-8">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
        <header className="flex flex-col gap-4 border-b border-slate-200/15 pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <Text className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-200/80">
              Judge Voice
            </Text>
            <Heading
              as="h1"
              className="mt-2 font-serif text-3xl font-black text-[#f2dfc7] sm:text-4xl"
            >
              法官语音资产
            </Heading>
            {data ? (
              <Text as="p" className="mt-2 text-sm text-slate-300">
                {data.audio_format.toUpperCase()} · {data.sample_rate} Hz · 已生成{" "}
                {generatedCount} / {data.lines.length}
              </Text>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-3">
            <Button
              disabled={isPending || missingCount === 0}
              intent="primary"
              loading={generation.isPending && !generation.variables?.force}
              onClick={() => generation.mutate({ force: false })}
              skin="gothic"
            >
              生成缺失语音
            </Button>
            <Button
              disabled={isPending || !data}
              intent="warning"
              loading={generation.isPending && generation.variables?.force}
              onClick={() => generation.mutate({ force: true })}
              skin="gothic"
            >
              重新生成全部
            </Button>
          </div>
        </header>

        {isPending ? (
          <Callout.Root>
            <Callout.Text>正在读取法官台词...</Callout.Text>
          </Callout.Root>
        ) : null}

        {isError ? (
          <Callout.Root color="red">
            <Callout.Text>无法读取法官语音资产</Callout.Text>
          </Callout.Root>
        ) : null}

        {generation.isError ? (
          <Callout.Root color="red">
            <Callout.Text>无法生成法官语音</Callout.Text>
          </Callout.Root>
        ) : null}

        {lastResult ? (
          <Callout.Root color="green">
            <Callout.Text>
              已生成 {lastResult.generated_ids.length} 条，跳过{" "}
              {lastResult.skipped_ids.length} 条。
            </Callout.Text>
          </Callout.Root>
        ) : null}

        {data ? <JudgeVoiceLineTable lines={data.lines} /> : null}
      </div>
    </main>
  );
}

function JudgeVoiceLineTable({ lines }: { lines: JudgeVoiceAsset[] }) {
  const staticLines = lines.filter((line) => !line.template_id);
  const templateGroups = groupTemplateLines(lines);

  return (
    <section
      aria-labelledby="judge-voice-lines-title"
      className="overflow-hidden border border-slate-200/15 bg-slate-950/50 shadow-[0_18px_48px_rgba(0,0,0,0.32)]"
    >
      <div className="flex items-center justify-between gap-4 border-b border-slate-200/12 px-4 py-3">
        <Heading
          as="h2"
          className="font-serif text-xl text-[#ead8bf]"
          id="judge-voice-lines-title"
        >
          台词列表
        </Heading>
        <Badge color="amber">{lines.length} 条</Badge>
      </div>
      <VoiceLinesTable lines={staticLines} />
      {templateGroups.length > 0 ? (
        <div className="divide-y divide-slate-200/10 border-t border-slate-200/12">
          {templateGroups.map((group) => (
            <TemplateLinePanel group={group} key={group.templateId} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

type TemplateLineGroup = {
  templateId: string;
  templateText: string;
  category: string;
  lines: JudgeVoiceAsset[];
};

function groupTemplateLines(lines: JudgeVoiceAsset[]): TemplateLineGroup[] {
  const groups = new Map<string, TemplateLineGroup>();

  for (const line of lines) {
    if (!line.template_id || !line.template_text) {
      continue;
    }
    const group = groups.get(line.template_id) ?? {
      templateId: line.template_id,
      templateText: line.template_text,
      category: line.category,
      lines: [],
    };
    group.lines.push(line);
    groups.set(line.template_id, group);
  }

  return Array.from(groups.values()).map((group) => ({
    ...group,
    lines: [...group.lines].sort(
      (left, right) => (left.seat_number ?? 0) - (right.seat_number ?? 0),
    ),
  }));
}

function VoiceLinesTable({ lines }: { lines: JudgeVoiceAsset[] }) {
  if (lines.length === 0) {
    return null;
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full table-fixed border-collapse text-left text-sm">
        <thead className="border-b border-slate-200/12 text-xs uppercase tracking-[0.14em] text-slate-400">
          <tr>
            <th className="w-44 px-4 py-3 font-semibold">ID</th>
            <th className="w-24 px-4 py-3 font-semibold">分类</th>
            <th className="px-4 py-3 font-semibold">台词</th>
            <th className="w-24 px-4 py-3 font-semibold">状态</th>
            <th className="w-64 px-4 py-3 font-semibold">试听</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200/10">
          {lines.map((line) => (
            <VoiceLineRow key={line.id} line={line} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TemplateLinePanel({ group }: { group: TemplateLineGroup }) {
  const [isOpen, setIsOpen] = useState(false);
  const generatedCount = group.lines.filter((line) => line.exists).length;
  const panelId = `judge-voice-template-${group.templateId}`;

  return (
    <div className="bg-black/10">
      <button
        aria-controls={panelId}
        aria-expanded={isOpen}
        className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left transition hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-amber-300/60"
        onClick={() => setIsOpen((value) => !value)}
        type="button"
      >
        <span className="min-w-0">
          <span className="block font-mono text-xs text-amber-100">
            {group.templateId}
          </span>
          <span className="mt-1 block text-sm font-semibold text-slate-100">
            {group.templateText}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-3">
          <Badge color={generatedCount === group.lines.length ? "green" : "red"}>
            已生成 {generatedCount} / {group.lines.length}
          </Badge>
          <span className="text-lg text-amber-100" aria-hidden="true">
            {isOpen ? "⌃" : "⌄"}
          </span>
        </span>
      </button>
      {isOpen ? (
        <div id={panelId}>
          <VoiceLinesTable lines={group.lines} />
        </div>
      ) : null}
    </div>
  );
}

function VoiceLineRow({ line }: { line: JudgeVoiceAsset }) {
  return (
    <tr className="align-top">
      <td className="break-words px-4 py-3 font-mono text-xs text-amber-100">
        {line.id}
      </td>
      <td className="px-4 py-3 text-slate-300">{line.category}</td>
      <td className="px-4 py-3 leading-6 text-slate-100">{line.text}</td>
      <td className="px-4 py-3">
        <Badge color={line.exists ? "green" : "red"}>
          {line.exists ? "已生成" : "缺失"}
        </Badge>
      </td>
      <td className="px-4 py-3">
        {line.exists ? (
          <audio
            aria-label={`试听 ${line.id}`}
            className="h-9 w-full min-w-44"
            controls
            preload="none"
            src={line.public_url}
          />
        ) : (
          <Text className="text-sm text-slate-400">-</Text>
        )}
      </td>
    </tr>
  );
}
