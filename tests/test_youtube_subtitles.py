import json

from download_subtitles import (
    get_tierlist_youtube_dir,
    get_translations_youtube_dir,
    get_youtube_subtitle_path,
)
from translate_tier_translations import resolve_subtitle_path
from youtube_subtitles import extract_youtube_video_id, is_youtube_url, vtt_to_srt


def test_youtube_url_detection_and_id_extraction():
    assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ?t=42")
    assert is_youtube_url("https://www.youtube.com/shorts/dQw4w9WgXcQ")
    assert not is_youtube_url("https://example.com/watch?v=dQw4w9WgXcQ")
    assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ?t=42") == "dQw4w9WgXcQ"


def test_vtt_to_srt_converts_webvtt_cues():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:03.500 align:start position:0%
<c>Hello</c> &amp; welcome

00:00:04.000 --> 00:00:05.000
Second line
"""
    srt = vtt_to_srt(vtt)

    assert "1\n00:00:01,000 --> 00:00:03,500\nHello & welcome" in srt
    assert "2\n00:00:04,000 --> 00:00:05,000\nSecond line" in srt
    assert "WEBVTT" not in srt


def test_youtube_paths_are_separate_from_movies_and_series(tmp_path):
    subtitle_path = get_youtube_subtitle_path(tmp_path / "Subtitle", "My Video!", "abc123XYZ")
    tier_dir = get_tierlist_youtube_dir(tmp_path / "Tier_lists", "My Video!", "abc123XYZ")
    translations_dir = get_translations_youtube_dir(
        tmp_path / "translations", "My Video!", "abc123XYZ"
    )

    assert subtitle_path == tmp_path / "Subtitle" / "YouTube" / "My Video!" / "my_video_abc123XYZ.srt"
    assert tier_dir == tmp_path / "Tier_lists" / "YouTube" / "My Video!" / "my_video_abc123XYZ"
    assert translations_dir == tmp_path / "translations" / "YouTube" / "My Video!" / "my_video_abc123XYZ"


def test_resolve_subtitle_path_supports_youtube_metadata(tmp_path):
    subtitle_base = tmp_path / "Subtitle"
    subtitle_path = get_youtube_subtitle_path(subtitle_base, "My Video", "abc123XYZ")
    subtitle_path.parent.mkdir(parents=True)
    subtitle_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    episode_dir = tmp_path / "Tier_lists" / "YouTube" / "My Video" / "my_video_abc123XYZ"
    episode_dir.mkdir(parents=True)
    info = {
        "series": "My Video",
        "subtitle_file": subtitle_path.name,
        "season_number": 0,
        "episode_number": 0,
        "is_youtube": True,
        "youtube_id": "abc123XYZ",
    }
    (episode_dir / "episode_info.json").write_text(json.dumps(info), encoding="utf-8")

    assert resolve_subtitle_path(episode_dir, info, subtitle_base, None) == subtitle_path
