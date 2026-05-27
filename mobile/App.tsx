import { StatusBar } from "expo-status-bar";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import {
  API_BASE_URL,
  loadDictionary,
  loadList,
  loadTitle,
  toggleDictionary,
} from "./src/api";
import type {
  ListKind,
  MediaMode,
  ResolvedTitle,
  TitleSelection,
  TitleSummary,
  WordItem,
  WordList,
} from "./src/types";

const tabs: Array<{ kind: ListKind; label: string }> = [
  { kind: "frequent_c", label: "Frequent C" },
  { kind: "frequent_b", label: "Frequent B" },
  { kind: "rare_c", label: "Rare C" },
  { kind: "rare_b", label: "Rare B" },
  { kind: "phrasal", label: "Phrasal" },
  { kind: "idioms", label: "Idioms" },
];

const modeOptions: Array<{ mode: MediaMode; label: string }> = [
  { mode: "auto", label: "Auto" },
  { mode: "series", label: "Series" },
  { mode: "movie", label: "Movie" },
];

function selectionFromResolved(item: ResolvedTitle): TitleSelection {
  return {
    media_type: item.media_type,
    canonical_title: item.canonical_title,
    season: item.season || 1,
    episode: item.episode || 1,
    year: item.year || 0,
    imdb_id: item.imdb_id || null,
  };
}

function titleLine(item: ResolvedTitle): string {
  if (item.media_type === "movie") {
    return `${item.canonical_title}${item.year ? ` (${item.year})` : ""}`;
  }
  return `${item.canonical_title} S${item.season || 1} E${item.episode || 1}`;
}

