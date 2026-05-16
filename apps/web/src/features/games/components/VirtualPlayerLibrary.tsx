import { Button, Container } from "../../../components/ui";
import {
  appearanceClassName,
  personalityLabel,
} from "../playerProfileOptions";
import type { VirtualPlayerProfile } from "../types";

type VirtualPlayerLibraryProps = {
  profiles: VirtualPlayerProfile[];
  isLoading: boolean;
  isError: boolean;
};

export function VirtualPlayerLibrary({
  profiles,
  isLoading,
  isError,
}: VirtualPlayerLibraryProps) {
  return (
    <Container
      aria-labelledby="virtual-player-library-title"
      as="section"
      className="virtual-player-library"
      contentClassName="virtual-player-library-content"
      data-testid="virtual-player-library"
      size="1"
    >
      <div className="virtual-player-library-header">
        <h2
          className="virtual-player-library-title"
          id="virtual-player-library-title"
        >
          虚拟玩家库
        </h2>
        <Button
          className="virtual-player-library-action"
          intent="primary"
          size="1"
          skin="gothic"
          type="button"
        >
          新建虚拟玩家
        </Button>
      </div>

      {isLoading ? (
        <p className="virtual-player-library-status">正在读取虚拟玩家...</p>
      ) : null}
      {isError ? (
        <p className="virtual-player-library-error">无法读取虚拟玩家库</p>
      ) : null}
      {!isLoading && !isError && profiles.length === 0 ? (
        <p className="virtual-player-library-empty">还没有保存的虚拟玩家。</p>
      ) : null}
      {profiles.length > 0 ? (
        <ul
          aria-label="虚拟玩家列表"
          className="virtual-player-library-grid"
        >
          {profiles.map((profile) => (
            <li className="virtual-player-card" key={profile.id}>
              <span
                aria-hidden="true"
                className={[
                  "virtual-player-card-avatar",
                  appearanceClassName(profile.appearance_id),
                ].join(" ")}
              >
                {profile.display_name.trim().charAt(0) || "?"}
              </span>
              <div className="virtual-player-card-main">
                <div className="virtual-player-card-heading">
                  <span className="virtual-player-card-name">
                    {profile.display_name}
                  </span>
                  <span className="virtual-player-card-personality">
                    {personalityLabel(profile.personality_id)}
                  </span>
                </div>
                <span className="virtual-player-card-model">
                  {profile.model}
                </span>
                {profile.tags.length > 0 ? (
                  <div className="virtual-player-card-tags">
                    {profile.tags.slice(0, 2).map((tag) => (
                      <span className="virtual-player-card-tag" key={tag}>
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </Container>
  );
}
