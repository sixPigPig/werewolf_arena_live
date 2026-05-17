import { appearanceClassName, personalityLabel } from "../playerProfileOptions";
import type { PlayerConfig, VirtualPlayerProfile } from "../types";

type SeatGridProps = {
  configs: PlayerConfig[];
  playerCount: number;
  profiles: VirtualPlayerProfile[];
  selectedSeat: number;
  onSelectSeat: (seat: number) => void;
};

export function SeatGrid({
  configs,
  playerCount,
  profiles,
  selectedSeat,
  onSelectSeat,
}: SeatGridProps) {
  const seats = Array.from({ length: playerCount }, (_, index) => index + 1);

  return (
    <div className="player-config-seat-module">
      {seats.map((seat) => {
        const config = configs.find((item) => item.seat === seat);
        const profile = profiles.find((item) => item.id === config?.profile_id);
        const isSelected = selectedSeat === seat;
        const isInvalid = Boolean(config?.profile_id && !profile);

        return (
          <button
            aria-label={`${seat}号${profile ? profile.display_name : "空席"}`}
            className={[
              "player-config-seat-card",
              isSelected ? "player-config-seat-card-selected" : "",
              profile ? "player-config-seat-card-filled" : "",
              isInvalid ? "player-config-seat-card-invalid" : "",
            ].join(" ")}
            key={seat}
            onClick={() => onSelectSeat(seat)}
            type="button"
          >
            <span
              className={[
                "player-config-seat-frame",
                profile?.avatar_image_url
                  ? ""
                  : appearanceClassName(profile?.appearance_id),
              ].join(" ")}
            >
              {profile?.avatar_image_url ? (
                <img alt="" aria-hidden="true" src={profile.avatar_image_url} />
              ) : (
                <span aria-hidden="true" className="player-config-seat-placeholder" />
              )}
            </span>
            <span className="player-config-seat-name">
              {seat}号{profile ? profile.display_name : "空席"}
            </span>
            {profile ? (
              <span className="player-config-seat-meta">
                {config?.model?.trim() || profile.model} ·{" "}
                {personalityLabel(profile.personality_id)}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
