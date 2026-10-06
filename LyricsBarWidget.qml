import QtQuick
import qs.Common
import qs.Modules.Plugins
import qs.Widgets

PluginComponent {
    id: root

    layerNamespacePlugin: "desktop-lyrics"

    PluginGlobalVar {
        id: lyricsState
        varName: "lyricsState"
        defaultValue: ({
            "status": "idle",
            "message": "暂无歌词",
            "title": "",
            "artist": "",
            "currentLine": "",
            "currentTranslation": "",
            "lines": []
        })
    }

    readonly property var state: lyricsState.value || {}
    readonly property string status: state.status || "idle"
    readonly property bool lyricsEnabled: pluginData.enabled !== undefined ? pluginData.enabled : true
    readonly property bool showTranslation: pluginData.showTranslation !== undefined ? pluginData.showTranslation : true
    readonly property string currentLine: !lyricsEnabled || status === "disabled" ? "" : (status === "ready" ? (state.currentLine || "") : (state.currentLine || state.message || "暂无歌词"))
    readonly property string currentTranslation: lyricsEnabled && status === "ready" ? (state.currentTranslation || "") : ""
    readonly property string title: lyricsEnabled && status !== "disabled" ? (state.title || "") : ""
    readonly property string artist: lyricsEnabled && status !== "disabled" ? (state.artist || "") : ""
    readonly property real maxBarWidth: {
        const screenWidth = parentScreen && parentScreen.width ? parentScreen.width : 1920;
        return Math.max(420, Math.min(980, screenWidth * 0.46));
    }

    horizontalBarPill: Component {
        Column {
            id: barLyrics
            spacing: 1
            clip: true
            width: Math.min(root.maxBarWidth, Math.max(originalMetrics.width, translationMetrics.width, 180))

            TextMetrics {
                id: originalMetrics
                text: root.currentLine
                font.pixelSize: Math.max(11, Theme.fontSizeSmall)
                font.family: originalLine.font.family
            }

            TextMetrics {
                id: translationMetrics
                text: translationLine.visible ? root.currentTranslation : ""
                font.pixelSize: Theme.fontSizeMedium
                font.family: translationLine.font.family
            }

            StyledText {
                id: originalLine
                width: parent.width
                text: root.currentLine
                color: Theme.surfaceVariantText
                font.pixelSize: Math.max(11, Theme.fontSizeSmall)
                wrapMode: Text.NoWrap
                elide: Text.ElideRight
                maximumLineCount: 1
                opacity: 0.9
            }

            StyledText {
                id: translationLine
                visible: root.showTranslation && root.currentTranslation.length > 0
                width: parent.width
                text: root.currentTranslation
                color: Theme.surfaceText
                font.pixelSize: Theme.fontSizeMedium
                wrapMode: Text.NoWrap
                elide: Text.ElideRight
                maximumLineCount: 1
            }
        }
    }

    verticalBarPill: Component {
        Column {
            width: parent ? parent.widgetThickness : implicitWidth
            spacing: 2

            StyledText {
                width: parent.width
                text: root.currentLine
                color: Theme.surfaceVariantText
                font.pixelSize: Math.max(10, Theme.fontSizeSmall - 1)
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
                opacity: 0.9
            }

            StyledText {
                visible: root.showTranslation && root.currentTranslation.length > 0
                width: parent.width
                text: root.currentTranslation
                color: Theme.surfaceText
                font.pixelSize: Theme.fontSizeMedium
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }

    popoutWidth: 420
    popoutHeight: 320
    popoutContent: Component {
        PopoutComponent {
            headerText: root.title || "歌词"
            detailsText: root.artist
            showCloseButton: true

            ListView {
                width: parent.width
                height: 240
                clip: true
                spacing: Theme.spacingXS
                model: root.lyricsEnabled && root.status !== "disabled" ? (root.state.lines || []) : []
                currentIndex: state.currentIndex !== undefined && state.currentIndex !== null ? state.currentIndex : -1
                highlightMoveDuration: 180

                delegate: Column {
                    required property var modelData
                    required property int index
                    width: ListView.view.width
                    spacing: 2

                    StyledText {
                        width: parent.width
                        text: modelData.displayText !== undefined ? modelData.displayText : modelData.text || ""
                        wrapMode: Text.WordWrap
                        color: index === (root.state.currentIndex !== undefined && root.state.currentIndex !== null ? root.state.currentIndex : -1) ? Theme.primary : Theme.surfaceText
                        font.weight: index === (root.state.currentIndex !== undefined && root.state.currentIndex !== null ? root.state.currentIndex : -1) ? Font.DemiBold : Font.Normal
                        opacity: index === (root.state.currentIndex !== undefined && root.state.currentIndex !== null ? root.state.currentIndex : -1) ? 1 : 0.72
                    }

                    StyledText {
                        visible: root.showTranslation && !!(modelData.translation)
                        width: parent.width
                        text: modelData.displayTranslation !== undefined ? modelData.displayTranslation : modelData.translation || ""
                        wrapMode: Text.WordWrap
                        color: Theme.surfaceVariantText
                        font.pixelSize: Theme.fontSizeSmall
                        opacity: 0.85
                    }
                }
            }
        }
    }
}
