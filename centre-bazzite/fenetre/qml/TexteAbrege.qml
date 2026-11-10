import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Une ligne de texte qui s'abrège (« … ») quand la place manque ; le texte entier reste dans son infobulle.
Controls.Label {
    id: texte

    elide: Text.ElideRight
    maximumLineCount: 1
    textFormat: Text.PlainText

    HoverHandler {
        id: survol
    }
    Controls.ToolTip.visible: survol.hovered && texte.truncated
    Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
    Controls.ToolTip.text: texte.text
}
