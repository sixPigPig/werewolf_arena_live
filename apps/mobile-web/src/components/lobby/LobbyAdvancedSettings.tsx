import { useEffect, useRef } from "react";

import type { ConfiguredAudioMode } from "../../match/contracts";

type LobbyAdvancedSettingsProps = {
  audioMode: ConfiguredAudioMode;
  disabled: boolean;
  maxRounds: string;
  maxRoundsError: string | null;
  onAudioModeChange: (value: ConfiguredAudioMode) => void;
  onMaxRoundsChange: (value: string) => void;
  onSeedChange: (value: string) => void;
  seed: string;
};

export function LobbyAdvancedSettings({ audioMode, disabled, maxRounds, maxRoundsError, onAudioModeChange, onMaxRoundsChange, onSeedChange, seed }: LobbyAdvancedSettingsProps) {
  const detailsRef = useRef<HTMLDetailsElement | null>(null);
  const roundsRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    if (!maxRoundsError) return;
    if (detailsRef.current) detailsRef.current.open = true;
    roundsRef.current?.focus();
  }, [maxRoundsError]);
  const seedSummary = seed ? `种子 ${seed}` : "随机种子";
  const roundsSummary = maxRounds ? `${maxRounds}轮` : "轮数未设置";
  const audioSummary = audioMode === "tts" ? "语音播报" : "纯文本";
  return (
    <details className="mobile-lobby-advanced" ref={detailsRef}>
      <summary>高级设置 · {seedSummary} / {roundsSummary} / {audioSummary}</summary>
      <div className="mobile-lobby-settings-grid">
        <label className="mobile-lobby-field"><span>种子</span><input disabled={disabled} inputMode="numeric" onChange={(event) => onSeedChange(event.target.value)} placeholder="随机" type="number" value={seed} /></label>
        <label className="mobile-lobby-field"><span>最大轮数</span><input aria-describedby={maxRoundsError ? "mobile-max-rounds-error" : undefined} aria-invalid={Boolean(maxRoundsError)} disabled={disabled} inputMode="numeric" max={20} min={1} onChange={(event) => onMaxRoundsChange(event.target.value)} ref={roundsRef} type="number" value={maxRounds} /></label>
        <label className="mobile-lobby-field"><span>播报方式</span><select disabled={disabled} onChange={(event) => onAudioModeChange(event.target.value as ConfiguredAudioMode)} value={audioMode}><option value="tts">语音播报</option><option value="text_only">纯文本（无 TTS）</option></select></label>
      </div>
      {maxRoundsError ? <p id="mobile-max-rounds-error" role="alert">{maxRoundsError}</p> : null}
    </details>
  );
}
