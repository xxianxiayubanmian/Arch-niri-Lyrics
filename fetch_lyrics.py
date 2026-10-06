#!/usr/bin/env python3
"""Fetch synced lyrics for the current MPRIS track."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

LRCLIB_GET = "https://lrclib.net/api/get"
LRCLIB_SEARCH = "https://lrclib.net/api/search"
NETEASE_SEARCH = "https://music.163.com/api/search/get/web"
NETEASE_LYRIC = "https://music.163.com/api/song/lyric"
QQ_SEARCH = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
QQ_LYRIC = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
USER_AGENT = "DMS-DesktopLyrics/1.0 (https://github.com/AvengeMedia/DankMaterialShell)"
NETEASE_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMESTAMP_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
TAG_RE = re.compile(r"^\[(ti|ar|al|offset|by|length):", re.IGNORECASE)
OFFSET_RE = re.compile(r"^\[offset:([+-]?\d+)\]$", re.IGNORECASE)
INFO_LINE_RE = re.compile(r"(作词|作曲|编曲|制作人|出品|录音|混音|母带)\s*[:：]")
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "DankMaterialShell" / "desktop-lyrics"
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
CACHE_SCHEMA = 5
HTTP_TIMEOUT = 3.0
ONLINE_DEADLINE = 7.5
_worker_deadline = threading.local()

def display_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Project lyrics for display without changing source text or cached data."""
    if not payload.get("ok") or not payload.get("lines"):
        return payload
    lines = [dict(line) for line in payload["lines"]]
    # Preserve Japanese/Korean originals as a whole, including kanji-only lines.
    foreign_original = any(re.search(r"[\u3040-\u30ff\uac00-\ud7af]", line.get("text", "")) for line in lines)
    texts = []
    for line in lines:
        texts.extend([line.get("text", ""), line.get("translation", "")])
    converted = subprocess.run(
        ["opencc", "-c", "tw2s.json"], input=json.dumps(texts, ensure_ascii=False),
        text=True, encoding="utf-8", capture_output=True, check=True, timeout=1.5,
    )
    simplified = json.loads(converted.stdout)
    for index, line in enumerate(lines):
        line["displayText"] = line.get("text", "") if foreign_original else simplified[index * 2]
        translation = line.get("translation", "")
        line["displayTranslation"] = translation if re.search(r"[\u3040-\u30ff\uac00-\ud7af]", translation) else simplified[index * 2 + 1]
    return {**payload, "lines": lines}


