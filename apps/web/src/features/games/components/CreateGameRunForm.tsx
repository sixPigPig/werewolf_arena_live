import { Button, Callout } from "../../../components/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { createGameRun } from "../api/createGameRun";
import { listRuleSets } from "../api/listRuleSets";
import {
  clearAllSeats,
  hasPlayerConfig,
  randomFillEmptySeats,
  removeInvalidProfileRefs,
  resizeLineupForPlayerCount,
} from "../lineupUtils";
import { LobbyActionBar } from "./LobbyActionBar";
import { LobbyLineupWorkbench } from "./LobbyLineupWorkbench";
import { LobbyRuleSelector } from "./LobbyRuleSelector";
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
  const [lineupResizeNotice, setLineupResizeNotice] = useState<string | null>(
    null,
  );
  const [validationError, setValidationError] = useState<string | null>(null);
  const [playerLibraryShortage, setPlayerLibraryShortage] = useState<{
    availableCount: number;
    requiredCount: number;
  } | null>(null);
  const ruleDetailsTriggerRef = useRef<HTMLButtonElement | null>(null);

  const closeRuleDetails = useCallback(() => {
    setIsRuleDrawerOpen(false);
  }, []);

  const ruleSetsQuery = useQuery({
    queryKey: ["rule-sets"],
    queryFn: listRuleSets,
  });

  const mutation = useMutation({
    mutationFn: createGameRun,
    onSuccess: (run) => navigate(`/games/live/${run.run_id}`),
  });

  const ruleSets = useMemo(
    () => ruleSetsQuery.data?.rule_sets ?? [],
    [ruleSetsQuery.data?.rule_sets],
  );
  const selectedRuleSet =
    ruleSets.find((rule) => rule.id === selectedRuleSetId) ??
    ruleSets[0] ??
    null;
  const isSubmitDisabled =
    mutation.isPending ||
    ruleSetsQuery.isPending ||
    ruleSetsQuery.isError ||
    !isProfileListLoaded;
  const validProfileIds = useMemo(
    () => new Set(profiles.map((profile) => profile.id)),
    [profiles],
  );
  const visiblePlayerConfigs = removeInvalidProfileRefs(
    playerConfigs,
    validProfileIds,
  );
  const handleRuleSetChange = useCallback((ruleSetId: string) => {
    setIsRuleDrawerOpen(false);
    setSelectedRuleSetId(ruleSetId);

    const nextRule = ruleSets.find((rule) => rule.id === ruleSetId);
    if (!nextRule) {
      setLineupResizeNotice(null);
      return;
    }

    setPlayerConfigs((previousConfigs) => {
      const currentVisibleConfigs = removeInvalidProfileRefs(
        previousConfigs,
        validProfileIds,
      );
      const resizedLineup = resizeLineupForPlayerCount(
        currentVisibleConfigs,
        nextRule.player_count,
      );
      const visibleSeats = new Set(
        currentVisibleConfigs.map((config) => config.seat),
      );
      const hiddenConfigs = previousConfigs.filter(
        (config) => !visibleSeats.has(config.seat),
      );

      setLineupResizeNotice(
        resizedLineup.removedSeats.length > 0
          ? `已移除 ${formatSeatRange(resizedLineup.removedSeats)}的 ${
              resizedLineup.removedSeats.length
            } 名玩家`
          : null,
      );

      return [...hiddenConfigs, ...resizedLineup.configs].sort(
        (left, right) => left.seat - right.seat,
      );
    });
  }, [ruleSets, validProfileIds]);

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
      <header className="lobby-workbench-heading">
        <h1 className="lobby-console-title">狼人杀对局大厅</h1>
        {lineupResizeNotice ? (
          <p className="lobby-lineup-resize-notice" role="status">
            {lineupResizeNotice}
          </p>
        ) : null}
      </header>

      <div
        className="lobby-workbench-frame"
        data-testid="lobby-workbench-frame"
      >
        <LobbyRuleSelector
          error={ruleSetsQuery.isError}
          loading={ruleSetsQuery.isPending}
          onValueChange={handleRuleSetChange}
          rules={ruleSets}
          value={selectedRuleSetId}
        />
        {selectedRuleSet ? (
          <>
            <RuleDetailsDrawer
              onClose={closeRuleDetails}
              open={isRuleDrawerOpen}
              returnFocusRef={ruleDetailsTriggerRef}
              rule={selectedRuleSet}
            />
            <LobbyLineupWorkbench
              configs={visiblePlayerConfigs}
              isProfileListLoaded={isProfileListLoaded}
              isRuleDetailsOpen={isRuleDrawerOpen}
              onChange={setPlayerConfigs}
              onOpenRuleDetails={() => setIsRuleDrawerOpen(true)}
              playerCount={selectedRuleSet.player_count}
              profiles={profiles}
              rule={selectedRuleSet}
              ruleDetailsTriggerRef={ruleDetailsTriggerRef}
            />
          </>
        ) : null}

        <LobbyActionBar
          disabled={isSubmitDisabled}
          loading={mutation.isPending}
          maxRounds={maxRounds}
          onClearAll={() => setPlayerConfigs(clearAllSeats())}
          onFillFavorites={() => {
            if (selectedRuleSet) {
              setPlayerConfigs(
                randomFillEmptySeats(
                  visiblePlayerConfigs,
                  profiles,
                  selectedRuleSet.player_count,
                  { favoritesOnly: true },
                ),
              );
            }
          }}
          onMaxRoundsChange={(value) => {
            setMaxRounds(value);
            setValidationError(null);
          }}
          onRandomFill={() => {
            if (selectedRuleSet) {
              setPlayerConfigs(
                randomFillEmptySeats(
                  visiblePlayerConfigs,
                  profiles,
                  selectedRuleSet.player_count,
                ),
              );
            }
          }}
          onSeedChange={setSeed}
          seed={seed}
        />
      </div>

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

function formatSeatRange(seats: number[]) {
  if (seats.length === 1) return `${seats[0]} 号位`;
  const consecutive = seats.every(
    (seat, index) => index === 0 || seat === seats[index - 1] + 1,
  );
  return consecutive
    ? `${seats[0]}-${seats[seats.length - 1]} 号位`
    : `${seats.join("、")} 号位`;
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
