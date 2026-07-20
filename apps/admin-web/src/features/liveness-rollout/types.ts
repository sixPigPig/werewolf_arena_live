export type LivenessExperienceOption = {
  revision: string;
  label: string;
  description: string;
  control_summary: string;
  treatment_summary: string;
};

export type LivenessRolloutConfig = {
  revision: number;
  experience_revision: string;
  experiment_id: string;
  treatment_percent: number;
  control_percent: number;
  source: "database" | "environment_fallback";
  effective_scope: "new_sessions_only";
  updated_at: string | null;
  available_experiences: LivenessExperienceOption[];
};

export type LivenessRolloutUpdate = {
  expected_revision: number;
  experience_revision: string;
  experiment_id: string;
  treatment_percent: number;
  change_reason: string;
};
