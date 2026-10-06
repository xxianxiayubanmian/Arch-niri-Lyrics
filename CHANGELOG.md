# Desktop Lyrics changes

## Spotify-only player source

- Select only MPRIS buses matching `org.mpris.MediaPlayer2.spotify` or its instance suffixes. Browser and other MPRIS metadata no longer launch lyric processes, alter the lyric query key, or advance lyric position.
- Keep the selected Spotify session when it is paused while a browser plays. If Spotify exits, cancel the request and clear the state; a browser cannot replace it.
- Added daemon regression coverage for Spotify selection, browser rejection, paused Spotify and Spotify exit. Verified the current session had Firefox playing and Spotify paused; no browser request is eligible. Reloaded only the lyric plugin.

## Platform title normalization

- Strip only provider-added Spotify/MPRIS suffixes such as `- From "..."`, `(Explicit)`, `(Clean)`, `(with ...)` and `(feat. ...)` for search matching. Preserve the original title in state and cache; Live titles remain distinct.
- Real `All The Stars (with SZA) - From "Black Panther: The Album"` request now selects NetEase `526929981`, returning 59 timed lines and 52 translations in 0.49 seconds. This was a title mismatch, not a confirmed current rate-limit response.
- 22 Python regressions passed after the fix; the plugin was reloaded through DMS IPC.

## Translation regression recovery

- Preserve compatible schema-4 recording-validated caches across the alias upgrade. For identical title/artist/album/duration keys, prefer translated cached lyrics over a newer untranslated result. Schemas predating recording validation remain excluded.
- Treat untranslated cache entries as fresh for 15 minutes, retaining them as fallback for up to 30 days. A failed refresh must not blank existing lyrics. Translated and instrumental results retain the normal 30-day lifetime.
- Remove the 250 ms original-only selection cutoff. Providers now get the existing 7.5-second overall deadline to return translations, with immediate return on a translated timed result. Uncached tracks without translations can consequently take longer to load; no retries were added.
- NetEase continues checking eligible candidates for translations instead of stopping at the first untranslated lyric. HTTP-200 responses containing service code 405/429/-460 are explicitly reported as search restrictions, not missing lyrics. Preserve provider error details when available.
- Observed NetEase search returning code 405 / 操作频繁 for Die For You and Flowers queries. Real CLI requests recovered The Weeknd's Die For You (260.253 s, 71 translated lines), Hana Hope's flowers (260.199 s, 35 translated lines), and retained ECLOSE alias lookup cache (190.166 s, 40 translated lines). Recovery used existing verified caches, not a claim that the rate limit cleared. All 21 Python regressions and daemon regressions passed.

## Verified artist aliases

- NetEase and QQ candidate matching recognizes provider-supplied artist alias fields without fuzzy or transliteration guesses. Title and recording-duration checks remain mandatory when duration is known.
- For otherwise plausible NetEase candidates, resolve unmatched artist names through `/api/artist/{id}`. Accept detail aliases only when the returned artist ID equals the requested ID. Memoize details within the lookup and share the existing network deadline; failures never relax identity checks.
- NetEase continues through eligible candidates when an earlier candidate has no lyrics or cannot be fetched. No cross-provider alias inference or permanent artist alias database is introduced.
- Advance lyric cache schema to 5 to bypass pre-alias selections without deleting old cache files.
- Real CLI request for ECLOSE / CHIAKI SATO / BUTTERFLY EFFECT at 190.166 seconds selected NetEase `2058678080` using its verified `佐藤千亜妃` / `Chiaki Sato` identity. Returned 48 timed lines with 40 non-empty translations in 0.66 seconds. All 18 Python regressions and daemon regressions passed; reloaded only desktopLyrics.

## Recording identity and timing fix