export default function App() {
  const [query, setQuery] = useState("Game of Thrones s2 e2");
  const [mode, setMode] = useState<MediaMode>("auto");
  const [title, setTitle] = useState<TitleSummary | null>(null);
  const [activeKind, setActiveKind] = useState<ListKind>("frequent_c");
  const [lists, setLists] = useState<Record<string, WordList>>({});
  const [dictionary, setDictionary] = useState<WordItem[]>([]);
  const [confirmation, setConfirmation] = useState<{
    resolved?: ResolvedTitle;
    alternatives: ResolvedTitle[];
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [error, setError] = useState("");

  const activeList = useMemo(() => lists[activeKind], [activeKind, lists]);

  async function refreshDictionary() {
    const rows = await loadDictionary();
    setDictionary(rows);
  }

  async function runLoad(selection?: TitleSelection) {
    if (!query.trim() && !selection) {
      setError("Enter a series, episode, or movie first.");
      return;
    }
    setLoading(true);
    setError("");
    setConfirmation(null);
    try {
      const result = await loadTitle({ query, mode, selection });
      if (result.status === "needs_confirmation") {
        setConfirmation({
          resolved: result.resolved,
          alternatives: result.alternatives || [],
        });
        return;
      }
      setTitle(result.title);
      setLists(result.title.lists || {});
      setActiveKind("frequent_c");
      await refreshDictionary();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function openTab(kind: ListKind) {
    setActiveKind(kind);
    if (!title || lists[kind]) {
      return;
    }
    setListLoading(true);
    setError("");
    try {
      const list = await loadList(title.id, kind);
      setLists((current) => ({ ...current, [kind]: list }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this list.");
    } finally {
      setListLoading(false);
    }
  }

  async function toggle(item: WordItem) {
    if (!title) {
      return;
    }
    const response = await toggleDictionary({
      item,
      sourceTitle: title.title,
      sourceId: title.id,
    });
    setLists((current) => {
      const next = { ...current };
      Object.keys(next).forEach((key) => {
        next[key] = {
          ...next[key],
          items: next[key].items.map((row) =>
            row.word === item.word && row.translation === item.translation
              ? { ...row, saved: response.saved }
              : row,
          ),
        };
      });
      return next;
    });
    await refreshDictionary();
  }

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="dark" />
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.header}>
          <Text style={styles.appName}>SerialTranslate</Text>
          <Text style={styles.caption}>Episode vocabulary, examples, idioms, and saved words.</Text>
        </View>

        <View style={styles.searchPanel}>
          <View style={styles.modeRow}>
            {modeOptions.map((option) => (
              <Pressable
                key={option.mode}
                onPress={() => setMode(option.mode)}
                style={[styles.modeButton, mode === option.mode && styles.modeButtonActive]}
              >
                <Text style={[styles.modeText, mode === option.mode && styles.modeTextActive]}>
                  {option.label}
                </Text>
              </Pressable>
            ))}
          </View>

          <TextInput
            value={query}
            onChangeText={setQuery}
            placeholder="Fallout S2E2 or The Matrix 1999"
            autoCapitalize="words"
            autoCorrect={false}
            returnKeyType="search"
            onSubmitEditing={() => runLoad()}
            style={styles.input}
          />

          <Pressable disabled={loading} onPress={() => runLoad()} style={styles.primaryButton}>
            {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryText}>Build list</Text>}
          </Pressable>

          <Text style={styles.apiHint}>Backend: {API_BASE_URL}</Text>
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        {confirmation ? (
          <View style={styles.confirmPanel}>
            <Text style={styles.sectionTitle}>Confirm title</Text>
            {confirmation.resolved ? (
              <Pressable
                style={styles.choice}
                onPress={() => runLoad(selectionFromResolved(confirmation.resolved as ResolvedTitle))}
              >
                <Text style={styles.choiceTitle}>{titleLine(confirmation.resolved)}</Text>
                <Text style={styles.choiceMeta}>Use suggested match</Text>
              </Pressable>
            ) : null}
            {confirmation.alternatives.map((item) => (
              <Pressable
                key={`${item.media_type}-${item.canonical_title}-${item.year}-${item.season}-${item.episode}`}
                style={styles.choice}
                onPress={() => runLoad(selectionFromResolved(item))}
              >
                <Text style={styles.choiceTitle}>{titleLine(item)}</Text>
                <Text style={styles.choiceMeta}>Alternative match</Text>
              </Pressable>
            ))}
          </View>
        ) : null}

        {title ? (
          <View style={styles.titlePanel}>
            <Text style={styles.kicker}>{title.media_type === "movie" ? "Movie" : "Series episode"}</Text>
            <Text style={styles.title}>{title.title}</Text>
            {title.subtitle ? <Text style={styles.subtitle}>{title.subtitle}</Text> : null}
            <Text style={styles.caption}>Saved in {title.translations_dir}</Text>
          </View>
        ) : null}

        {title ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tabs}>
            {tabs.map((tab) => (
              <Pressable
                key={tab.kind}
                onPress={() => openTab(tab.kind)}
                style={[styles.tab, activeKind === tab.kind && styles.tabActive]}
              >
                <Text style={[styles.tabText, activeKind === tab.kind && styles.tabTextActive]}>
                  {tab.label}
                </Text>
              </Pressable>
            ))}
          </ScrollView>
        ) : null}

        {listLoading ? <ActivityIndicator color="#195c4a" style={styles.loader} /> : null}

        {activeList ? (
          <View style={styles.listPanel}>
            <View style={styles.listHeader}>
              <Text style={styles.sectionTitle}>{tabs.find((t) => t.kind === activeKind)?.label}</Text>
              <Text style={styles.count}>{activeList.total} items</Text>
            </View>
            {activeList.items.map((item, index) => (
              <View key={`${item.word}-${index}`} style={styles.wordCard}>
                <View style={styles.wordTop}>
                  <View style={styles.wordTextWrap}>
                    <Text style={styles.word}>{item.word}</Text>
                    <Text style={styles.translation}>{item.translation || "No translation yet"}</Text>
                  </View>
                  {activeKind === "phrasal" || activeKind === "idioms" ? null : (
                    <Pressable onPress={() => toggle(item)} style={[styles.saveButton, item.saved && styles.savedButton]}>
                      <Text style={[styles.saveText, item.saved && styles.savedText]}>
                        {item.saved ? "Saved" : "Save"}
                      </Text>
                    </Pressable>
                  )}
                </View>
                {item.example ? <Text style={styles.example}>{item.example}</Text> : null}
                {item.frequency || item.score ? (
                  <Text style={styles.meta}>
                    {[item.frequency ? `freq ${item.frequency}` : "", item.score ? `score ${item.score}` : ""]
                      .filter(Boolean)
                      .join(" | ")}
                  </Text>
                ) : null}
              </View>
            ))}
            {activeList.truncated ? <Text style={styles.caption}>Showing a preview. Increase the API limit to load more.</Text> : null}
          </View>
        ) : null}

        <View style={styles.dictionaryPanel}>
          <View style={styles.listHeader}>
            <Text style={styles.sectionTitle}>My dictionary</Text>
            <Pressable onPress={refreshDictionary} style={styles.secondaryButton}>
              <Text style={styles.secondaryText}>Refresh</Text>
            </Pressable>
          </View>
          {dictionary.length === 0 ? (
            <Text style={styles.caption}>Saved words will appear here.</Text>
          ) : (
            dictionary.map((item, index) => (
              <View key={`${item.word}-${index}`} style={styles.dictionaryRow}>
                <Text style={styles.dictionaryWord}>{item.word}</Text>
                <Text style={styles.dictionaryTranslation}>{item.translation}</Text>
              </View>
            ))
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: "#f6f2eb",
  },
  content: {
    padding: 18,
    paddingBottom: 44,
  },
  header: {
    marginBottom: 16,
  },
  appName: {
    fontSize: 34,
    fontWeight: "800",
    color: "#16211f",
  },
  caption: {
    color: "#6c716f",
    fontSize: 14,
    lineHeight: 20,
  },
  searchPanel: {
    backgroundColor: "#ffffff",
    borderRadius: 8,
    padding: 14,
    borderWidth: 1,
    borderColor: "#e7dfd2",
    gap: 12,
  },
  modeRow: {
    flexDirection: "row",
    gap: 8,
  },
  modeButton: {
    flex: 1,
    paddingVertical: 9,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#d9d2c8",
    alignItems: "center",
  },
  modeButtonActive: {
    backgroundColor: "#195c4a",
    borderColor: "#195c4a",
  },
  modeText: {
    color: "#55615e",
    fontWeight: "700",
  },
  modeTextActive: {
    color: "#ffffff",
  },
  input: {
    borderWidth: 1,
    borderColor: "#d9d2c8",
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 12,
    fontSize: 16,
    color: "#18221f",
    backgroundColor: "#fffdf9",
  },
  primaryButton: {
    minHeight: 48,
    borderRadius: 8,
    backgroundColor: "#195c4a",
    alignItems: "center",
    justifyContent: "center",
  },
  primaryText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "800",
  },
  apiHint: {
    color: "#8a8174",
    fontSize: 12,
  },
  error: {
    marginTop: 12,
    color: "#a33a2c",
    fontWeight: "700",
  },
  confirmPanel: {
    marginTop: 16,
    gap: 10,
  },
  choice: {
    backgroundColor: "#fff",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#e0d7ca",
    padding: 13,
  },
  choiceTitle: {
    fontWeight: "800",
    color: "#17211f",
    fontSize: 16,
  },
  choiceMeta: {
    color: "#6c716f",
    marginTop: 4,
  },
  titlePanel: {
    marginTop: 18,
    backgroundColor: "#173b34",
    borderRadius: 8,
    padding: 16,
  },
  kicker: {
    color: "#b8d9cc",
    fontWeight: "800",
    textTransform: "uppercase",
    fontSize: 12,
  },
  title: {
    color: "#ffffff",
    fontSize: 28,
    fontWeight: "800",
    marginTop: 4,
  },
  subtitle: {
    color: "#e6f1ed",
    fontWeight: "700",
    marginTop: 4,
  },
  tabs: {
    gap: 8,
    paddingVertical: 16,
  },
  tab: {
    paddingHorizontal: 13,
    paddingVertical: 10,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#d7d0c5",
    backgroundColor: "#fffdf9",
  },
  tabActive: {
    backgroundColor: "#d96f3d",
    borderColor: "#d96f3d",
  },
  tabText: {
    color: "#39413f",
    fontWeight: "800",
  },
  tabTextActive: {
    color: "#ffffff",
  },
  loader: {
    marginVertical: 20,
  },
  listPanel: {
    gap: 10,
  },
  listHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  sectionTitle: {
    color: "#17211f",
    fontSize: 20,
    fontWeight: "800",
  },
  count: {
    color: "#6c716f",
    fontWeight: "700",
  },
  wordCard: {
    backgroundColor: "#ffffff",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#e5ddcf",
    padding: 14,
  },
  wordTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 12,
  },
  wordTextWrap: {
    flex: 1,
  },
  word: {
    color: "#16211f",
    fontSize: 19,
    fontWeight: "800",
  },
  translation: {
    color: "#35403d",
    fontSize: 16,
    marginTop: 3,
  },
  saveButton: {
    alignSelf: "flex-start",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#195c4a",
    paddingHorizontal: 11,
    paddingVertical: 8,
  },
  savedButton: {
    backgroundColor: "#195c4a",
  },
  saveText: {
    color: "#195c4a",
    fontWeight: "800",
  },
  savedText: {
    color: "#ffffff",
  },
  example: {
    color: "#69716e",
    fontStyle: "italic",
    marginTop: 10,
    lineHeight: 20,
  },
  meta: {
    color: "#8a8174",
    fontSize: 12,
    marginTop: 8,
  },
  dictionaryPanel: {
    marginTop: 22,
    backgroundColor: "#ffffff",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#e5ddcf",
    padding: 14,
    gap: 10,
  },
  secondaryButton: {
    paddingHorizontal: 11,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#d7d0c5",
  },
  secondaryText: {
    color: "#35403d",
    fontWeight: "800",
  },
  dictionaryRow: {
    borderTopWidth: 1,
    borderTopColor: "#eee6da",
    paddingTop: 10,
  },
  dictionaryWord: {
    fontWeight: "800",
    color: "#17211f",
  },
  dictionaryTranslation: {
    color: "#4b5451",
    marginTop: 2,
  },
});
