import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Services
import qs.Modules.Plugins
import qs.Widgets

PluginComponent {
    id: root

    readonly property string pluginKey: pluginId || "desktopLyrics"
    readonly property string scriptPath: {
        const dir = pluginService && pluginService.availablePlugins[pluginKey] ? pluginService.availablePlugins[pluginKey].pluginDirectory : "";
        if (dir)
            return dir + "/fetch_lyrics.py";
        return Paths.strip(Paths.config) + "/plugins/DesktopLyrics/fetch_lyrics.py";
    }
    property real offsetMs: pluginData.offsetMs !== undefined ? Number(pluginData.offsetMs) : 0
    property string localDir: pluginData.localDir || ""
    property bool enabled: pluginData.enabled !== undefined ? pluginData.enabled : true
    property string lastQueryKey: ""
    property int fetchGeneration: 0
    property var activeRequest: null
    readonly property var spotifyPlayer: selectSpotify(MprisController.availablePlayers || [])

    function isSpotify(player) {
        return !!player && /^org\.mpris\.MediaPlayer2\.spotify(?:\.|$)/i.test(String(player.dbusName || ""));
    }

    function selectSpotify(players) {
        const spotify = players.filter(player => isSpotify(player));
        return spotify.find(player => player.isPlaying) || spotify[0] || null;
    }

    onSpotifyPlayerChanged: scheduleRefresh(true)
    PluginGlobalVar {
        id: lyricsState
        varName: "lyricsState"
        defaultValue: emptyState("idle", "")
    }

    function emptyState(status, message) {
        return {
            "status": status,
            "message": message || "",
            "title": "",
            "artist": "",
            "album": "",
            "source": "",
            "synced": false,
            "instrumental": false,
            "hasTranslation": false,
            "lines": [],
            "currentIndex": -1,
            "currentLine": "",
            "currentTranslation": "",
            "nextLine": "",
            "nextTranslation": "",
            "position": 0,
            "isPlaying": false,
            "queryKey": ""
        };
    }

    function cloneState(base) {
        return {
            "status": base.status || "idle",
            "message": base.message || "",
            "title": base.title || "",
            "artist": base.artist || "",
            "album": base.album || "",
            "source": base.source || "",
            "synced": !!base.synced,
            "instrumental": !!base.instrumental,
            "hasTranslation": !!base.hasTranslation,
            "lines": Array.isArray(base.lines) ? base.lines : [],
            "currentIndex": base.currentIndex !== undefined && base.currentIndex !== null ? base.currentIndex : -1,
            "currentLine": base.currentLine || "",
            "currentTranslation": base.currentTranslation || "",
            "nextLine": base.nextLine || "",
            "nextTranslation": base.nextTranslation || "",
            "position": base.position || 0,
            "isPlaying": !!base.isPlaying,
            "queryKey": base.queryKey || ""
        };
    }

    function publish(next) {
        lyricsState.set(next);
    }

    function trackMeta(player) {
        if (!isSpotify(player))
            return {title: "", artist: "", album: "", duration: null, url: "", trackId: "", identity: ""};
        const source = player;
        const data = source.metadata || {};
        const artists = data["xesam:artist"];
        const length = Number(data["mpris:length"] !== undefined ? data["mpris:length"] / 1000000 : source.length);
        return {
            title: String(data["xesam:title"] || source.trackTitle || "").trim(),
            artist: (Array.isArray(artists) ? artists.join(", ") : String(artists || source.trackArtist || "")).trim(),
            album: String(data["xesam:album"] || source.trackAlbum || "").trim(),
            duration: Number.isFinite(length) && length > 0 ? length : null,
            url: String(data["xesam:url"] || ""),
            trackId: String(data["mpris:trackid"] || ""),
            identity: String(player.identity || "")
        };
    }

    function currentPosition() {
        const player = root.spotifyPlayer;
        if (!player)
            return 0;
        const raw = Number(player.position || 0);
        const length = trackMeta(player).duration;
        const position = Number.isFinite(raw) ? Math.max(0, raw) : 0;
        return Math.max(0, (length ? Math.min(position, length) : position) + root.offsetMs / 1000);
    }

    function queryKeyFor(player) {
        if (!player)
            return "";
        const meta = trackMeta(player);
        return JSON.stringify([meta.identity, meta.trackId, meta.title, meta.artist, meta.album, meta.url, meta.duration, root.localDir]);
    }

    function lineAt(lines, position) {
        if (!Array.isArray(lines) || lines.length === 0)
            return {
                "index": -1,
                "current": "",
                "currentTranslation": "",
                "next": "",
                "nextTranslation": ""
            };

        let low = 0;
        let high = lines.length;
        while (low < high) {
            const middle = (low + high) >>> 1;
            if (Number(lines[middle].start || 0) <= position)
                low = middle + 1;
            else
                high = middle;
        }
        let index = low - 1;
        if (index >= 0 && lines[index].end != null && position >= Number(lines[index].end))
            index = -1;
        const current = index >= 0 ? lines[index] : null;
        const upcoming = low < lines.length ? lines[low] : null;
        return {
            "index": index,
            "current": current ? (current.displayText !== undefined ? current.displayText : current.text || "") : "",
            "currentTranslation": current ? (current.displayTranslation !== undefined ? current.displayTranslation : current.translation || "") : "",
            "next": upcoming ? (upcoming.displayText !== undefined ? upcoming.displayText : upcoming.text || "") : "",
            "nextTranslation": upcoming ? (upcoming.displayTranslation !== undefined ? upcoming.displayTranslation : upcoming.translation || "") : ""
        };
    }

    function applyPosition(base) {
        const next = cloneState(base || lyricsState.value || emptyState("idle", ""));
        const player = root.spotifyPlayer;
        next.isPlaying = !!(player && player.isPlaying);
        next.position = currentPosition();
        if (next.synced && next.lines.length) {
            const hit = lineAt(next.lines, next.position);
            next.currentIndex = hit.index;
            next.currentLine = hit.current;
            next.currentTranslation = hit.currentTranslation;
            next.nextLine = hit.next;
            next.nextTranslation = hit.nextTranslation;
        } else if (next.lines.length && !next.synced) {
            next.currentIndex = 0;
            next.currentLine = next.lines[0].displayText !== undefined ? next.lines[0].displayText : next.lines[0].text || "";
            next.currentTranslation = next.lines[0].displayTranslation !== undefined ? next.lines[0].displayTranslation : next.lines[0].translation || "";
            next.nextLine = next.lines.length > 1 ? (next.lines[1].displayText !== undefined ? next.lines[1].displayText : next.lines[1].text || "") : "";
            next.nextTranslation = next.lines.length > 1 ? (next.lines[1].displayTranslation !== undefined ? next.lines[1].displayTranslation : next.lines[1].translation || "") : "";
        }
        return next;
    }

    function handleResponse(stdout, exitCode, meta) {
        if (!meta || meta.generation !== root.fetchGeneration || !root.enabled || meta.queryKey !== queryKeyFor(root.spotifyPlayer))
            return;
        if (exitCode !== 0) {
            publish(Object.assign(emptyState("error", "歌词查询失败"), meta));
            return;
        }
        let parsed = null;
        try {
            parsed = JSON.parse((stdout || "").trim().split("\n").filter(Boolean).pop() || "{}");
        } catch (e) {
            parsed = {
                "ok": false,
                "error": "invalid lyrics response"
            };
        }
        if (!parsed || parsed.ok !== true || !Array.isArray(parsed.lines)) {
            const err = parsed && parsed.error ? parsed.error : "暂无歌词";
            publish(Object.assign(emptyState("missing", err), meta));
            return;
        }
        const next = applyPosition({
            "status": parsed.instrumental ? "instrumental" : "ready",
            "message": parsed.instrumental ? "纯音乐" : (parsed.synced ? "" : "无时间轴，显示全文"),
            "title": meta.title,
            "artist": meta.artist,
            "album": meta.album,
            "source": parsed.source || "",
            "synced": !!parsed.synced,
            "instrumental": !!parsed.instrumental,
            "hasTranslation": !!parsed.hasTranslation,
            "lines": parsed.lines || [],
            "queryKey": meta.queryKey
        });
        publish(next);
    }

    function cancelRequest() {
        ++root.fetchGeneration;
        fetchTimeout.stop();
        const request = root.activeRequest;
        root.activeRequest = null;
        if (request) {
            if (request.running)
                request.signal(9);
            else
                request.destroy();
        }
    }

    function fetchLyrics(player) {
        const meta = trackMeta(player);
        if (!meta.title) {
            publish(emptyState("idle", "等待曲目信息"));
            return;
        }
        meta.queryKey = queryKeyFor(player);
        meta.generation = root.fetchGeneration;
        meta.position = currentPosition();
        meta.isPlaying = !!player.isPlaying;
        publish(Object.assign(emptyState("loading", "正在获取歌词"), meta));
        const payload = JSON.stringify({title: meta.title, artist: meta.artist, album: meta.album, duration: meta.duration, localDir: root.localDir});
        const request = requestComponent.createObject(root, {meta: meta});
        root.activeRequest = request;
        fetchTimeout.restart();
        request.exec(["python3", root.scriptPath, payload]);
    }

    Component {
        id: requestComponent
        Process {
            id: worker
            property var meta
            stdout: StdioCollector { id: output }
            stderr: StdioCollector { id: errors }
            onExited: exitCode => {
                if (root.activeRequest === worker) {
                    root.activeRequest = null;
                    fetchTimeout.stop();
                    if (errors.text.trim())
                        console.warn("desktopLyrics:", errors.text.trim());
                    root.handleResponse(output.text, exitCode, worker.meta);
                }
                worker.destroy();
            }
        }
    }

    Timer {
        id: fetchTimeout
        interval: 10000
        repeat: false
        onTriggered: {
            const request = root.activeRequest;
            if (!request)
                return;
            const meta = request.meta;
            root.handleResponse(JSON.stringify({ok: false, error: "歌词查询超时"}), 0, meta);
            root.cancelRequest();
        }
    }

    function scheduleRefresh(force) {
        const key = queryKeyFor(root.spotifyPlayer);
        if (!force && key === root.lastQueryKey)
            return;
        root.cancelRequest();
        root.lastQueryKey = "";
        if (!root.enabled || !root.spotifyPlayer) {
            trackDebounce.stop();
            root.refreshTrack();
            return;
        }
        publish(emptyState("loading", "等待曲目信息"));
        trackDebounce.restart();
    }

    function refreshTrack() {
        if (!root.enabled) {
            publish(emptyState("disabled", "歌词部件已关闭"));
            return;
        }
        const player = root.spotifyPlayer;
        if (!player) {
            publish(emptyState("idle", "Spotify 没有正在播放的音乐"));
            return;
        }
        root.lastQueryKey = queryKeyFor(player);
        fetchLyrics(player);
    }

    Timer {
        id: trackDebounce
        interval: 180
        onTriggered: root.refreshTrack()
    }

    onEnabledChanged: scheduleRefresh(true)
    onLocalDirChanged: scheduleRefresh(true)
    onOffsetMsChanged: tick()

    function tick() {
        const current = lyricsState.value;
        if (!current || (current.status !== "ready" && current.status !== "instrumental"))
            return;
        const next = applyPosition(current);
        if (next.currentIndex !== current.currentIndex || next.currentLine !== current.currentLine || next.isPlaying !== current.isPlaying)
            publish(next);
        else if (Math.abs((next.position || 0) - (current.position || 0)) >= 0.25)
            publish(next);
    }

    // Only the selected Spotify session can invalidate lyrics. Global active
    // player and stable metadata signals also change for browser playback.

    Connections {
        target: root.spotifyPlayer
        ignoreUnknownSignals: true
        function onMetadataChanged() {
            root.scheduleRefresh(false);
        }
        function onLengthChanged() {
            root.scheduleRefresh(false);
        }
        function onIsPlayingChanged() {
            root.tick();
        }
        function onPositionChanged() {
            root.tick();
        }
        function onPlaybackStateChanged() {
            root.tick();
        }
    }


    Timer {
        interval: 200
        running: root.enabled && !!root.spotifyPlayer
        repeat: true
        onTriggered: root.tick()
    }

    Component.onCompleted: root.scheduleRefresh(true)
}
