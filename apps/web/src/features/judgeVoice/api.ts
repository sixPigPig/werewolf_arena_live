import { apiFetch } from "../../api/client";

export type JudgeVoiceAsset = {
  id: string;
  text: string;
  category: string;
  filename: string;
  public_url: string;
  exists: boolean;
  byte_size: number | null;
  template_id: string | null;
  template_text: string | null;
  seat_number: number | null;
};

export type JudgeVoiceLineListResponse = {
  audio_format: string;
  sample_rate: number;
  lines: JudgeVoiceAsset[];
};

export type GenerateJudgeVoiceLinesRequest = {
  force: boolean;
  line_ids?: string[];
};

export type GenerateJudgeVoiceLinesResponse = JudgeVoiceLineListResponse & {
  generated_ids: string[];
  skipped_ids: string[];
  manifest_path: string;
};

export function listJudgeVoiceLines(): Promise<JudgeVoiceLineListResponse> {
  return apiFetch<JudgeVoiceLineListResponse>("/api/v1/judge-voice-lines");
}

export function generateJudgeVoiceLines(
  request: GenerateJudgeVoiceLinesRequest,
): Promise<GenerateJudgeVoiceLinesResponse> {
  return apiFetch<GenerateJudgeVoiceLinesResponse>(
    "/api/v1/judge-voice-lines/generate",
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
  );
}
