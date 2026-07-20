import type { LivenessRolloutConfig } from "@/features/liveness-rollout/types";

export const previewLivenessRollout: LivenessRolloutConfig = {
  revision: 4,
  experience_revision: "liveness-v1",
  experiment_id: "lifelike-preview-v1",
  treatment_percent: 25,
  control_percent: 75,
  source: "database",
  effective_scope: "new_sessions_only",
  updated_at: "2026-07-20T08:00:00Z",
  available_experiences: [
    {
      revision: "liveness-v1",
      label: "活人感体验 V1",
      description: "角色心智、分句流式语音、情绪表达和可打断播报的第一版组合。",
      control_summary: "保留异步质量观察与影子心智，不启用分句语音、情绪投递和打断。",
      treatment_summary: "启用角色心智读取、分句语音、情绪投递、预取和确定性打断。",
    },
  ],
};
