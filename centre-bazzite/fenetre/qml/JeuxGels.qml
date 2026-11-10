import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// L'onglet Gels (D16, déplacé de la page Santé) : les captures les plus récentes de freeze-watch (gels détectés
// automatiquement) et de freeze-jeu (manuelles), chacune ouvrable ; « Ouvrir le dossier » montre toutes les autres.
// La liste défile dans sa propre zone, bornée au reste de l'écran.
ColumnLayout {
    id: onglet

    required property var page      // la page Jeux : ses données et ses formats

    readonly property var gels: page.gels
    readonly property var liste: gels.liste ?? []
    readonly property int nombre: gels.nombre ?? liste.length
    readonly property int automatiques: gels.automatiques ?? 0

    // « 21 sept. à 20 h 37 »
    function quand(iso) {
        const d = Style.dateDe(iso);
        return d ? page.jourCourt(iso) + " à " + Style.heure(d) : "Date inconnue";
    }
    // « 3 captures, dont 2 gels détectés automatiquement »
    function entete() {
        const debut = page.pluriel(nombre, "capture", "captures");
        if (automatiques === 0)
            return debut + (nombre > 1 ? ", toutes manuelles" : ", manuelle");
        return debut + ", dont " + page.pluriel(automatiques, "gel détecté automatiquement", "gels détectés automatiquement");
    }

    objectName: "jeux-gels"
    spacing: Style.gouttiere

    EtatVide {
        objectName: "jeux-vide"
        Layout.fillWidth: true
        visible: !onglet.page.releve
        icone: "applications-games"
        texte: onglet.page.texteVide
    }
    EtatVide {
        objectName: "gels-vide"
        Layout.fillWidth: true
        visible: onglet.page.releve && onglet.liste.length === 0
        icone: "checkmark"
        texte: "Aucun gel capturé."
    }

    Carte {
        id: carte

        objectName: "gels-carte"
        Layout.fillWidth: true
        visible: onglet.page.releve && onglet.liste.length > 0

        RowLayout {
            Layout.fillWidth: true
            spacing: Style.espace(3)

            Kirigami.Heading {
                objectName: "gels-entete"
                Layout.fillWidth: true
                level: 2
                font.pointSize: Style.tailleTitreCarte
                font.weight: Font.Bold
                text: onglet.entete()
                wrapMode: Text.WordWrap
            }
            Bouton {
                objectName: "gels-dossier"
                text: "Ouvrir le dossier"
                icon.name: "folder-open"
                onClicked: pont.ouvrirDossierGels()
            }
        }

        ListView {
            id: liste

            objectName: "liste-gels"
            Layout.fillWidth: true
            // Bornée au reste de l'écran (la page tient sur un écran) : la carte au-dessus, sa marge, puis sa marge du bas.
            Layout.preferredHeight: Math.min(contentHeight, Math.max(Kirigami.Units.gridUnit * 6,
                onglet.page.hauteurOnglet - carte.y - liste.y - 2 * Style.margeCarte))
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            model: onglet.liste
            Controls.ScrollBar.vertical: Controls.ScrollBar {
                policy: Controls.ScrollBar.AsNeeded
            }

            delegate: ColumnLayout {
                id: rang

                required property var modelData
                required property int index

                width: ListView.view.width - Style.espace(3)
                spacing: 0

                Kirigami.Separator {
                    Layout.fillWidth: true
                    visible: rang.index > 0
                    color: Style.ligne
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: Style.espace(1)
                    Layout.bottomMargin: Style.espace(1)
                    spacing: Style.espace(3)

                    Controls.Label {
                        objectName: "gel-date-" + rang.index
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 7
                        text: onglet.quand(rang.modelData.date)
                        font.features: ({ "tnum": 1 })
                    }
                    TexteAbrege {
                        objectName: "gel-jeu-" + rang.index
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 7
                        text: rang.modelData.jeu ?? ""
                        font.weight: Font.DemiBold
                    }
                    Badge {
                        objectName: "gel-badge-" + rang.index
                        texte: rang.modelData.automatique ? "Automatique" : "Manuelle"
                        etat: rang.modelData.automatique ? "info" : "neutre"
                    }
                    // Ce qui a déclenché la capture automatique, abrégé (le texte entier est dans l'infobulle).
                    TexteAbrege {
                        objectName: "gel-declencheur-" + rang.index
                        Layout.fillWidth: true
                        visible: text !== ""
                        text: rang.modelData.declencheur ?? ""
                        color: Style.texteAttenue
                        font.pointSize: Style.tailleMeta
                    }
                    Item {
                        Layout.fillWidth: true
                        visible: (rang.modelData.declencheur ?? "") === ""
                    }
                    Controls.Label {
                        objectName: "gel-taille-" + rang.index
                        text: rang.modelData.taille ?? ""
                        color: Style.texteAttenue
                        font.features: ({ "tnum": 1 })
                    }
                    Bouton {
                        objectName: "gel-ouvrir-" + rang.index
                        flat: true
                        text: "Ouvrir"
                        icon.name: "document-open"
                        onClicked: pont.ouvrirGel(String(rang.modelData.fichier ?? "").split("/").pop())
                    }
                }
            }
        }
    }
}
