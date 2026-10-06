import QtQuick
import qs.Common
import qs.Modules.Plugins
import qs.Widgets

DesktopPluginComponent {
    id: root

    minWidth: 280
    minHeight: 120

    readonly property var globalLyricsSettings: SettingsData.pluginSettings[pluginId] || {}
    readonly property real backgroundOpacity: (pluginData.backgroundOpacity !== undefined ? pluginData.backgroundOpacity : (globalLyricsSettings.backgroundOpacity !== undefined ? globalLyricsSettings.backgroundOpacity : 35)) / 100
    readonly property bool showTrackInfo: pluginData.showTrackInfo !== undefined ? pluginData.showTrackInfo : (globalLyricsSettings.showTrackInfo !== undefined ? globalLyricsSettings.showTrackInfo : true)
    readonly property bool showTranslation: pluginData.showTranslation !== undefined ? pluginData.showTranslation : (globalLyricsSettings.showTranslation !== undefined ? globalLyricsSettings.showTranslation : true)
    readonly property bool lyricsEnabled: globalLyricsSettings.enabled !== undefined ? globalLyricsSettings.enabled : true

    PluginGlobalVar {
        id: lyricsState
        varName: "lyricsState"
        defaultValue: ({
            "status": "idle",
            "message": "等待歌词",
            "title": "",
            "artist": "",
            "currentLine": "",
            "currentTranslation": "",
            "isPlaying": false
        })
    }

    readonly property var state: lyricsState.value || {}
    readonly property string status: state.status || "idle"
    readonly property string currentLine: state.currentLine || ""
    readonly property string currentTranslation: state.currentTranslation || ""
    readonly property string message: state.message || ""
    readonly property string title: state.title || ""
    readonly property string artist: state.artist || ""

    Rectangle {
        anchors.fill: parent
        radius: Theme.cornerRadius
        color: Theme.surfaceContainer
        opacity: root.backgroundOpacity
    }

    Column {
        anchors.fill: parent
        anchors.margins: Theme.spacingM
        spacing: Theme.spacingS

        StyledText {
            id: trackInfo
            visible: root.lyricsEnabled && root.status !== "disabled" && root.showTrackInfo && (root.title.length > 0 || root.artist.length > 0)
            width: parent.width
            text: root.artist ? (root.artist + "  ·  " + root.title) : root.title
            color: Theme.surfaceVariantText
            font.pixelSize: Theme.fontSizeSmall
            elide: Text.ElideRight
        }

        Item {
            id: lyricArea
            width: parent.width
            height: Math.max(0, parent.height - (trackInfo.visible ? trackInfo.height + parent.spacing : 0))
            clip: true

            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.spacingXS

                StyledText {
                    id: originalLine
                    width: parent.width
                    height: Math.min(implicitHeight, Math.max(0, lyricArea.height * (translationLine.visible ? 0.4 : 1) - (translationLine.visible ? parent.spacing : 0)))
                    clip: true
                    text: {
                        if (root.status === "disabled" || !root.lyricsEnabled)
                            return "";
                        if (root.status === "ready")
                            return root.currentLine;
                        if (root.status === "loading")
                            return "正在获取歌词";
                        if (root.status === "instrumental")
                            return "纯音乐";
                        if (root.message)
                            return root.message;
                        return "暂无歌词";
                    }
                    color: Theme.surfaceVariantText
                    font.pixelSize: Math.max(Theme.fontSizeSmall, root.height * 0.11)
                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                    elide: Text.ElideRight
                    horizontalAlignment: Text.AlignHCenter
                    opacity: 0.92
                }

                StyledText {
                    id: translationLine
                    visible: root.lyricsEnabled && root.showTranslation && root.status === "ready" && root.currentTranslation.length > 0
                    width: parent.width
                    height: Math.min(implicitHeight, Math.max(0, lyricArea.height - originalLine.height - parent.spacing))
                    clip: true
                    text: root.currentTranslation
                    color: Theme.surfaceText
                    font.pixelSize: Math.max(Theme.fontSizeLarge, root.height * 0.18)
                    font.weight: Font.DemiBold
                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                    elide: Text.ElideRight
                    horizontalAlignment: Text.AlignHCenter
                }

            }
        }
    }
}
