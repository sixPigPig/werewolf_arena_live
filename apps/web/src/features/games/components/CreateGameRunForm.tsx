import {
  Button,
  Callout,
  Container,
  TextField,
} from "../../../components/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { createGameRun } from "../api/createGameRun";
import { listRuleSets } from "../api/listRuleSets";
import {
  hasPlayerConfig,
  randomFillEmptySeats,
  removeInvalidProfileRefs,
} from "../lineupUtils";
import { LobbyRuleSelector } from "./LobbyRuleSelector";
import { PlayerConfigPanel } from "./PlayerConfigPanel";
import { RuleDetailsDrawer } from "./RuleDetailsDrawer";
import type {
  PlayerConfig,
  VirtualPlayerProfile,
} from "../types";

type CreateGameRunFormProps = {
  isProfileListLoaded?: boolean;
  profiles?: VirtualPlayerProfile[];
};

export function CreateGameRunForm({
  isProfileListLoaded = true,
  profiles = [],
}: CreateGameRunFormProps) {
  const navigate = useNavigate();
  const [selectedRuleSetId, setSelectedRuleSetId] = useState("classic_8");
  const [isRuleDrawerOpen, setIsRuleDrawerOpen] = useState(false);
  const [seed, setSeed] = useState("");
  const [maxRounds, setMaxRounds] = useState("8");
  const [playerConfigs, setPlayerConfigs] = useState<PlayerConfig[]>([]);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [playerLibraryShortage, setPlayerLibraryShortage] = useState<{
    availableCount: number;
    requiredCount: number;
  } | null>(null);
  const ruleDetailsTriggerRef = useRef<HTMLButtonElement | null>(null);

  const closeRuleDetails = useCallback(() => {
    setIsRuleDrawerOpen(false);
  }, []);
  const handleRuleSetChange = useCallback((ruleSetId: string) => {
    setIsRuleDrawerOpen(false);
    setSelectedRuleSetId(ruleSetId);
  }, []);

  const ruleSetsQuery = useQuery({
    queryKey: ["rule-sets"],
    queryFn: listRuleSets,
  });

  const mutation = useMutation({
    mutationFn: createGameRun,
    onSuccess: (run) => navigate(`/games/live/${run.run_id}`),
  });

  const ruleSets = ruleSetsQuery.data?.rule_sets ?? [];
  const selectedRuleSet =
    ruleSets.find((rule) => rule.id === selectedRuleSetId) ??
    ruleSets[0] ??
    null;
  const isSubmitDisabled =
    mutation.isPending ||
    ruleSetsQuery.isPending ||
    ruleSetsQuery.isError ||
    !isProfileListLoaded;
  const validProfileIds = new Set(profiles.map((profile) => profile.id));
  const visiblePlayerConfigs = removeInvalidProfileRefs(
    playerConfigs,
    validProfileIds,
  );

  return (
    <form
      className="games-create-module lobby-console-form"
      data-testid="games-create-module"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        const parsedMaxRounds = Number(maxRounds);
        if (
          !maxRounds ||
          !Number.isInteger(parsedMaxRounds) ||
          parsedMaxRounds < 1 ||
          parsedMaxRounds > 20
        ) {
          setValidationError("最大轮数必须是 1 到 20 的整数");
          setPlayerLibraryShortage(null);
          return;
        }

        setValidationError(null);
        setPlayerLibraryShortage(null);
        const basePlayerConfigs = selectedRuleSet
          ? normalizePlayerConfigs(
              visiblePlayerConfigs,
              selectedRuleSet.player_count,
            )
          : [];
        const filledPlayerConfigs = selectedRuleSet
          ? normalizePlayerConfigs(
              randomFillEmptySeats(
                basePlayerConfigs,
                profiles,
                selectedRuleSet.player_count,
              ),
              selectedRuleSet.player_count,
            )
          : [];
        const selectedProfileCount = new Set(
          filledPlayerConfigs
            .map((config) => config.profile_id)
            .filter((profileId): profileId is string => Boolean(profileId)),
        ).size;
        if (selectedRuleSet && selectedProfileCount < selectedRuleSet.player_count) {
          setPlayerLibraryShortage({
            availableCount: profiles.length,
            requiredCount: selectedRuleSet.player_count,
          });
          return;
        }
        mutation.mutate({
          rule_set_id: selectedRuleSetId,
          seed: seed ? Number(seed) : null,
          max_rounds: parsedMaxRounds,
          player_configs: filledPlayerConfigs,
        });
      }}
    >
      <section className="lobby-console-bar" data-testid="lobby-console-bar">
        <div className="lobby-console-title-block">
          <h1 className="lobby-console-title">狼人杀对局大厅</h1>
        </div>
        <div className="lobby-console-controls" data-testid="lobby-console-controls">
          <label className="lobby-console-field lobby-console-field-seed">
            <span className="lobby-console-field-label">随机种子</span>
            <TextField.Root
              className="lobby-console-input"
              inputMode="numeric"
              placeholder="可留空"
              value={seed}
              onChange={(event) => setSeed(event.target.value)}
            />
          </label>
          <label className="lobby-console-field lobby-console-field-rounds">
            <span className="lobby-console-field-label">最大轮数</span>
            <TextField.Root
              className="lobby-console-input"
              min={1}
              max={20}
              required
              type="number"
              value={maxRounds}
              onChange={(event) => {
                setMaxRounds(event.target.value);
                setValidationError(null);
              }}
            />
          </label>
          <Button
            className="lobby-console-launch"
            disabled={isSubmitDisabled}
            intent="warning"
            loading={mutation.isPending}
            size="1"
            skin="gothic"
            type="submit"
          >
            发起对局
          </Button>
        </div>
      </section>

      <Container
        aria-labelledby="lobby-rules-title"
        as="section"
        className="lobby-rules-panel"
        contentClassName="lobby-rules-panel-content"
        data-testid="lobby-rules-panel"
        size="2"
      >
        <h2 className="lobby-rules-legend" id="lobby-rules-title">
          <span aria-hidden="true" className="lobby-rules-legend-mark" />
          官方规则
        </h2>
        <div className="lobby-rules-content">
          <LobbyRuleSelector
            error={ruleSetsQuery.isError}
            loading={ruleSetsQuery.isPending}
            onValueChange={handleRuleSetChange}
            rules={ruleSets}
            value={selectedRuleSetId}
          />
          {selectedRuleSet ? (
            <>
              <button
                aria-expanded={isRuleDrawerOpen}
                aria-haspopup="dialog"
                className="gothic-button gothic-button-sm"
                data-intent="default"
                onClick={() => setIsRuleDrawerOpen(true)}
                ref={ruleDetailsTriggerRef}
                type="button"
              >
                <span className="gothic-button-content">
                  <span className="gothic-button-label">规则详情</span>
                </span>
              </button>
              <RuleDetailsDrawer
                onClose={closeRuleDetails}
                open={isRuleDrawerOpen}
                returnFocusRef={ruleDetailsTriggerRef}
                rule={selectedRuleSet}
              />
              <PlayerConfigPanel
                configs={visiblePlayerConfigs}
                isProfileListLoaded={isProfileListLoaded}
                onChange={setPlayerConfigs}
                playerCount={selectedRuleSet.player_count}
                profiles={profiles}
              />
            </>
          ) : null}
        </div>
      </Container>

      {validationError ? (
        <Callout.Root className="lobby-form-callout" color="red" size="1" variant="soft">
          <Callout.Text>{validationError}</Callout.Text>
        </Callout.Root>
      ) : null}
      {mutation.isError ? (
        <Callout.Root className="lobby-form-callout" color="red" size="1" variant="soft">
          <Callout.Text>无法发起对局</Callout.Text>
        </Callout.Root>
      ) : null}
      {playerLibraryShortage ? (
        <PlayerLibraryShortageDialog
          availableCount={playerLibraryShortage.availableCount}
          onClose={() => setPlayerLibraryShortage(null)}
          requiredCount={playerLibraryShortage.requiredCount}
        />
      ) : null}
    </form>
  );
}