def emit(payload: dict[str, Any]) -> None:
    try:
        displayed = display_payload(payload)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        displayed = {"ok": False, "error": f"简体歌词转换失败，请检查 OpenCC：{exc}"}
    sys.stdout.write(json.dumps(displayed, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def fail(message: str, **extra: Any) -> None:
    payload = {"ok": False, "error": message}
    payload.update(extra)
    emit(payload)


def read_request() -> dict[str, Any]:
    raw = ""
    if "--request-file" in sys.argv:
        idx = sys.argv.index("--request-file")
        path = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if path:
            try:
                raw = Path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeError, ValueError) as exc:
                fail(f"cannot read request: {exc}")
                raise SystemExit(0) from exc
    if "--request-file" not in sys.argv and len(sys.argv) > 1:
        raw = sys.argv[1]
    if not raw.strip():
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw.strip():
        raw = "{}"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        fail(f"invalid request json: {exc}")
        raise SystemExit(0) from exc
    if not isinstance(data, dict):
        fail("request must be a json object")
        raise SystemExit(0)
    return data


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def first_artist(artist: str) -> str:
    if not artist:
        return ""
    return re.split(r"\s*(?:/|,|&|feat\.?|ft\.?|featuring)\s*", artist, maxsplit=1, flags=re.IGNORECASE)[0].strip()


def parse_timestamp(minute: str, second: str, fraction: str | None) -> float:
    frac = 0.0
    if fraction:
        if len(fraction) == 1:
            frac = int(fraction) / 10
        elif len(fraction) == 2:
            frac = int(fraction) / 100
        else:
            frac = int(fraction[:3]) / 1000
    return int(minute) * 60 + int(second) + frac


def parse_lrc(text: str) -> list[dict[str, Any]]:
    if not isinstance(text, str):
        return []
    lines: list[dict[str, Any]] = []
    offset = 0
    for raw_line in text.splitlines():
        offset_match = OFFSET_RE.fullmatch(raw_line.strip())
        if offset_match:
            offset = int(offset_match.group(1))
    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if OFFSET_RE.fullmatch(raw_line):
            continue
        if not raw_line or TAG_RE.match(raw_line):
            continue
        matches = list(TIMESTAMP_RE.finditer(raw_line))
        if not matches or matches[0].start() != 0:
            continue
        if TIMESTAMP_RE.sub("", raw_line[:matches[-1].end()]).strip():
            continue
        words = raw_line[matches[-1].end():].strip()
        if INFO_LINE_RE.match(words):
            continue
        for match in matches:
            start = parse_timestamp(match.group(1), match.group(2), match.group(3)) - offset / 1000
            lines.append({"start": round(start, 3), "text": words})
    lines.sort(key=lambda item: item["start"])
    merged: list[dict[str, Any]] = []
    for line in lines:
        if merged and abs(merged[-1]["start"] - line["start"]) < 0.02:
            if line["text"] and line["text"] != merged[-1]["text"]:
                if merged[-1]["text"]:
                    merged[-1]["translation"] = line["text"]
                else:
                    merged[-1]["text"] = line["text"]
            continue
        merged.append(line)
    for index, line in enumerate(merged):
        line.setdefault("translation", "")
        line["end"] = merged[index + 1]["start"] if index + 1 < len(merged) else None
    return merged


def candidate_paths(local_dir: str, artist: str, title: str, album: str) -> list[Path]:
    if not local_dir:
        return []
    try:
        root = Path(os.path.expanduser(local_dir))
        if not root.is_dir():
            return []
    except (OSError, ValueError):
        return []
    names = []
    for value in (f"{artist} - {title}" if artist else "", title, f"{album} - {title}" if album else ""):
        value = clean_text(value)
        if value:
            names.append(value)
    paths: list[Path] = []
    for name in names:
        for ext in (".lrc", ".txt"):
            paths.append(root / f"{name}{ext}")
            if artist:
                paths.append(root / artist / f"{title}{ext}")
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def load_local(local_dir: str, artist: str, title: str, album: str) -> dict[str, Any] | None:
    for path in candidate_paths(local_dir, artist, title, album):
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError, ValueError):
            continue
        lines = parse_lrc(text)
        if not lines and not text.strip():
            continue
        synced = bool(lines)
        plain = "\n".join(line["text"] for line in lines) if synced else text
        if not synced:
            lines = [{"start": 0.0, "end": None, "text": line, "translation": ""} for line in text.splitlines() if line.strip()]
        return {
            "ok": True, "source": "local", "path": str(path),
            "instrumental": False, "synced": synced, "lines": lines,
            "plain": plain, "hasTranslation": any(line.get("translation") for line in lines),
            "translationSource": "local" if any(line.get("translation") for line in lines) else "",
        }
    return None


def http_json(url: str, timeout: float = HTTP_TIMEOUT, headers: dict[str, str] | None = None) -> tuple[int, Any]:
    remaining = getattr(_worker_deadline, "until", float("inf")) - time.monotonic()
    if remaining <= 0:
        raise RuntimeError("online deadline exceeded")
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=min(timeout, remaining)) as response:
            raw = response.read(2_000_001).decode("utf-8", "replace")
            if len(raw) > 2_000_000:
                raise RuntimeError("oversized provider response")
            status = getattr(response, "status", 200)
            if not raw.strip():
                return status, None
            return status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        return exc.code, body
    except (OSError, ValueError, TimeoutError, UnicodeError) as exc:
        raise RuntimeError(str(exc)) from exc
