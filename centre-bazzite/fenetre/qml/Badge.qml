import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Pilule d'état : toujours un mot, la couleur ne porte jamais seule l'information.
Rectangle {
    id: badge

    property string texte
    property string etat: "neutre"   // ok | attention | echec | info | en_cours | neutre
    property bool point: true

    readonly property color couleur: Style.couleurEtat(etat)

    // Pilule de GitHub Hub : 11,5 px demi-gras, 9 px de marge sur les côtés.
    implicitWidth: ligne.implicitWidth + Style.espace(4.5)
    implicitHeight: ligne.implicitHeight + Style.espace(1.5)
    radius: height / 2
    color: Style.teinteFond(couleur)
    border.width: 1
    border.color: Style.teinteBordure(couleur)
    Accessible.role: Accessible.StaticText
    Accessible.name: texte

    RowLayout {
        id: ligne

        anchors.centerIn: parent
        spacing: Style.espace(1.5)

        Rectangle {
            visible: badge.point
            implicitWidth: Style.espace(1.5)
            implicitHeight: implicitWidth
            radius: width / 2
            color: badge.couleur
        }
        Controls.Label {
            text: badge.texte
            color: badge.couleur
            font.weight: Font.DemiBold
            font.pointSize: Style.tailleBadge
        }
    }
}
