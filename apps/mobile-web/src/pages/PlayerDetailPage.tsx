import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import {
  listPlayerProfiles,
  resolveAvatarImageUrl,
  type VirtualPlayerProfile,
} from "@werewolf-arena/game-client";

export function PlayerDetailPage() {
  const { playerId } = useParams();
  const playerProfilesQuery = useQuery({
    queryKey: ["player-profiles"],
    queryFn: listPlayerProfiles,
  });
  const profiles = playerProfilesQuery.data?.profiles ?? [];
  const profile = profiles.find((item) => item.id === playerId);

  return (
    <main className="mobile-page mobile-archive-page mobile-player-detail-page">
      <header className="mobile-archive-hero">
        <span>角色档案</span>
        <h1>玩家详情</h1>
        <p>查看玩家的发言风格、策略倾向和模型设定。</p>
        <Link className="mobile-button mobile-session-link" to="/players">
          返回图鉴
        </Link>
      </header>

      {playerProfilesQuery.isPending ? <p>正在读取玩家档案...</p> : null}
      {playerProfilesQuery.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法读取玩家档案
        </p>
      ) : null}
      {playerProfilesQuery.isSuccess && !profile ? (
        <section className="mobile-archive-card">
          <h2>未找到玩家档案</h2>
          <p className="mobile-archive-muted">这个角色可能已被移除或尚未同步。</p>
        </section>
      ) : null}

      {profile ? <PlayerDossier profile={profile} /> : null}
    </main>
  );
}

type PlayerDossierProps = {
  profile: VirtualPlayerProfile;
};

function PlayerDossier({ profile }: PlayerDossierProps) {
  const avatarImageUrl = resolveAvatarImageUrl(profile);

  return (
    <>
      <section className="mobile-archive-card mobile-player-detail-hero">
        {avatarImageUrl ? (
          <img
            alt={`${profile.display_name} 头像`}
            className="mobile-player-detail-avatar"
            src={avatarImageUrl}
          />
        ) : (
          <span className="mobile-player-detail-avatar-fallback">
            {profile.display_name.trim().slice(0, 1) || "?"}
          </span>
        )}
        <div className="mobile-player-detail-copy">
          <span>{profile.favorite ? "收藏档案" : "普通档案"}</span>
          <h2>{profile.display_name}</h2>
          <p>{profile.short_description || "暂无简介"}</p>
          <strong>{profile.model}</strong>
        </div>
      </section>

      <section className="mobile-archive-card">
        <div className="mobile-archive-card-heading">
          <span>人格设定</span>
          <strong>{profile.personality_id}</strong>
        </div>
        <p className="mobile-archive-body-copy">
          {profile.personality_text || profile.background_story || "暂无人格设定"}
        </p>
        {profile.tags.length > 0 ? (
          <ul className="mobile-player-tags" aria-label="玩家标签">
            {profile.tags.map((tag) => (
              <li className="mobile-player-tag" key={tag}>
                {tag}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="mobile-archive-card" aria-label="玩家策略雷达">
        <div className="mobile-archive-card-heading">
          <span>策略雷达</span>
          <strong>{profile.strategy_profile}</strong>
        </div>
        <dl className="mobile-player-trait-grid">
          <Trait label="风险" value={profile.risk_tolerance} />
          <Trait label="诈唬" value={profile.bluffing_tendency} />
          <Trait label="信任" value={profile.trust_tendency} />
          <Trait label="控场" value={profile.leadership_tendency} />
          <Trait label="话量" value={profile.talkativeness} />
        </dl>
      </section>

      <section className="mobile-archive-card">
        <div className="mobile-archive-card-heading">
          <span>发言样本</span>
          <strong>{profile.speaking_style || "未设置"}</strong>
        </div>
        {profile.catchphrases.length > 0 ? (
          <ul className="mobile-player-quote-list">
            {profile.catchphrases.map((phrase) => (
              <li key={phrase}>{phrase}</li>
            ))}
          </ul>
        ) : (
          <p className="mobile-archive-muted">暂无口头禅</p>
        )}
      </section>
    </>
  );
}

function Trait({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        <span style={{ width: `${Math.max(0, Math.min(value, 5)) * 20}%` }} />
        <strong>{value}/5</strong>
      </dd>
    </div>
  );
}