def cache_key(artist: str, title: str, album: str, duration: float | None) -> str:
    duration_part = f"{duration:.3f}" if duration else ""
    raw = "\u001f".join([title.lower(), artist.lower(), album.lower(), duration_part])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def cache_path(artist: str, title: str, album: str, duration: float | None) -> Path:
    return CACHE_DIR / f"v{CACHE_SCHEMA}-{cache_key(artist, title, album, duration)}.json"


def load_cache(artist: str, title: str, album: str, duration: float | None, allow_stale: bool = False) -> dict[str, Any] | None:
    # Schema 4 already enforced recording duration. Schema 5 only added aliases,
    # so its upgrade must not discard verified translations from schema 4.
    candidates = []
    key = cache_key(artist, title, album, duration)
    for schema in (CACHE_SCHEMA, 4):
        path = CACHE_DIR / f"v{schema}-{key}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
        if not isinstance(data, dict) or data.get("schema") != schema:
            continue
        cached_at = data.get("cachedAt")
        if not isinstance(cached_at, (int, float)) or isinstance(cached_at, bool):
            continue
        age = time.time() - cached_at
        if not 0 <= age <= CACHE_TTL_SECONDS:
            continue
        result = data.get("result")
        if not isinstance(result, dict) or result.get("ok") is not True or not isinstance(result.get("lines"), list):
            continue
        if not isinstance(result.get("source"), str) or not isinstance(result.get("synced"), bool) or not isinstance(result.get("instrumental"), bool):
            continue
        if any(not isinstance(line, dict) or not isinstance(line.get("text"), str) or not isinstance(line.get("start"), (float, int)) for line in result["lines"]):
            continue
        translated = any(bool(line.get("translation")) for line in result["lines"])
        # Untranslated success is provisional, not a 30-day verdict.
        if not allow_stale and not translated and not result.get("instrumental") and age > 900:
            continue
        candidates.append((translated, bool(result.get("synced")), cached_at, result))
    return max(candidates, key=lambda item: item[:3])[3] if candidates else None


def save_cache(artist: str, title: str, album: str, duration: float | None, result: dict[str, Any]) -> None:
    if not result.get("ok"):
        return
    temporary: str | None = None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = cache_path(artist, title, album, duration)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CACHE_DIR, prefix=".lyrics-", delete=False) as stream:
            temporary = stream.name
            json.dump({"schema": CACHE_SCHEMA, "cachedAt": time.time(), "result": result}, stream, ensure_ascii=False)
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError):
        pass
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def duration_close(left: float | None, right: float | None, tolerance: float = 8.0) -> bool:
    try:
        return not left or not right or abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError, OverflowError):
        return False


@lru_cache(maxsize=256)
def normalized_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", clean_text(value)).casefold()
    if re.search(r"[\u3400-\u9fff]", text):
        text = subprocess.run(
            ["opencc", "-c", "tw2s.json"], input=text, text=True,
            encoding="utf-8", capture_output=True, check=True, timeout=1.5,
        ).stdout
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def title_variants(value: Any) -> list[str]:
    text = clean_text(value)
    variants = [text]
    for pattern in (r"\s+-\s+From\s+['\"].*?['\"]\s*$", r"\s*\((?:from|explicit|clean|with|feat\.?|ft\.?)\b.*?\)\s*$"):
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
    if text and text not in variants:
        variants.append(text)
    return variants


def matches_song(found_title: Any, found_artist: Any, artist: str, title: str) -> bool:
    # Match provider-cleaned titles while retaining exact artist identity.
    found = normalized_name(found_title)
    wanted = {normalized_name(candidate) for candidate in title_variants(title)}
    if not found or found not in wanted:
        return False
    if not artist:
        return True
    wanted_artist = normalized_name(first_artist(artist))
    artists = [normalized_name(first_artist(part)) for part in re.split(r"[,/&]\s*", clean_text(found_artist))]
    return bool(wanted_artist) and wanted_artist in artists


