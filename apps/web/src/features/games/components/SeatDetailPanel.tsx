import { Button, TextField } from "../../../components/ui";

import { personalityLabel } from "../playerProfileOptions";
import type { PlayerConfig, VirtualPlayerProfile } from "../types";

type SeatDetailPanelProps = {
  selectedConfig?: PlayerConfig;
  selectedProfile?: VirtualPlayerProfile;
  selectedSeat: number;
  onClearAllSeats: () => void;
  onClearSeat: () => void;
  onFillFavorites: () => void;
  onModelChange: (model: string) => void;
  onRandomFill: () => void;
};

export function SeatDetailPanel({
  selectedConfig,
  selectedProfile,
  selectedSeat,
  onClearAllSeats,
  onClearSeat,
  onFillFavorites,
  onModelChange,
  onRandomFill,
}: SeatDetailPanelProps) {
  return (
    <div className="seat-detail-panel">
      <div className="seat-detail-header">
        <div>
          <h3 className="player-config-role-title">当前席位</h3>
          <span className="player-config-role-seat">{selectedSeat} 号座位</span>
        </div>
        <div className="seat-detail-actions">
          <Button onClick={onClearSeat} size="1" skin="gothic" type="button">
            清空当前座位
          </Button>
          <Button onClick={onClearAllSeats} size="1" skin="gothic" type="button">
            清空全部座位
          </Button>
        </div>
      </div>
      <div className="seat-detail-card">
        {selectedProfile ? (
          <>
            <span className="seat-detail-name">{selectedProfile.display_name}</span>
            <span className="seat-detail-meta">
              {selectedConfig?.model?.trim() || selectedProfile.model} ·{" "}
              {personalityLabel(selectedProfile.personality_id)}
            </span>
            {selectedProfile.short_description ? (
              <p className="seat-detail-copy">{selectedProfile.short_description}</p>
            ) : null}
          </>
        ) : (
          <>
            <span className="seat-detail-name">空席</span>
            <span className="seat-detail-meta">开局时由系统随机补齐</span>
          </>
        )}
      </div>
      <div className="player-config-role-controls">
        <label className="player-config-seat-model-field">
          <span>{selectedSeat} 号座位模型覆盖</span>
          <TextField.Root
            aria-label={`${selectedSeat} 号座位模型覆盖`}
            className="player-config-model"
            placeholder={selectedProfile?.model || "按身份默认"}
            value={selectedConfig?.model ?? ""}
            onChange={(event) => onModelChange(event.target.value)}
          />
        </label>
        <div className="player-config-role-actions">
          <Button onClick={onRandomFill} size="1" skin="gothic" type="button">
            随机填充空席
          </Button>
          <Button onClick={onFillFavorites} size="1" skin="gothic" type="button">
            只用收藏填充
          </Button>
        </div>
      </div>
    </div>
  );
}
