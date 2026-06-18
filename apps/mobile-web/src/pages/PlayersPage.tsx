import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listPlayerProfiles } from "../api/playerProfilesApi";
import { StatusBanner } from "../components/StatusBanner";

export function PlayersPage() {
  const playersQuery = useQuery({
    queryFn: listPlayerProfiles,
    queryKey: ["mobile-player-profiles"],
  });

  return (
    <section className="mobile-page-section">
      <header className="mobile-card">
        <p className="mobile-kicker">玩家库</p>
        <h2>虚拟玩家</h2>
        <p>浏览玩家档案，并从自定义开局中挑选阵容。</p>
      </header>

      {playersQuery.isError ? (
        <StatusBanner title="玩家库不可用" tone="error">
          <p>玩家档案数据库暂时不可用，请稍后重试。</p>
        </StatusBanner>
      ) : null}

      <section className="mobile-card">
        {playersQuery.isPending ? <p>正在读取玩家库...</p> : null}
        {playersQuery.data?.profiles.map((profile) => (
          <article className="mobile-list-row" key={profile.id}>
            <div>
              <strong>{profile.display_name}</strong>
              <p>{profile.short_description || profile.model}</p>
            </div>
            <span>{profile.favorite ? "常用" : "档案"}</span>
          </article>
        ))}
        {playersQuery.data?.profiles.length === 0 ? <p>暂无玩家档案。</p> : null}
      </section>

      <Link className="mobile-link-button" to="/custom-game">
        用这些玩家开局
      </Link>
    </section>
  );
}
