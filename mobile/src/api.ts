import Constants from "expo-constants";
import type {
  ListKind,
  LoadTitleResponse,
  MediaMode,
  TitleSelection,
  WordItem,
  WordList,
} from "./types";

const configuredUrl =
  (Constants.expoConfig?.extra?.apiBaseUrl as string | undefined) ||
  "http://localhost:8000";

export const API_BASE_URL = configuredUrl.replace(/\/$/, "");
export const MOBILE_USER_ID = "ios-local-user";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: string };
      message = body.detail || message;
    } catch {
      // Keep the generic HTTP message.
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

export async function loadTitle(params: {
  query: string;
  mode: MediaMode;
  selection?: TitleSelection;
}): Promise<LoadTitleResponse> {
  return request<LoadTitleResponse>(
    `/api/titles/load?user_id=${encodeURIComponent(MOBILE_USER_ID)}`,
    {
      method: "POST",
      body: JSON.stringify(params),
    },
  );
}

export async function loadList(
  titleId: string,
  kind: ListKind,
  limit = 120,
): Promise<WordList> {
  return request<WordList>(
    `/api/titles/${encodeURIComponent(titleId)}/lists/${kind}?user_id=${encodeURIComponent(
      MOBILE_USER_ID,
    )}&limit=${limit}`,
  );
}

export async function toggleDictionary(params: {
  item: WordItem;
  sourceTitle: string;
  sourceId: string;
}): Promise<{ saved: boolean; count: number }> {
  return request<{ saved: boolean; count: number }>(`/api/dictionary/toggle`, {
    method: "POST",
    body: JSON.stringify({
      user_id: MOBILE_USER_ID,
      word: params.item.word,
      translation: params.item.translation,
      example: params.item.example,
      source_title: params.sourceTitle,
      source_id: params.sourceId,
    }),
  });
}

export async function loadDictionary(): Promise<WordItem[]> {
  const body = await request<{ items: WordItem[] }>(
    `/api/dictionary?user_id=${encodeURIComponent(MOBILE_USER_ID)}`,
  );
  return body.items;
}
