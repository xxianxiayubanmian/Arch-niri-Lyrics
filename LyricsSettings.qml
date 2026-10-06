import QtQuick
import qs.Common
import qs.Modules.Plugins
import qs.Widgets

PluginSettings {
    id: root
    pluginId: "desktopLyrics"

    ToggleSetting {
        settingKey: "enabled"
        label: "启用歌词"
        description: "仅跟随 Spotify，并在 niri 的 DMS 导航栏中显示歌词"
        defaultValue: true
    }


    ToggleSetting {
        settingKey: "showTranslation"
        label: "显示翻译"
        description: "在原文下方显示已提供的翻译；无翻译时只显示原文"
        defaultValue: true
    }

    ToggleSetting {
        settingKey: "showTrackInfo"
        label: "显示歌曲信息"
        defaultValue: true
    }

    SliderSetting {
        settingKey: "backgroundOpacity"
        label: "背景不透明度"
        defaultValue: 35
        minimum: 0
        maximum: 100
        unit: "%"
    }

    SliderSetting {
        settingKey: "offsetMs"
        label: "歌词偏移"
        description: "正值让歌词提前，负值让歌词延后"
        defaultValue: 0
        minimum: -2000
        maximum: 2000
        unit: "ms"
    }

    StringSetting {
        settingKey: "localDir"
        label: "本地歌词目录"
        description: "优先读取该目录下的 .lrc 或 .txt，文件名可用「歌手 - 歌名.lrc」"
        placeholder: "~/Music/Lyrics"
        defaultValue: ""
    }

    StyledText {
        width: parent.width
        wrapMode: Text.WordWrap
        color: Theme.surfaceVariantText
        font.pixelSize: Theme.fontSizeSmall
        text: "面向 Arch Linux 的 niri 桌面。仅跟随 Spotify，在 DMS 导航栏显示歌词；浏览器和其他播放器不会触发查询。歌曲元数据稳定后并行查询网易云、QQ 音乐和 LRCLIB，在最多 7.5 秒内优先等待带翻译的同步歌词。已有翻译缓存优先保留；无翻译缓存 15 分钟后可补查。中文歌词及翻译通过 OpenCC 显示为简体，不修改原文缓存；含日文假名或韩文的原歌词保留。"
    }
}