def score_result(item: dict[str, Any], artist: str, title: str, album: str, duration: float | None) -> int:
    if not matches_song(item.get("trackName"), item.get("artistName"), artist, title):
        return -1
    if not duration_close(duration, item.get("duration")):
        return -1
    score = 8
    if album and normalized_name(item.get("albumName")) == normalized_name(album):
        score += 3
    if item.get("syncedLyrics"):
        score += 5
    if duration_close(duration, item.get("duration")):
        score += 2
    return score


def from_lrclib_item(item: dict[str, Any], source: str) -> dict[str, Any]:
    synced = parse_lrc(item.get("syncedLyrics") or "")
    plain = item.get("plainLyrics") if isinstance(item.get("plainLyrics"), str) else ""
    if not synced and plain.strip():
        lines = [{"start": 0.0, "end": None, "text": line, "translation": ""} for line in plain.splitlines() if line.strip()]
        return {
            "ok": True,
            "source": source,
            "id": item.get("id"),
            "instrumental": bool(item.get("instrumental")),
            "synced": False,
            "lines": lines,
            "plain": plain,
            "hasTranslation": False,
            "translationSource": "",
        }
    if not synced:
        return {
            "ok": True,
            "source": source,
            "id": item.get("id"),
            "instrumental": bool(item.get("instrumental")),
            "synced": False,
            "lines": [],
            "plain": "",
            "hasTranslation": False,
            "translationSource": "",
        }
    return {
        "ok": True,
        "source": source,
        "id": item.get("id"),
        "instrumental": bool(item.get("instrumental")),
        "synced": True,
        "lines": synced,
        "plain": "\n".join(line["text"] for line in synced),
        "hasTranslation": any(line.get("translation") for line in synced),
        "translationSource": source if any(line.get("translation") for line in synced) else "",
    }


def attach_translations(lines: list[dict[str, Any]], translations: list[dict[str, Any]], tolerance: float = 1.6) -> int:
    if not lines:
        return 0
    matched = 0
    trans_index = 0
    for line in lines:
        line.setdefault("translation", "")
        start = float(line.get("start") or 0)
        best = None
        best_delta = tolerance
        idx = trans_index
        while idx < len(translations):
            candidate = translations[idx]
            delta = abs(float(candidate.get("start") or 0) - start)
            if float(candidate.get("start") or 0) - start > tolerance and best is not None:
                break
            if delta <= best_delta:
                best = candidate
                best_delta = delta
                trans_index = idx
            idx += 1
        if best and best.get("text") and best["text"] != line.get("text"):
            line["translation"] = best["text"]
            matched += 1
    return matched


def artist_names(record: dict[str, Any]) -> list[str]:
    """Only use names supplied together by the provider, never guessed aliases."""
    names = [record.get("name")]
    for key in ("alias", "aliases", "transNames", "trans"):
        value = record.get(key)
        if isinstance(value, list):
            names.extend(value)
        elif isinstance(value, str):
            names.append(value)
    return [name for name in names if isinstance(name, str) and name.strip()]


def matches_artists(records: Any, artist: str) -> bool:
    if not artist:
        return True
    wanted = normalized_name(first_artist(artist))
    return bool(wanted) and isinstance(records, list) and any(
        normalized_name(name) == wanted
        for record in records if isinstance(record, dict)
        for name in artist_names(record)
    )


def resolve_netease_artists(song: dict[str, Any], artist: str, resolved: dict[int, dict[str, Any]]) -> dict[str, Any]:
    records = song.get("artists") or []
    if matches_artists(records, artist):
        return song
    enriched = []
    for record in records:
        if not isinstance(record, dict):
            continue
        artist_id = record.get("id")
        if not isinstance(artist_id, int) or artist_id <= 0:
            enriched.append(record)
            continue
        if artist_id not in resolved:
            resolved[artist_id] = record
            try:
                status, body = http_json(f"https://music.163.com/api/artist/{artist_id}", headers={"Referer": "https://music.163.com/"})
                detail = body.get("artist") if isinstance(body, dict) else None
                if status == 200 and isinstance(detail, dict) and detail.get("id") == artist_id:
                    # Keep the search name plus aliases verified for this exact ID.
                    resolved[artist_id] = {**record, "alias": artist_names(record) + artist_names(detail)}
            except RuntimeError:
                pass
        enriched.append(resolved[artist_id])
    return {**song, "artists": enriched}


