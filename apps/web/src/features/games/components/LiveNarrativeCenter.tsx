import { Badge } from "../../../components/ui";
import type { LiveNarrativeState, NarrativeCueTone } from "../liveNarrative";
import { appearanceClassName } from "../playerProfileOptions";
import { resolveAvatarImageUrl } from "../types";

type LiveNarrativeCenterProps = {
  narrative: LiveNarrativeState;
};

const TONE_CLASS_BY_TONE: Record<NarrativeCueTone, string> = {
  danger:
    "border-red-300/35 shadow-[0_0_44px_rgba(248,113,113,0.2),0_24px_68px_rgba(0,0,0,0.38)]",
  day: "border-amber-300/30 shadow-[0_0_44px_rgba(251,191,36,0.16),0_24px_68px_rgba(0,0,0,0.38)]",
  neutral: "border-amber-300/25 shadow-[0_24px_68px_rgba(0,0,0,0.38)]",
  night:
    "border-indigo-300/35 shadow-[0_0_44px_rgba(129,140,248,0.18),0_24px_68px_rgba(0,0,0,0.38)]",
  safe: "border-teal-300/35 shadow-[0_0_44px_rgba(45,212,191,0.16),0_24px_68px_rgba(0,0,0,0.38)]",
  terminal:
    "border-emerald-300/35 shadow-[0_0_44px_rgba(52,211,153,0.18),0_24px_68px_rgba(0,0,0,0.38)]",
  vote: "border-amber-200/40 shadow-[0_0_44px_rgba(251,191,36,0.2),0_24px_68px_rgba(0,0,0,0.38)]",
};

export function LiveNarrativeCenter({ narrative }: LiveNarrativeCenterProps) {
  const { cue, speaker } = narrative;
  const displayText = cue.speechText.trim() ? cue.speechText : cue.performerLine;
  const speakerAvatarImageUrl = speaker
    ? resolveAvatarImageUrl({ avatar_image_url: speaker.avatarImageUrl })
    : "";

  return (
    <div
      className={`glass-panel-subtle absolute left-1/2 top-[51%] z-30 w-[min(31rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg border p-3 text-center sm:top-[55%] sm:p-4 ${TONE_CLASS_BY_TONE[cue.tone]}`}
      data-narrative-tone={cue.tone}
      data-testid="live-narrative-center"
    >
      <div className="mb-3 flex flex-wrap justify-center gap-2 text-xs">
        <Badge color="amber" variant="surface">
          法官旁白
        </Badge>
        <Badge color="gray" variant="surface">
          {kindLabel(cue.kind)}
        </Badge>
        {cue.eventId !== null ? (
          <Badge color="gray" variant="surface">
            #{cue.eventId}
          </Badge>
        ) : null}
      </div>

      <p className="text-sm font-semibold tracking-normal text-amber-100">
        {cue.judgeLine}
      </p>

      {speaker ? (
        <div
          className="mt-3 grid grid-cols-[5rem_minmax(0,1fr)] items-center gap-3 rounded-lg border border-amber-300/25 bg-black/45 p-3 text-left sm:grid-cols-[6rem_minmax(0,1fr)]"
          data-testid="live-narrative-speaker"
        >
          <div
            className={`relative flex aspect-[3/4] items-center justify-center overflow-hidden rounded-md border-2 border-amber-300/45 bg-gradient-to-br from-[#26323b] to-[#05070a] ${appearanceClassName(speaker.appearanceId)}`}
          >
            {speakerAvatarImageUrl ? (
              <img
                alt={`${speaker.name} 当前发言形象`}
                className="h-full w-full object-cover"
                src={speakerAvatarImageUrl}
              />
            ) : (
              <span className="text-3xl font-black text-amber-50">
                {avatarText(speaker.name)}
              </span>
            )}
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-amber-200">
              {speaker.seatNumber === null ? "席位未定" : `${speaker.seatNumber} 号`}
            </p>
            <h2 className="truncate text-xl font-semibold text-amber-50">
              {speaker.name}
            </h2>
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              <span className="rounded border border-amber-300/30 bg-amber-400/10 px-2 py-1 text-amber-100">
                {speaker.role}
              </span>
              <span className="rounded border border-sky-300/25 bg-sky-400/10 px-2 py-1 text-sky-100">
                {speaker.camp}
              </span>
            </div>
          </div>
        </div>
      ) : null}

      <div
        aria-label="旁白内容"
        className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-md border border-amber-300/15 p-3 text-left text-sm leading-6 text-slate-200 shadow-[inset_0_0_24px_rgba(0,0,0,0.24)] sm:max-h-48 sm:text-base"
        tabIndex={0}
      >
        {displayText}
      </div>

      {cue.detailLine ? (
        <p className="mt-3 text-xs font-semibold text-slate-300">
          {cue.detailLine}
        </p>
      ) : null}
    </div>
  );
}

function kindLabel(kind: LiveNarrativeState["cue"]["kind"]) {
  if (kind === "player-speaking") {
    return "公开发言";
  }
  if (kind === "player-thinking") {
    return "思考中";
  }
  if (kind === "player-action") {
    return "行动";
  }
  if (kind === "vote") {
    return "投票";
  }
  if (kind === "death") {
    return "结算";
  }
  if (kind === "terminal") {
    return "终局";
  }
  if (kind === "judge") {
    return "阶段";
  }
  return "事件";
}

function avatarText(name: string) {
  return Array.from(name).slice(0, 2).join("");
}
