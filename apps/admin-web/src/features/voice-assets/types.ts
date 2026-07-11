export type AdminJudgeVoiceAvailability = "available" | "missing";
export type AdminJudgeVoiceSortField = "category" | "id" | "byte_size";

export type AdminJudgeVoiceLine = {
  id: string;
  text: string;
  category: string;
  available: boolean;
  byte_size: number | null;
  template_id: string | null;
  seat_number: number | null;
  subtitle_cue_count: number;
  audio_url: string | null;
};

export type AdminJudgeVoiceCategory = {
  name: string;
  total: number;
  available: number;
  missing: number;
};

export type AdminJudgeVoiceList = {
  audio_format: string;
  sample_rate: number;
  storage_mode: "database" | "legacy_static_directory";
  coverage: {
    total: number;
    available: number;
    missing: number;
    byte_total: number;
  };
  categories: AdminJudgeVoiceCategory[];
  items: AdminJudgeVoiceLine[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    pages: number;
  };
};

export type AdminJudgeVoiceListParams = {
  page: number;
  page_size: number;
  q?: string;
  category?: string;
  availability?: AdminJudgeVoiceAvailability;
  sort: AdminJudgeVoiceSortField;
  direction: "asc" | "desc";
};