def score_netease_song(song: dict[str, Any], artist: str, title: str, duration: float | None) -> int:
    title_matches = {normalized_name(candidate) for candidate in title_variants(title)}
    if normalized_name(song.get("name")) not in title_matches or not matches_artists(song.get("artists"), artist):
        return -1
    try:
        length = float(song.get("duration")) / 1000
    except (TypeError, ValueError, OverflowError):
        length = None
    if not duration_close(duration, length):
        return -1
    return 8 + (4 if duration and length and duration_close(duration, length, 6.0) else 0)


def fetch_netease(artist: str, title: str, duration: float | None) -> dict[str, Any]:
    query_title = title_variants(title)[-1]
    query = " ".join(part for part in [query_title, artist] if part)
    url = f"{NETEASE_SEARCH}?{urllib.parse.urlencode({'s': query, 'type': 1, 'offset': 0, 'limit': 8, 'total': 'true'})}"
    status, body = http_json(url, headers={"User-Agent": NETEASE_UA, "Referer": "https://music.163.com/"})
    if isinstance(body, dict) and body.get("code") in (405, 429, -460):
        return {"ok": False, "error": "网易云搜索受限，请稍后再试", "temporary": True, "source": "netease"}
    if status != 200 or not isinstance(body, dict):
        return {"ok": False, "error": "no lyrics found", "source": "netease"}
    search_result = body.get("result")
    songs = search_result.get("songs") if isinstance(search_result, dict) else []
    songs = songs if isinstance(songs, list) else []
    if not songs:
        return {"ok": False, "error": "no lyrics found", "source": "netease"}
    # Resolve identities only for plausible title/duration candidates. Artist
    # detail requests share the provider deadline and are memoized per lookup.
    candidates = []
    for song in songs:
        if not isinstance(song, dict) or not song.get("id") or not any(normalized_name(song.get("name")) == normalized_name(candidate) for candidate in title_variants(title)):
            continue
        try:
            length = float(song.get("duration")) / 1000 if song.get("duration") else None
        except (ValueError, TypeError):
            continue
        if duration_close(duration, length):
            candidates.append(song)
    candidates.sort(key=lambda song: score_netease_song(song, artist, title, duration), reverse=True)
    resolved: dict[int, dict[str, Any]] = {}
    fallback = None
    for candidate in candidates:
        song = resolve_netease_artists(candidate, artist, resolved)
        if score_netease_song(song, artist, title, duration) < 0:
            continue
        lyric_url = f"{NETEASE_LYRIC}?{urllib.parse.urlencode({'id': song['id'], 'lv': 1, 'tv': 1, 'kv': 1})}"
        try:
            status, lyric_body = http_json(lyric_url, headers={"User-Agent": NETEASE_UA, "Referer": "https://music.163.com/"})
        except RuntimeError:
            continue
        if status != 200 or not isinstance(lyric_body, dict):
            continue
        original_data, translated_data = lyric_body.get("lrc"), lyric_body.get("tlyric")
        original = parse_lrc(original_data.get("lyric") if isinstance(original_data, dict) else "")
        translations = parse_lrc(translated_data.get("lyric") if isinstance(translated_data, dict) else "")
        if not original:
            continue
        source = f"netease:{song['id']}"
        result = {
            "ok": True, "source": source, "id": song["id"],
            "instrumental": False, "synced": True, "lines": original,
            "plain": "\n".join(line["text"] for line in original),
        }
        result = apply_translations(result, translations, source)
        if result.get("hasTranslation"):
            return result
        if fallback is None:
            fallback = result
    return fallback or {"ok": False, "error": "no lyrics found", "source": "netease"}

def score_qq_song(song: dict[str, Any], artist: str, title: str, duration: float | None) -> int:
    if normalized_name(song.get("songname") or song.get("name")) != normalized_name(title) or not matches_artists(song.get("singer"), artist):
        return -1
    if not duration_close(duration, song.get("interval")):
        return -1
    return 8 + (4 if duration and duration_close(duration, song.get("interval"), 6.0) else 0)