function PlayerLibraryShortageDialog({
  availableCount,
  onClose,
  requiredCount,
}: {
  availableCount: number;
  onClose: () => void;
  requiredCount: number;
}) {
  return (
    <div className="lobby-profile-shortage-dialog-backdrop">
      <section
        aria-labelledby="lobby-profile-shortage-title"
        aria-modal="true"
        className="lobby-profile-shortage-dialog"
        role="dialog"
      >
        <h3
          className="lobby-profile-shortage-title"
          id="lobby-profile-shortage-title"
        >
          玩家库玩家不足
        </h3>
        <p className="lobby-profile-shortage-copy">
          当前规则需要 {requiredCount} 名虚拟玩家，玩家库当前只有{" "}
          {availableCount} 名可用玩家。请先新建玩家后再发起对局。
        </p>
        <div className="lobby-profile-shortage-actions">
          <Button asChild intent="primary" size="1" skin="gothic">
            <Link to="/players">去新建玩家</Link>
          </Button>
          <Button onClick={onClose} size="1" skin="gothic" type="button">
            继续调整
          </Button>
        </div>
      </section>
    </div>
  );
}

function normalizePlayerConfigs(configs: PlayerConfig[], playerCount: number) {
  return configs
    .filter((config) => config.seat >= 1 && config.seat <= playerCount)
    .map((config) => {
      const normalized: PlayerConfig = { seat: config.seat };
      const model = config.model?.trim();
      if (config.profile_id) {
        normalized.profile_id = config.profile_id;
      }
      if (model) {
        normalized.model = model;
      }
      if (config.personality_id) {
        normalized.personality_id = config.personality_id;
      }
      if (config.appearance_id) {
        normalized.appearance_id = config.appearance_id;
      }
      return normalized;
    })
    .filter((config) => hasPlayerConfig(config))
    .sort((left, right) => left.seat - right.seat);
}
