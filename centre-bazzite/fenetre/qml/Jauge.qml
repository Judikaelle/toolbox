import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Espace libre d'un volume : nom, barre de l'espace libre, Go libres ; si l'état n'est pas ok, il est écrit en dessous
// (sauf quand la ligne qui la porte l'écrit elle-même : badgeAlerte à faux, vue d'ensemble de Stockage).
ColumnLayout {
    id: jauge

    property string nom
    property real libreGo
    property real totalGo
    property string etat: "ok"      // ok | attention | echec
    property real largeurNom: Kirigami.Units.gridUnit * 4.5
    property bool badgeAlerte: true

    readonly property bool enAlerte: etat !== "ok"
    readonly property color teinte: etat === "echec" ? Style.echec
                                  : etat === "attention" ? Style.attention
                                  : Style.accent
    readonly property string libre: Number(libreGo).toLocaleString(Qt.locale("fr_FR"), "f", libreGo >= 100 ? 0 : 1)
                                    + " Go libres"
    readonly property real partLibre: totalGo > 0 ? Math.max(0, Math.min(libreGo / totalGo, 1)) : 0

    spacing: Style.espace(1)
    Accessible.role: Accessible.ProgressBar
    Accessible.name: nom + " : " + libre + (enAlerte ? ", peu d'espace libre" : "")

    RowLayout {
        Layout.fillWidth: true
        spacing: Style.espace(3)

        Controls.Label {
            Layout.preferredWidth: jauge.largeurNom
            text: jauge.nom
            elide: Text.ElideRight
        }
        Progression {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            valeur: jauge.partLibre
            teinte: jauge.teinte
        }
        Controls.Label {
            Layout.preferredWidth: Kirigami.Units.gridUnit * 6
            horizontalAlignment: Text.AlignRight
            text: jauge.libre
            color: jauge.enAlerte ? jauge.teinte : Style.texteAttenue
            font.features: ({ "tnum": 1 })
        }
    }

    Badge {
        Layout.leftMargin: jauge.largeurNom + Style.espace(3)
        visible: jauge.enAlerte && jauge.badgeAlerte
        texte: "Peu d'espace libre"
        etat: jauge.etat
    }
}