def fetch_qq(artist: str, title: str, duration: float | None) -> dict[str, Any]:
    query = " ".join(part for part in [title, artist] if part)
    url = f"{QQ_SEARCH}?{urllib.parse.urlencode({'format': 'json', 'inCharset': 'utf8', 'outCharset': 'utf-8', 'notice': 0, 'platform': 'yqq.json', 'needNewCode': 0, 'w': query, 'p': 1, 'n': 5, 'catZhida': 1})}"
    status, body = http_json(url, headers={"User-Agent": NETEASE_UA, "Referer": "https://y.qq.com/"})
    if status != 200 or not isinstance(body, dict):
        return {"ok": False, "error": "no lyrics found", "source": "qq"}
    search_data = body.get("data")
    song_data = search_data.get("song") if isinstance(search_data, dict) else None
    songs = song_data.get("list") if isinstance(song_data, dict) else []
    songs = songs if isinstance(songs, list) else []
    if not songs:
        return {"ok": False, "error": "no lyrics found", "source": "qq"}
    ranked = sorted((song for song in songs if isinstance(song, dict)), key=lambda item: score_qq_song(item, artist, title, duration), reverse=True)
    best = ranked[0] if ranked else {}
    if score_qq_song(best, artist, title, duration) < 0:
        return {"ok": False, "error": "no lyrics found", "source": "qq"}
    mid = best.get("songmid")
    if not mid:
        return {"ok": False, "error": "no lyrics found", "source": "qq"}
    lyric_url = f"{QQ_LYRIC}?{urllib.parse.urlencode({'songmid': mid, 'format': 'json', 'inCharset': 'utf8', 'outCharset': 'utf-8', 'nobase64': 0, 'g_tk': 5381, 'platform': 'yqq.json'})}"
    status, lyric_body = http_json(lyric_url, headers={"User-Agent": NETEASE_UA, "Referer": "https://y.qq.com/"})
    if status != 200 or not isinstance(lyric_body, dict):
        return {"ok": False, "error": "no lyrics found", "source": "qq"}
    def decode_qq_field(value: Any) -> str:
        if not value:
            return ""
        text = str(value)
        try:
            import base64
            return base64.b64decode(text).decode("utf-8", "replace")
        except Exception:
            return text
    original = parse_lrc(decode_qq_field(lyric_body.get("lyric")))
    translations = parse_lrc(decode_qq_field(lyric_body.get("trans")))
    if not original:
        return {"ok": False, "error": "no lyrics found", "source": "qq"}
    result = {
        "ok": True,
        "source": f"qq:{mid}",
        "id": mid,
        "instrumental": False,
        "synced": True,
        "lines": original,
        "plain": "\n".join(line["text"] for line in original),
    }
    return apply_translations(result, translations, f"qq:{mid}")


def apply_translations(result: dict[str, Any], translations: list[dict[str, Any]], source: str) -> dict[str, Any]:
    lines = result.get("lines") or []
    for line in lines:
        line.setdefault("translation", "")
    if lines and not result.get("instrumental") and result.get("synced") and translations:
        attach_translations(lines, translations)
    result["lines"] = lines
    result["hasTranslation"] = any(line.get("translation") for line in lines)
    result["translationSource"] = source if result["hasTranslation"] else ""
    return result


