export type MediaMode = "auto" | "series" | "movie";

export type ListKind =
  | "frequent_c"
  | "frequent_b"
  | "rare_c"
  | "rare_b"
  | "phrasal"
  | "idioms";

export type WordItem = {
  word: string;
  translation: string;
  example: string;
  saved: boolean;
  frequency?: string;
  score?: string;
};

export type WordList = {
  id: string;
  kind: ListKind;
  title: string;
  subtitle: string;
  total: number;
  items: WordItem[];
  truncated: boolean;
};

export type TitleSelection = {
  media_type: "tv" | "movie";
  canonical_title: string;
  season?: number;
  episode?: number;
  year?: number;
  imdb_id?: string | null;
};

export type ResolvedTitle = {
  media_type: "tv" | "movie";
  canonical_title: string;
  season: number;
  episode: number;
  year: number;
  imdb_id?: string | null;
  confidence: "high" | "low";
  issue?: string | null;
  reason?: string;
};

export type TitleSummary = {
  id: string;
  media_type: "tv" | "movie";
  title: string;
  subtitle: string;
  translations_dir: string;
  available_lists: ListKind[];
  lists: Record<string, WordList>;
};

export type LoadTitleResponse =
  | {
      status: "ready";
      title: TitleSummary;
      resolved?: ResolvedTitle;
      alternatives?: ResolvedTitle[];
    }
  | {
      status: "needs_confirmation";
      resolved?: ResolvedTitle;
      alternatives: ResolvedTitle[];
      title?: null;
    };
