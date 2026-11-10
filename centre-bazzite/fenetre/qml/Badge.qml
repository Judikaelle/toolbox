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
    // 0 : sur une ligne, sans limite (l'usage courant). Sinon, la largeur à ne pas dépasser : un texte plus long passe à
    // la ligne, et la pilule devient un cadre arrondi (UI-m7 : la phrase du mode jeu dans le bandeau d'accueil).
    property real largeurMax: 0

    readonly property color couleur: Style.couleurEtat(etat)
    readonly property real marges: Style.espace(4.5)

    // Pilule de GitHub Hub : 11,5 px demi-gras, 9 px de marge sur les côtés.
    implicitWidth: ligne.implicitWidth + marges
    implicitHeight: ligne.implicitHeight + Style.espace(1.5)
    radius: etiquette.lineCount > 1 ? Style.rayonControle : height / 2
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
            id: etiquette

            // Sans limite, le Label garde sa largeur naturelle ; avec, il ne dépasse pas la place laissée par le point.
            Layout.maximumWidth: badge.largeurMax > 0
                                 ? Math.max(0, badge.largeurMax - badge.marges - (badge.point ? Style.espace(3) : 0))
                                 : Number.POSITIVE_INFINITY
            text: badge.texte
            color: badge.couleur
            font.weight: Font.DemiBold
            font.pointSize: Style.tailleBadge
            wrapMode: badge.largeurMax > 0 ? Text.WordWrap : Text.NoWrap
        }
    }
}
