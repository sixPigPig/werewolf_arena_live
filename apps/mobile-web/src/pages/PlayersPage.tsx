import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import {
  listPlayerProfiles,
  resolveAvatarImageUrl,
} from "@werewolf-arena/game-client";

export function PlayersPage() {
  const playerProfilesQuery = useQuery({
    queryKey: ["player-profiles"],
    queryFn: listPlayerProfiles,
  });

  const profiles = playerProfilesQuery.data?.profiles ?? [];

  return (
    <main className="mobile-page mobile-archive-page mobile-players-page">
      <header className="mobile-archive-hero">
        <span>角色档案库</span>
        <h1>玩家图鉴</h1>
        <p>编辑能力不在第一版范围内</p>
      </header>

      {playerProfilesQuery.isPending ? <p>正在读取玩家档案...</p> : null}
      {playerProfilesQuery.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法读取玩家档案
        </p>
      ) : null}
      {playerProfilesQuery.isSuccess && profiles.length === 0 ? (
        <p>暂无玩家档案</p>
      ) : null}

      {profiles.length > 0 ? (
        <section aria-label="玩家档案列表" className="mobile-player-list">
          {profiles.map((profile) => {
            const avatarImageUrl = resolveAvatarImageUrl(profile);

            return (
              <article
                aria-label={`${profile.display_name} 档案`}
                className="mobile-archive-card mobile-player-card mobile-player-dossier-card"
                key={profile.id}
              >
                {avatarImageUrl ? (
                  <img
                    alt={`${profile.display_name} 头像`}
                    className="mobile-player-avatar"
                    src={avatarImageUrl}
                  />
                ) : null}
                <div className="mobile-player-card-body">
                  <div className="mobile-player-card-heading">
                    <h2>{profile.display_name}</h2>
                    {profile.favorite ? (
                      <span className="mobile-player-favorite">收藏</span>
                    ) : null}
                  </div>
                  <p className="mobile-player-model">{profile.model}</p>
                  {profile.short_description ? (
                    <p className="mobile-player-description">
                      {profile.short_description}
                    </p>
                  ) : null}
                  {profile.tags.length > 0 ? (
                    <ul className="mobile-player-tags" aria-label="玩家标签">
                      {profile.tags.map((tag) => (
                        <li className="mobile-player-tag" key={tag}>
                          {tag}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {profile.speaking_style ? (
                    <p className="mobile-player-speaking">
                      说话风格：{profile.speaking_style}
                    </p>
                  ) : null}
                  <Link
                    aria-label={`查看${profile.display_name}档案`}
                    className="mobile-button mobile-session-link mobile-player-detail-link"
                    to={`/players/${profile.id}`}
                  >
                    查看档案
                  </Link>
                </div>
              </article>
            );
          })}
        </section>
      ) : null}
    </main>
  );
}
