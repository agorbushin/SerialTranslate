# Data folders and Git

This project has folders that hold data (subtitles, tier lists, translations). You can choose what to put in Git.

## Folders

| Folder | What it is | Recommendation |
|--------|------------|----------------|
| **Subtitle/** | Input .srt files (downloaded or manual) | **Don’t put in Git** — can get large; re-download or copy from elsewhere. Already in `.gitignore`. |
| **Tier_lists/** | Generated CSV/JSON per episode (tiers, episode_info) | **Put in Git** if you want the repo to be runnable with sample data; otherwise add `Tier_lists/` to `.gitignore`. |
| **translations/** | Output of translation pipeline | **Usually don’t put in Git** — regeneratable. Already in `.gitignore`. |
| **Archieve/** | Old archive (code + subtitles) | **Don’t put in Git** — legacy. Already in `.gitignore`. |
| **filters/** | Word lists (CSV) used by the pipeline | **Put in Git** — small and required for the code. |

## Options

1. **Code-only (current setup)**  
   Only code, docs, tests, and `filters/` are tracked. `Subtitle/`, `Tier_lists/`, `translations/`, `Archieve/` are ignored. Repo stays small; others clone and add their own data.

2. **Code + sample tier lists**  
   Keep `Tier_lists/` tracked so someone can run the pipeline on a sample episode without fetching data. Remove `Tier_lists/` from `.gitignore` if you want this.

3. **Everything in Git**  
   Remove `Subtitle/`, `translations/`, `Archieve/` from `.gitignore` to track all data. Only do this if total size is small (e.g. &lt; 100 MB) and you need full reproducibility in the repo.

4. **Large files with Git LFS**  
   If you want to track large files (e.g. many .srt or big CSVs), use [Git LFS](https://git-lfs.com/) and add patterns in `.gitattributes` so the repo history stays small.

To change what’s tracked, edit `.gitignore` and then run `git add .` and commit.