def fetch_lrclib(artist: str, title: str, album: str, duration: float | None) -> dict[str, Any]:
    query = {
        "track_name": title,
        "artist_name": artist,
    }
    if album:
        query["album_name"] = album
    if duration:
        query["duration"] = f"{duration:.3f}"
    try:
        status, body = http_json(f"{LRCLIB_GET}?{urllib.parse.urlencode(query)}")
    except RuntimeError:
        status, body = 0, None
    if status == 200 and isinstance(body, dict) and score_result(body, artist, title, album, duration) >= 0:
        result = from_lrclib_item(body, "lrclib")
        if result["lines"] or result["instrumental"]:
            return result
    try:
        status, body = http_json(f"{LRCLIB_SEARCH}?{urllib.parse.urlencode({'track_name': title, 'artist_name': artist})}")
    except RuntimeError:
        return {"ok": False, "error": "no lyrics found", "source": "lrclib"}
    if status != 200 or not isinstance(body, list) or not body:
        return {"ok": False, "error": "no lyrics found", "source": "lrclib"}
    ranked = sorted((item for item in body if isinstance(item, dict) and score_result(item, artist, title, album, duration) >= 0),
                    key=lambda item: score_result(item, artist, title, album, duration), reverse=True)
    for item in ranked:
        result = from_lrclib_item(item, "lrclib-search")
        if result["lines"] or result["instrumental"]:
            return result
    return {"ok": False, "error": "no lyrics found", "source": "lrclib"}



def fetch_online(artist: str, title: str, album: str, duration: float | None) -> dict[str, Any]:
    # Daemon workers allow CLI exit without joining slow or blocked network providers.
    deadline = time.monotonic() + ONLINE_DEADLINE
    completed: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
    providers = (
        ("netease", fetch_netease, (artist, title, duration)),
        ("qq", fetch_qq, (artist, title, duration)),
        ("lrclib", fetch_lrclib, (artist, title, album, duration)),
    )

    def run_provider(name: str, provider: Any, arguments: tuple[Any, ...]) -> None:
        _worker_deadline.until = deadline
        try:
            result = provider(*arguments)
            if not isinstance(result, dict):
                result = {"ok": False}
        except Exception as exc:  # Preserve the failure cause without crashing the request.
            result = {"ok": False, "error": f"{name}: {exc}"}
        completed.put((name, result))

    for name, provider, arguments in providers:
        threading.Thread(target=run_provider, args=(name, provider, arguments), daemon=True).start()
    fallback: dict[str, Any] | None = None
    remaining = len(providers)
    errors: list[str] = []
    while remaining:
        wait_until = deadline
        try:
            _name, result = completed.get(timeout=max(0.0, wait_until - time.monotonic()))
        except queue.Empty:
            break
        remaining -= 1
        if not result.get("ok") or not (result.get("lines") or result.get("instrumental")):
            if result.get("error"):
                errors.append(str(result["error"]))
            continue
        if result.get("synced") and result.get("hasTranslation"):
            return result
        if fallback is None or (not fallback.get("synced") and result.get("synced")):
            fallback = result
    if fallback:
        if errors:
            fallback = {**fallback, "providerErrors": errors}
        return fallback
    message = next((error for error in errors if error != "no lyrics found"), "暂无匹配歌词")
    return {"ok": False, "error": message, "source": "netease+qq+lrclib"}


def main() -> int:
    request = read_request()
    title = clean_text(request.get("title"))
    artist = clean_text(request.get("artist"))
    album = clean_text(request.get("album"))
    duration = request.get("duration")
    try:
        duration_value = float(duration) if duration not in (None, "", 0, "0") else None
        if duration_value is not None and (not 0 < duration_value < float("inf")):
            duration_value = None
    except (TypeError, ValueError, OverflowError):
        duration_value = None
    local_dir = clean_text(request.get("localDir"))
    if not title:
        fail("missing title")
        return 0

    local = load_local(local_dir, artist, title, album)
    if local:
        local.update({"title": title, "artist": artist, "album": album, "fromCache": False})
        emit(local)
        return 0
    cached = load_cache(artist, title, album, duration_value)
    if cached:
        cached = dict(cached)
        cached.update({"title": title, "artist": artist, "album": album, "fromCache": True})
        emit(cached)
        return 0
    stale = load_cache(artist, title, album, duration_value, allow_stale=True)
    result = fetch_online(artist, title, album, duration_value)
    if stale and (not result.get("ok") or (stale.get("synced") and not result.get("synced"))):
        result = {**stale, "fromCache": True}
    result.update({"title": title, "artist": artist, "album": album, "fromCache": bool(result.get("fromCache"))})
    if result.get("ok"):
        save_cache(artist, title, album, duration_value, result)
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