- Normalize Chinese metadata to simplified before matching, with bounded per-process memoization. This allows traditional Spotify metadata to match simplified NetEase/QQ metadata without relaxing title or artist identity.
- Reject known candidate durations differing by more than 8 seconds in NetEase, QQ and both LRCLIB lookup paths. Missing duration remains permitted; album/version title distinctions remain intact.
- Advance cache schema to 4 so previously accepted preview recordings cannot survive the corrected matching rules. Historical cache files are not deleted.
- Reproduced 擱淺的人 / 康士坦的變化球 selecting QQ `001aeTvc2KFdY6` (60-second preview) for Spotify's 271.855-second full recording. The correct simplified-title QQ candidate had previously been rejected. After repair, a real request selected NetEase `447925725` in 0.64 seconds, with its first lyric at 27.52 seconds instead of the preview's 0.17 seconds.
- All 14 Python regressions and daemon regression checks passed. Reloaded only the lyric plugin without changing playback or global offset. Full-recording selection and returned timing verified; audio-to-text synchronization was not audited by listening.

## Simplified Chinese display

- Require the installed OpenCC executable; use `tw2s.json` to cover traditional Chinese and Taiwanese variants without vocabulary localization.
- Generate `displayText` and `displayTranslation` only when emitting a response. Original lyric text, timing, provider identity and disk cache remain unchanged. Cache hits receive the same projection as local and network results.
- Desktop and bar current/next lines and the full-lyrics popout use the display fields. Preserve original songs containing Japanese kana or Korean Hangul, while simplifying Chinese translations. This script heuristic is not full language detection.
- Verified 12 Python regressions and the daemon regression script. An actual cached request for 自種自收 converted 24 lines; cache bytes were unchanged. Plugin reload succeeded. The live player had moved to a different track without available lyrics, so a visual check of this song was not performed.

## Reliability update

- Read title, artist, album and duration from one player metadata snapshot; debounce metadata changes for 180 ms.
- Give each lyric request its own process and generation. Cancel obsolete requests and reject late responses after track changes or disable. Pass JSON directly to Python, without shell request files.
- Clamp playback position instead of wrapping at track end. Locate lyric lines with binary search, including seeking and blank instrumental intervals.
- Query NetEase, QQ Music and LRCLIB concurrently within a 7.5-second online deadline; daemon watchdog is 10 seconds. Plain lyrics remain a fallback while timed results are outstanding. Timed lyrics allow a 250 ms grace for translations; slow workers do not delay CLI shutdown.
- Require normalized title and supplied primary artist matches. Duration and album only rank eligible matches. Cross-language aliases are not inferred: a romanized title may fall back to plain lyrics even when another provider has a differently named timed version.
- Read local LRC/TXT before disk cache or network. Remove QML memory caching; use versioned, atomic disk cache writes with a 30-day TTL. Old cache schemas are ignored. Local files do not wait for online translation.
- Parse multiple timestamps, signed LRC offset tags, blank intervals and same-time bilingual lines. Preserve plain-text line breaks; never substitute original lyrics for missing translations.
- Honor translation visibility in the bar, popout and desktop; inherit global desktop settings unless the instance overrides presentation. Bound long text and leave intro/interlude lines blank.

## Verification

- `python3 -B -m unittest discover -s ~/.config/DankMaterialShell/plugins/DesktopLyrics -p test_fetch_lyrics.py -v`: 10 passing regression tests, including real subprocess shutdown and stdin behavior.
- `node ~/.config/DankMaterialShell/plugins/DesktopLyrics/test_daemon.cjs`: passed metadata, end-position, seeking, disabled-state and stale-response regressions.
- Live lookup of EYES WIDE SHUT / CHIAKI SATO returned 49 timed lines from LRCLIB in 0.78 seconds during verification. Provider availability and timing vary.
- Reloaded only desktopLyrics through DMS IPC. Subsequent runtime log showed successful daemon loading; final screenshot showed original and translated lyrics in the live bar. Desktop widget was obscured by application windows and was not visually verified.
