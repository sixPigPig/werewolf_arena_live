import {
  Badge,
  Button,
  Callout,
  Container,
  Flex,
  RadioCards,
  Text,
  TextField,
} from "../../../components/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { createGameRun } from "../api/createGameRun";
import { listRuleSets } from "../api/listRuleSets";
import {
  hasPlayerConfig,
  randomFillEmptySeats,
  removeInvalidProfileRefs,
} from "../lineupUtils";
import { PlayerConfigPanel } from "./PlayerConfigPanel";
import type {
  PlayerConfig,
  RuleSetSummary,
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
  const [seed, setSeed] = useState("");
  const [maxRounds, setMaxRounds] = useState("8");
  const [playerConfigs, setPlayerConfigs] = useState<PlayerConfig[]>([]);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [playerLibraryShortage, setPlayerLibraryShortage] = useState<{
    availableCount: number;
    requiredCount: number;
  } | null>(null);

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

  const renderRuleCard = (rule: RuleSetSummary) => {
    const roleSummary = formatRoleSummary(rule);
    const isSelected = selectedRuleSetId === rule.id;

    return (
      <RadioCards.Item
        aria-label={rule.name}
        className={[
          "lobby-rule-card",
          isSelected ? "lobby-rule-card-selected" : "",
        ].join(" ")}
        key={rule.id}
        value={rule.id}
      >
        <span aria-hidden="true" className="lobby-rule-card-glint" />
        <div className="lobby-rule-card-body">
          <span
            aria-hidden="true"
            className={[
              "lobby-rule-emblem",
              isSelected ? "lobby-rule-emblem-selected" : "",
            ].join(" ")}
          >
            {getRuleEmblem(rule)}
          </span>
          <div className="lobby-rule-copy">
            <Text as="span" className="lobby-rule-name" size="3" weight="bold">
              {rule.name}
            </Text>
            <Text as="span" className="lobby-rule-meta" size="2">
              {rule.player_count} 人 · {rule.complexity ?? "标准"} ·{" "}
              {rule.estimated_duration ?? "中"}
            </Text>
            <Text as="span" className="lobby-rule-roles" size="2">
              {roleSummary}
            </Text>
            {rule.rule_tags && rule.rule_tags.length > 0 ? (
              <Flex className="lobby-rule-tags" gap="1" wrap="wrap">
                {rule.rule_tags.map((tag) => (
                  <Badge
                    className="lobby-rule-tag"
                    color="gray"
                    key={tag}
                    variant="surface"
                  >
                    {tag}
                  </Badge>
                ))}
              </Flex>
            ) : null}
          </div>
        </div>
      </RadioCards.Item>
    );
  };

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
        {ruleSetsQuery.isPending ? (
          <p className="lobby-rules-status">正在读取官方规则...</p>
        ) : null}
        {ruleSetsQuery.isError ? (
          <p className="lobby-rules-error">无法读取官方规则</p>
        ) : null}
        {ruleSets.length > 0 ? (
          <div className="lobby-rules-content">
            <RadioCards.Root
              aria-label="官方规则"
              className="lobby-rule-grid"
              highContrast
              onValueChange={setSelectedRuleSetId}
              value={selectedRuleSetId}
              variant="surface"
            >
              {ruleSets.map(renderRuleCard)}
            </RadioCards.Root>
            {selectedRuleSet ? (
              <>
                <SelectedRuleDetails rule={selectedRuleSet} />
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
        ) : null}
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

function SelectedRuleDetails({ rule }: { rule: RuleSetSummary }) {
  const roleSummary = formatRoleSummary(rule);
  const rows = [
    { label: "阵营配置", value: roleSummary },
    { label: "发言顺序", value: formatSpeechPolicy(rule) },
    { label: "警长规则", value: formatSheriffRule(rule) },
    { label: "胜利条件", value: formatWinCondition(rule) },
    { label: "复盘提示", value: formatReplayHint(rule) },
  ];

  return (
    <section
      className="lobby-rule-details"
      data-testid="selected-rule-details"
    >
      <div
        aria-hidden="true"
        className="lobby-rule-details-glyph"
      >
        狼
      </div>
      <div className="lobby-rule-details-header">
        <span
          aria-hidden="true"
          className="lobby-rule-details-emblem"
        >
          {getRuleEmblem(rule)}
        </span>
        <div className="lobby-rule-details-title-block">
          <h3 className="lobby-rule-details-title">{rule.name}规则</h3>
          {rule.description ? (
            <p className="lobby-rule-details-description">{rule.description}</p>
          ) : null}
        </div>
      </div>
      <dl className="lobby-rule-details-list">
        {rows.map((row) => (
          <div
            className="lobby-rule-details-row"
            key={row.label}
          >
            <dt className="lobby-rule-details-label">{row.label}</dt>
            <dd className="lobby-rule-details-value">{row.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function formatRoleSummary(rule: RuleSetSummary) {
  if (rule.role_summary) {
    return rule.role_summary;
  }

  return rule.roles.map((role) => `${role.count} ${role.role}`).join(" / ");
}

function getRuleEmblem(rule: RuleSetSummary) {
  if (rule.sheriff_enabled) {
    return "警";
  }

  if (rule.name.includes("新手")) {
    return "新";
  }

  if (rule.name.includes("社交")) {
    return "社";
  }

  return "典";
}

function formatSpeechPolicy(rule: RuleSetSummary) {
  if (rule.speech_policy === "sheriff_directed") {
    return "警长决定警左或警右，所有玩家完成完整发言";
  }

  return "顺序发言";
}

function formatSheriffRule(rule: RuleSetSummary) {
  if (!rule.sheriff_enabled) {
    return "无警长";
  }

  const voteWeight = rule.sheriff_vote_weight ?? 1.5;
  return `有警长，警徽 ${voteWeight} 票`;
}

function formatWinCondition(rule: RuleSetSummary) {
  if (
    rule.win_condition === "slaughter_side" ||
    rule.rule_tags?.includes("屠边")
  ) {
    return "狼人淘汰所有神民或村民；好人放逐所有狼人";
  }

  return "狼人数量大于等于其他存活玩家；好人放逐所有狼人";
}

function formatReplayHint(rule: RuleSetSummary) {
  const nightActions = rule.night_actions ?? [];
  const hasNightRoles = nightActions.length > 1;
  const hasSheriff = Boolean(rule.sheriff_enabled);

  if (hasSheriff) {
    return "显示上警、警徽流、投票轨迹与关键发言";
  }

  if (hasNightRoles) {
    return "显示夜间行动、投票轨迹与关键发言";
  }

  return "突出发言博弈、投票轨迹与关键轮次";
}
