import { CreateGameRunForm } from "../../features/games/components/CreateGameRunForm";
import { ArenaNavButton } from "../../app/navigation";
import { listPlayerProfiles } from "../../features/games/api/listPlayerProfiles";
import { useQuery } from "@tanstack/react-query";
import type { RefObject } from "react";
import brandBannerSrc from "../../assets/langrensha-arena-banner.png";
import ravenCandleLeftSrc from "../../assets/lobby-decor/raven-candle-left.png";
import ravenCandleRightSrc from "../../assets/lobby-decor/raven-candle-right.png";

type GamesWorkspaceProps = {
  createFormRef: RefObject<HTMLDivElement | null>;
  onCreateGameClick: () => void;
};

export function GamesWorkspace({
  createFormRef,
  onCreateGameClick,
}: GamesWorkspaceProps) {
  const playerProfilesQuery = useQuery({
    queryKey: ["player-profiles"],
    queryFn: listPlayerProfiles,
  });
  const profiles = playerProfilesQuery.data?.profiles ?? [];
  const profileLoadError = "无法读取虚拟玩家资料，暂时不能发起对局。";

  return (
    <main
      className="games-workspace-module lobby-page-shell mx-auto w-full max-w-none px-4 pb-4 pt-1 sm:px-6 lg:px-8"
      data-testid="games-workspace-module"
    >
      <div aria-hidden="true" className="games-lobby-corner-decor">
        <img
          alt=""
          className="games-lobby-corner-decor-image games-lobby-corner-decor-left"
          data-testid="games-lobby-corner-decor-left"
          src={ravenCandleLeftSrc}
        />
        <img
          alt=""
          className="games-lobby-corner-decor-image games-lobby-corner-decor-right"
          data-testid="games-lobby-corner-decor-right"
          src={ravenCandleRightSrc}
        />
      </div>
      <header className="games-lobby-header" data-testid="games-lobby-header">
        <div
          aria-label="狼人杀竞技场"
          className="games-lobby-brand"
          role="img"
        >
          <img
            alt=""
            aria-hidden="true"
            className="games-lobby-brand-banner"
            data-testid="games-lobby-brand-banner"
            src={brandBannerSrc}
          />
        </div>
        <nav aria-label="大厅操作" className="games-lobby-actions">
          <ArenaNavButton intent="primary" onClick={onCreateGameClick}>
            创建对局
          </ArenaNavButton>
          <ArenaNavButton to="/players">玩家图鉴</ArenaNavButton>
          <ArenaNavButton to="/games/history">对局记录</ArenaNavButton>
        </nav>
      </header>
      {playerProfilesQuery.isPending ? (
        <p
          className="mb-3 rounded-md border border-amber-300/25 bg-slate-950/35 px-3 py-2 text-sm text-amber-100"
          role="status"
        >
          正在读取虚拟玩家资料，席位选择加载完成后可用。
        </p>
      ) : null}
      {playerProfilesQuery.isError ? (
        <p
          aria-label={profileLoadError}
          className="mb-3 rounded-md border border-red-300/30 bg-red-950/35 px-3 py-2 text-sm text-red-100"
          role="alert"
        >
          {profileLoadError}
        </p>
      ) : null}
      <div ref={createFormRef}>
        <CreateGameRunForm
          isProfileListLoaded={playerProfilesQuery.isSuccess}
          profiles={profiles}
        />
      </div>
    </main>
  );
}
