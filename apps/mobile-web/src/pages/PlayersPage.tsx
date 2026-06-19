import { QueryClientContext, useQuery } from "@tanstack/react-query";
import { useContext } from "react";

import { listPlayerProfiles } from "@werewolf-arena/game-client";
import { queryClient } from "../lib/query-client";

export function PlayersPage() {
  const queryClientFromContext = useContext(QueryClientContext);
  const playerProfilesQuery = useQuery({
    queryKey: ["player-profiles"],
    queryFn: listPlayerProfiles,
  }, queryClientFromContext ?? queryClient);

  const profiles = playerProfilesQuery.data?.profiles ?? [];

  return (
    <main className="mobile-page">
      <header className="mobile-page-section">
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
          {profiles.map((profile) => (
            <article className="mobile-player-card" key={profile.id}>
              {profile.avatar_image_url ? (
                <img
                  alt={`${profile.display_name} 头像`}
                  className="mobile-player-avatar"
                  src={profile.avatar_image_url}
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
                  <div className="mobile-player-tags" aria-label="玩家标签">
                    {profile.tags.map((tag) => (
                      <span className="mobile-player-tag" key={tag}>
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : null}
                {profile.speaking_style ? (
                  <p className="mobile-player-speaking">
                    说话风格：{profile.speaking_style}
                  </p>
                ) : null}
              </div>
            </article>
          ))}
        </section>
      ) : null}
    </main>
  );
}
