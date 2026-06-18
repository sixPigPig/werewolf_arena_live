import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  createGameRun,
  listModelOptions,
  listRuleSets,
} from "../api/gamesApi";
import { listPlayerProfiles } from "../api/playerProfilesApi";
import { FixedActionBar } from "../components/FixedActionBar";
import { MobileButton } from "../components/MobileButton";
import { StatusBanner } from "../components/StatusBanner";

const stepTitles = ["规则预设", "玩家选择", "模型和轮数", "确认开局"];
const minGameRounds = 1;
const maxGameRounds = 20;

function normalizeMaxRounds(value: number) {
  if (!Number.isFinite(value)) {
    return minGameRounds;
  }

  return Math.min(maxGameRounds, Math.max(minGameRounds, value));
}

function mutationErrorMessage(error: unknown) {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "请检查网络连接或稍后再试。";
}

export function CustomGamePage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [selectedRuleSetId, setSelectedRuleSetId] = useState("");
  const [selectedProfileIds, setSelectedProfileIds] = useState<string[]>([]);
  const [maxRounds, setMaxRounds] = useState(8);

  const ruleSetsQuery = useQuery({
    queryKey: ["rule-sets"],
    queryFn: listRuleSets,
  });
  const modelOptionsQuery = useQuery({
    queryKey: ["model-options"],
    queryFn: listModelOptions,
  });
  const playerProfilesQuery = useQuery({
    queryKey: ["player-profiles"],
    queryFn: listPlayerProfiles,
  });

  const ruleSets = useMemo(
    () => ruleSetsQuery.data?.rule_sets ?? [],
    [ruleSetsQuery.data?.rule_sets],
  );
  const models = useMemo(
    () => modelOptionsQuery.data?.models ?? [],
    [modelOptionsQuery.data?.models],
  );
  const profiles = useMemo(
    () => playerProfilesQuery.data?.profiles ?? [],
    [playerProfilesQuery.data?.profiles],
  );

  const activeRule = useMemo(
    () =>
      ruleSets.find((ruleSet) => ruleSet.id === selectedRuleSetId) ??
      ruleSets[0],
    [ruleSets, selectedRuleSetId],
  );
  const firstModel = useMemo(() => models[0], [models]);
  const selectedProfiles = useMemo(
    () =>
      selectedProfileIds
        .map((profileId) => profiles.find((profile) => profile.id === profileId))
        .filter((profile) => Boolean(profile)),
    [profiles, selectedProfileIds],
  );

  const createRunMutation = useMutation({
    mutationFn: (request: Parameters<typeof createGameRun>[0]) =>
      createGameRun(request),
    onSuccess: (run) => {
      navigate(`/live/${run.run_id}`);
    },
  });

  const toggleProfile = (profileId: string) => {
    setSelectedProfileIds((current) =>
      current.includes(profileId)
        ? current.filter((selectedId) => selectedId !== profileId)
        : [...current, profileId],
    );
  };

  const nextDisabled =
    (step === 0 && !activeRule) ||
    (step === 1 && selectedProfileIds.length === 0);

  const confirmDisabled =
    !activeRule ||
    !firstModel ||
    selectedProfileIds.length === 0 ||
    createRunMutation.isPending;

  const confirmGame = () => {
    if (!activeRule || !firstModel) {
      return;
    }

    createRunMutation.mutate({
      rule_set_id: activeRule.id,
      villager_model: firstModel.id,
      werewolf_model: firstModel.id,
      max_rounds: maxRounds,
      player_configs: selectedProfileIds.map((profileId, index) => ({
        seat: index + 1,
        profile_id: profileId,
      })),
    });
  };

  return (
    <section className="mobile-page-section">
      <header className="mobile-card">
        <p className="mobile-kicker">自定义开局</p>
        <h2>{stepTitles[step]}</h2>
        <p>
          第 {step + 1} 步 / 共 {stepTitles.length} 步
        </p>
      </header>

      <section className="mobile-card" aria-labelledby="custom-step-title">
        <h2 id="custom-step-title">{stepTitles[step]}</h2>

        {step === 0 ? (
          <>
            {ruleSetsQuery.isLoading ? <p>正在读取规则预设...</p> : null}
            {ruleSetsQuery.isError ? (
              <StatusBanner title="规则读取失败" tone="error">
                <p>规则预设暂时无法加载，请稍后再试。</p>
              </StatusBanner>
            ) : null}
            {ruleSets.map((ruleSet) => (
              <label className="mobile-choice-row" key={ruleSet.id}>
                <input
                  checked={activeRule?.id === ruleSet.id}
                  name="rule-set"
                  onChange={() => {
                    setSelectedRuleSetId(ruleSet.id);
                  }}
                  type="radio"
                />
                <span>
                  <strong>{ruleSet.name}</strong>
                  <span>
                    {ruleSet.player_count} 人
                    {ruleSet.role_summary ? ` · ${ruleSet.role_summary}` : ""}
                  </span>
                </span>
              </label>
            ))}
          </>
        ) : null}

        {step === 1 ? (
          <>
            {playerProfilesQuery.isLoading ? <p>正在读取玩家档案...</p> : null}
            {playerProfilesQuery.isError ? (
              <StatusBanner title="玩家读取失败" tone="error">
                <p>玩家档案暂时无法加载，请稍后再试。</p>
              </StatusBanner>
            ) : null}
            {profiles.map((profile) => (
              <label className="mobile-choice-row" key={profile.id}>
                <input
                  checked={selectedProfileIds.includes(profile.id)}
                  onChange={() => {
                    toggleProfile(profile.id);
                  }}
                  type="checkbox"
                />
                <span>
                  <strong>{profile.display_name}</strong>
                  <span>{profile.short_description}</span>
                </span>
              </label>
            ))}
          </>
        ) : null}

        {step === 2 ? (
          <>
            {modelOptionsQuery.isError ? (
              <StatusBanner title="模型读取失败" tone="error">
                <p>模型选项暂时无法加载，请稍后再试。</p>
              </StatusBanner>
            ) : null}
            <label className="mobile-field" htmlFor="custom-game-model">
              <span>模型</span>
              <select
                disabled
                id="custom-game-model"
                value={firstModel?.id ?? ""}
              >
                {firstModel ? (
                  <option value={firstModel.id}>{firstModel.label}</option>
                ) : (
                  <option value="">正在读取模型...</option>
                )}
              </select>
            </label>
            <label className="mobile-field" htmlFor="custom-game-max-rounds">
              <span>最大轮数</span>
              <input
                id="custom-game-max-rounds"
                max={maxGameRounds}
                min={minGameRounds}
                onChange={(event) => {
                  const nextValue = Number.parseInt(event.target.value, 10);
                  setMaxRounds(normalizeMaxRounds(nextValue));
                }}
                type="number"
                value={maxRounds}
              />
            </label>
          </>
        ) : null}

        {step === 3 ? (
          <>
            <div className="mobile-list-row">
              <strong>规则</strong>
              <span>{activeRule?.name ?? "未选择"}</span>
            </div>
            <div className="mobile-list-row">
              <strong>模型</strong>
              <span>{firstModel?.label ?? "未加载"}</span>
            </div>
            <div className="mobile-list-row">
              <strong>最大轮数</strong>
              <span>{maxRounds}</span>
            </div>
            <div>
              <strong>玩家</strong>
              {selectedProfiles.length > 0 ? (
                <p>
                  {selectedProfiles
                    .map((profile) => profile?.display_name)
                    .join("、")}
                </p>
              ) : (
                <p>未选择玩家</p>
              )}
            </div>
          </>
        ) : null}

        {createRunMutation.isError ? (
          <StatusBanner title="开局失败" tone="error">
            <p>{mutationErrorMessage(createRunMutation.error)}</p>
          </StatusBanner>
        ) : null}
      </section>

      <FixedActionBar>
        {step > 0 ? (
          <MobileButton
            disabled={createRunMutation.isPending}
            onClick={() => {
              setStep((current) => Math.max(0, current - 1));
            }}
          >
            上一步
          </MobileButton>
        ) : null}

        {step < stepTitles.length - 1 ? (
          <MobileButton
            disabled={nextDisabled}
            onClick={() => {
              setStep((current) => Math.min(stepTitles.length - 1, current + 1));
            }}
            tone="primary"
          >
            下一步
          </MobileButton>
        ) : (
          <MobileButton
            disabled={confirmDisabled}
            onClick={confirmGame}
            tone="primary"
          >
            {createRunMutation.isPending ? "开局中..." : "确认开局"}
          </MobileButton>
        )}
      </FixedActionBar>
    </section>
  );
}
