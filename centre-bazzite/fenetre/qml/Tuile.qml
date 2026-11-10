import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Une mesure en grand : icône, valeur, légende ; un badge écrit l'état s'il y en a un.
Carte {
    id: tuile

    property string icone
    property string valeur
    property string legende
    property string etat: ""            // "" (pas de badge) | ok | attention | echec | info | en_cours
    property string badgeTexte: ""      // vide : le mot de l'état

    readonly property var mots: ({
        "ok": "Tout va bien",
        "attention": "Attention",
        "echec": "Échec",
        "info": "Info",
        "en_cours": "En cours"
    })

    Accessible.role: Accessible.StaticText
    readonly property string motEtat: etat === "" ? "" : (badgeTexte !== "" ? badgeTexte : (mots[etat] ?? ""))

    Accessible.name: legende + " : " + valeur + (motEtat !== "" ? ", " + motEtat : "")

    RowLayout {
        Layout.fillWidth: true
        spacing: Style.espace(2)

        Kirigami.Icon {
            visible: tuile.icone !== ""
            source: tuile.icone
            implicitWidth: Kirigami.Units.iconSizes.smallMedium
            implicitHeight: implicitWidth
            color: Style.texteAttenue
        }
        Item {
            Layout.fillWidth: true
        }
        Badge {
            visible: tuile.etat !== ""
            etat: tuile.etat
            texte: tuile.motEtat
        }
    }
    Controls.Label {
        Layout.fillWidth: true
        text: tuile.valeur
        font.pointSize: Style.tailleChiffre
        font.weight: Font.Bold
        font.features: ({ "tnum": 1 })
        elide: Text.ElideRight
    }
    Controls.Label {
        Layout.fillWidth: true
        text: tuile.legende
        color: Style.texteAttenue
        font.pointSize: Style.tailleMeta
        elide: Text.ElideRight
    }
}
