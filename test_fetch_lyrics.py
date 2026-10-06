"""Regression coverage for Desktop Lyrics matching, local precedence and deadlines."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("fetch_lyrics.py")
spec = importlib.util.spec_from_file_location("desktop_lyrics_fetch", SCRIPT)
lyrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lyrics)


class LyricsBackendTests(unittest.TestCase):
    def test_provider_aliases_require_exact_identity_and_recording(self):
        record = {"name": "佐藤千亜妃", "alias": ["Chiaki Sato"]}
        self.assertTrue(lyrics.matches_artists([record], "CHIAKI SATO"))
        self.assertFalse(lyrics.matches_artists([record], "Chiaki"))
        self.assertFalse(lyrics.matches_artists([{"name": "佐藤千亜妃"}], "CHIAKI SATO"))
        song = {"name": "ECLOSE", "artists": [record], "duration": 190166}
        self.assertGreaterEqual(lyrics.score_netease_song(song, "CHIAKI SATO", "ECLOSE", 190.166), 0)
        self.assertEqual(-1, lyrics.score_netease_song(song, "CHIAKI SATO", "ECLOSE", 230.893))
        self.assertEqual(-1, lyrics.score_netease_song(song, "CHIAKI SATO", "ECLOSE (Live)", 190.166))
        qq = {"songname": "ECLOSE", "singer": [record], "interval": 190}
        self.assertGreaterEqual(lyrics.score_qq_song(qq, "CHIAKI SATO", "ECLOSE", 190.166), 0)

    def test_empty_exact_candidate_falls_back_to_verified_alias(self):
        empty = {"id": 1, "name": "ECLOSE", "artists": [{"id": 0, "name": "CHIAKI SATO"}], "duration": 190166}
        valid = {"id": 2, "name": "ECLOSE", "artists": [{"id": 123, "name": "佐藤千亜妃"}], "duration": 190166}
        responses = [(200, {"result": {"songs": [empty, valid]}}), (200, {"lrc": {"lyric": ""}}),
                     (200, {"artist": {"id": 123, "name": "佐藤千亜妃", "alias": ["Chiaki Sato"]}}),
                     (200, {"lrc": {"lyric": "[00:26.69]original"}, "tlyric": {"lyric": "[00:26.69]中文翻译"}})]
        with mock.patch.object(lyrics, "http_json", side_effect=responses):
            result = lyrics.fetch_netease("CHIAKI SATO", "ECLOSE", 190.166)
        self.assertEqual("netease:2", result["source"])
        self.assertEqual("中文翻译", result["lines"][0]["translation"])
        self.assertEqual(26.69, result["lines"][0]["start"])

    def test_platform_title_suffix_matches_canonical_recording(self):
        self.assertTrue(lyrics.matches_song("All The Stars", "Kendrick Lamar / SZA", "Kendrick Lamar", 'All The Stars (with SZA) - From "Black Panther: The Album"'))
        self.assertTrue(lyrics.matches_song("All The Stars", "Kendrick Lamar / SZA", "Kendrick Lamar", "All The Stars (Explicit)"))
        self.assertFalse(lyrics.matches_song("All The Stars (Live)", "Kendrick Lamar / SZA", "Kendrick Lamar", 'All The Stars - From "Black Panther: The Album"'))

    def test_wrong_artist_detail_id_cannot_create_alias(self):
        song = {"artists": [{"id": 123, "name": "Different Artist"}]}
        with mock.patch.object(lyrics, "http_json", return_value=(200, {"artist": {"id": 456, "name": "Different Artist", "alias": ["CHIAKI SATO"]}})):
            result = lyrics.resolve_netease_artists(song, "CHIAKI SATO", {})
        self.assertFalse(lyrics.matches_artists(result["artists"], "CHIAKI SATO"))

    def test_alias_lookup_failure_does_not_accept_unverified_artist(self):
        song = {"id": 2, "name": "ECLOSE", "artists": [{"id": 123, "name": "Other Artist"}], "duration": 190166}
        with mock.patch.object(lyrics, "http_json", side_effect=[(200, {"result": {"songs": [song]}}), RuntimeError("offline")]):
            result = lyrics.fetch_netease("CHIAKI SATO", "ECLOSE", 190.166)
        self.assertFalse(result["ok"])

    def test_simplified_display_preserves_original_and_timing(self):
        original = {"ok": True, "lines": [{"start": 1, "end": 3, "text": "讓愛繼續，頭髮隨風飛揚", "translation": "這場夢很溫柔"}, {"start": 3, "end": None, "text": "", "translation": ""}]}
        result = lyrics.display_payload(original)
        self.assertEqual("让爱继续，头发随风飞扬", result["lines"][0]["displayText"])
        self.assertEqual("这场梦很温柔", result["lines"][0]["displayTranslation"])
        self.assertEqual("讓愛繼續，頭髮隨風飛揚", original["lines"][0]["text"])
        self.assertNotIn("displayText", original["lines"][0])
        self.assertEqual((1, 3), (result["lines"][0]["start"], result["lines"][0]["end"]))
        self.assertEqual("", result["lines"][1]["displayText"])

    def test_foreign_original_preserved_with_simplified_translation(self):
        original = {"ok": True, "lines": [{"text": "愛してる", "translation": "我會愛著你"}, {"text": "世界", "translation": "溫柔的世界"}]}
        result = lyrics.display_payload(original)
        self.assertEqual("愛してる", result["lines"][0]["displayText"])
        self.assertEqual("世界", result["lines"][1]["displayText"])
        self.assertEqual("我会爱着你", result["lines"][0]["displayTranslation"])

    def test_traditional_metadata_selects_full_recording_not_preview(self):
        artist, title, duration = "康士坦的變化球", "擱淺的人", 271.855
        full = {"songname": "搁浅的人", "singer": [{"name": "康士坦的变化球"}], "interval": 271}
        preview = {"songname": title, "singer": [{"name": artist}], "interval": 60}
        self.assertGreaterEqual(lyrics.score_qq_song(full, artist, title, duration), 0)
        self.assertEqual(-1, lyrics.score_qq_song(preview, artist, title, duration))
        self.assertEqual(-1, lyrics.score_netease_song({"name": title, "artists": [{"name": artist}], "duration": 60000}, artist, title, duration))
        self.assertEqual(-1, lyrics.score_result({"trackName": title, "artistName": artist, "duration": 60}, artist, title, "", duration))
        self.assertFalse(lyrics.matches_song("搁浅的人 (Live)", "康士坦的变化球", artist, title))

    def test_lrclib_direct_preview_is_rejected_for_full_recording(self):
        preview = {"trackName": "Song", "artistName": "Artist", "duration": 60, "syncedLyrics": "[00:00.17]preview"}
        full = {"trackName": "Song", "artistName": "Artist", "duration": 271.855, "syncedLyrics": "[00:27.52]full"}
        with mock.patch.object(lyrics, "http_json", side_effect=[(200, preview), (200, [preview, full])]):
            result = lyrics.fetch_lrclib("Artist", "Song", "Album", 271.855)
        self.assertEqual("full", result["lines"][0]["text"])
        self.assertEqual(27.52, result["lines"][0]["start"])

    def test_wrong_title_or_artist_cannot_win_on_duration(self):
        self.assertFalse(lyrics.matches_song("Wrong Song", "Odoloop", "Odoloop", "Lefty Hand Cream"))
        self.assertFalse(lyrics.matches_song("Lefty Hand Cream", "Elsewhere", "Odoloop", "Lefty Hand Cream"))
        self.assertTrue(lyrics.matches_song("LEFTY - HAND CREAM", "Odoloop", "Odoloop", "Lefty Hand Cream"))
        self.assertEqual(-1, lyrics.score_netease_song({"name": "Wrong Song", "artists": [{"name": "Odoloop"}], "duration": 246346}, "Odoloop", "Lefty Hand Cream", 246.346))
        self.assertEqual(-1, lyrics.score_qq_song({"songname": "Wrong Song", "singer": [{"name": "Odoloop"}], "interval": 246}, "Odoloop", "Lefty Hand Cream", 246.346))
        self.assertEqual(-1, lyrics.score_result({"trackName": "Wrong Song", "artistName": "Odoloop", "duration": 246.346, "syncedLyrics": "[00:01.00]wrong"}, "Odoloop", "Lefty Hand Cream", "", 246.346))

    def test_lrclib_direct_mismatch_uses_valid_search_result(self):
        wrong = {"trackName": "Other Song", "artistName": "Odoloop", "duration": 246.346, "syncedLyrics": "[00:01.00]wrong"}
        right = {"trackName": "Lefty Hand Cream", "artistName": "Odoloop", "duration": 246.346, "syncedLyrics": "[00:02.00]right"}
        with mock.patch.object(lyrics, "http_json", side_effect=[(200, wrong), (200, [wrong, right])]) as http:
            result = lyrics.fetch_lrclib("Odoloop", "Lefty Hand Cream", "", 246.346)
        self.assertEqual("lrclib-search", result["source"])
        self.assertEqual("right", result["lines"][0]["text"])
        self.assertEqual(2, http.call_count)

    def test_lrc_offsets_multiple_times_blank_intervals_and_bilingual(self):
        parsed = lyrics.parse_lrc("[00:01.00][00:02.00]hello\n[00:02.00]hola\n[00:03.00]\n[offset:+500]\n[00:04.00]bye")
        self.assertEqual([0.5, 1.5, 2.5, 3.5], [row["start"] for row in parsed])
        self.assertEqual("hola", parsed[1]["translation"])
        self.assertEqual("", parsed[2]["text"])
        self.assertEqual(2.5, parsed[1]["end"])

    def test_plain_text_retains_newlines_and_does_not_invent_translation(self):
        result = lyrics.from_lrclib_item({"plainLyrics": "first\n\nsecond\n"}, "lrclib")
        self.assertEqual("first\n\nsecond\n", result["plain"])
        self.assertFalse(result["hasTranslation"])
        translated = lyrics.apply_translations({"lines": [{"start": 1, "text": "original", "translation": ""}], "synced": True}, [{"start": 1, "text": "original"}], "provider")
        self.assertFalse(translated["hasTranslation"])

    def test_local_file_precedes_cache_and_network_without_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Lefty Hand Cream.txt").write_text("first\n\nsecond\n", encoding="utf-8")
            with mock.patch.object(lyrics, "CACHE_DIR", root / "cache"), mock.patch.object(lyrics, "fetch_online", side_effect=AssertionError("network must not run")), mock.patch.object(lyrics, "emit") as emit:
                lyrics.save_cache("Odoloop", "Lefty Hand Cream", "", 246.346, {"ok": True, "source": "stale", "synced": True, "instrumental": False, "lines": [{"start": 1, "end": None, "text": "wrong"}]})
                with mock.patch.object(sys, "argv", [str(SCRIPT), json.dumps({"artist": "Odoloop", "title": "Lefty Hand Cream", "duration": 246.346, "localDir": directory})]):
                    lyrics.main()
            result = emit.call_args.args[0]
            self.assertEqual("local", result["source"])
            self.assertEqual("first\n\nsecond\n", result["plain"])
            self.assertFalse(result["synced"])
            self.assertFalse(result["fromCache"])

    def test_cache_bypasses_old_schema_and_handles_malformed_payload(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(lyrics, "CACHE_DIR", Path(directory)):
            cache = lyrics.cache_path("A", "B", "", None)
            cache.write_text(json.dumps({"cachedAt": time.time(), "result": {"ok": True, "lines": []}}), encoding="utf-8")
            self.assertIsNone(lyrics.load_cache("A", "B", "", None))
            cache.write_text("[]", encoding="utf-8")
            self.assertIsNone(lyrics.load_cache("A", "B", "", None))
            lyrics.save_cache("A", "B", "", None, {"ok": True, "synced": False, "instrumental": True, "lines": [], "source": "lrclib"})
            self.assertEqual("lrclib", lyrics.load_cache("A", "B", "", None)["source"])
            self.assertEqual([], list(Path(directory).glob(".lyrics-*")))

    def test_untranslated_result_waits_for_translation_within_deadline(self):
        def translated(*args):
            time.sleep(0.35)
            return {"ok": True, "source": "netease", "synced": True, "hasTranslation": True, "lines": [{"start": 1, "text": "original", "translation": "中文"}]}
        original = {"ok": True, "source": "lrclib", "synced": True, "hasTranslation": False, "lines": [{"start": 1, "text": "original"}]}
        with mock.patch.object(lyrics, "fetch_netease", side_effect=translated), mock.patch.object(lyrics, "fetch_qq", return_value={"ok": False}), mock.patch.object(lyrics, "fetch_lrclib", return_value=original):
            result = lyrics.fetch_online("Artist", "Song", "", 180)
        self.assertEqual("中文", result["lines"][0]["translation"])

    def test_verified_older_translation_beats_new_untranslated_cache(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(lyrics, "CACHE_DIR", Path(directory)):
            translated = {"ok": True, "source": "netease:1", "synced": True, "instrumental": False, "lines": [{"start": 1, "text": "original", "translation": "中文"}]}
            older = Path(directory) / f"v4-{lyrics.cache_key('Artist', 'Song', 'Album', 180)}.json"
            older.write_text(json.dumps({"schema": 4, "cachedAt": time.time() - 100, "result": translated}))
            lyrics.save_cache("Artist", "Song", "Album", 180, {**translated, "source": "lrclib", "lines": [{"start": 1, "text": "original"}]})
            self.assertEqual("中文", lyrics.load_cache("Artist", "Song", "Album", 180)["lines"][0]["translation"])
            self.assertIsNone(lyrics.load_cache("Artist", "Song", "Album", 60))

    def test_untranslated_cache_expires_for_enrichment_but_remains_fallback(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(lyrics, "CACHE_DIR", Path(directory)):
            result = {"ok": True, "source": "lrclib", "synced": True, "instrumental": False, "lines": [{"start": 1, "text": "original"}]}
            with mock.patch.object(lyrics.time, "time", return_value=time.time() - 1000):
                lyrics.save_cache("Artist", "Song", "", 180, result)
            self.assertIsNone(lyrics.load_cache("Artist", "Song", "", 180))
            self.assertEqual("original", lyrics.load_cache("Artist", "Song", "", 180, allow_stale=True)["lines"][0]["text"])

    def test_netease_rate_limit_is_not_reported_as_missing_lyrics(self):
        with mock.patch.object(lyrics, "http_json", return_value=(200, {"code": 405, "message": "操作频繁"})):
            result = lyrics.fetch_netease("Artist", "Song", 180)
        self.assertFalse(result["ok"])
        self.assertTrue(result["temporary"])
        self.assertIn("搜索受限", result["error"])

    def test_plain_result_cannot_preempt_later_synced_lyrics(self):
        plain = {"ok": True, "synced": False, "lines": [{"text": "plain"}]}
        synced = {"ok": True, "synced": True, "lines": [{"start": 1, "text": "timed"}]}
        def later(*args):
            time.sleep(0.35)
            return synced
        with mock.patch.object(lyrics, "fetch_netease", return_value=None), mock.patch.object(lyrics, "fetch_qq", side_effect=later), mock.patch.object(lyrics, "fetch_lrclib", return_value=plain):
            result = lyrics.fetch_online("Artist", "Song", "", 180)
        self.assertTrue(result["synced"])
        self.assertEqual("timed", result["lines"][0]["text"])

    def test_subprocess_cli_exits_before_deadline_with_blocked_providers(self):
        # A real Python process catches regressions where executor shutdown joins losers.
        child = '''import importlib.util, json, sys, time
spec=importlib.util.spec_from_file_location("lyrics_child", sys.argv[1])
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.ONLINE_DEADLINE=0.15
def slow(*args):
    time.sleep(2)
    return None
mod.fetch_netease=slow
mod.fetch_qq=slow
mod.fetch_lrclib=slow
sys.argv=[sys.argv[1], json.dumps({"title":"Uncached unique deadline song","artist":"Test Artist"})]
mod.main()
'''
        with tempfile.TemporaryDirectory() as directory:
            start = time.monotonic()
            process = subprocess.run([sys.executable, "-c", child, str(SCRIPT)], input="", text=True, capture_output=True, timeout=1.5, env={"XDG_CACHE_HOME": directory})
            elapsed = time.monotonic() - start
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertFalse(json.loads(process.stdout)["ok"])
        self.assertLess(elapsed, 1.2)

    def test_subprocess_json_argv_does_not_wait_for_stdin(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "My Song.txt").write_text("hello\nworld", encoding="utf-8")
            request = json.dumps({"title": "My Song", "artist": "Artist", "localDir": directory})
            process = subprocess.Popen([sys.executable, str(SCRIPT), request], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                process.wait(timeout=1.5)
                output = process.stdout.read()
                self.assertEqual("local", json.loads(output)["source"])
                self.assertFalse(process.stderr.read())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stdin.close()
                process.stdout.close()
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
