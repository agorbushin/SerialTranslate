# SerialTranslate iOS App

This is the mobile front end for the existing SerialTranslate pipeline. The app
talks to `mobile_api.py`, which reuses the Telegram bot's backend logic for:

- TV series and movie title resolution
- subtitle lookup/download
- hard-word tier generation
- frequent C/B and rare C/B translations
- phrasal verbs and idioms
- personal dictionary save/remove

## Run the backend

From the repository root:

```bash
python3 -m uvicorn mobile_api:app --reload --host 0.0.0.0 --port 8000
```

The backend still needs the same environment as the Telegram bot, including
OpenAI/OpenSubtitles/TMDB keys where those features are used.

## Run the iOS app

From this `mobile/` directory:

```bash
npm install
npm run ios
```

The default API URL is `http://localhost:8000`, which works for the iOS
simulator. For a physical iPhone, set `expo.extra.apiBaseUrl` in `app.json` to
your Mac's LAN URL, for example `http://192.168.1.20:8000`.

## Product flow

1. Enter a show episode or movie, e.g. `Fallout S2E2` or `The Matrix 1999`.
2. Confirm the title if the backend returns multiple likely matches.
3. Review tabs: Frequent C, Frequent B, Rare C, Rare B, Phrasal, Idioms.
4. Save words from vocabulary lists into My dictionary.

Rare lists, phrasal verbs, and idioms are generated on demand, matching the
Telegram button behavior.
