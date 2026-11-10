import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Onglet Contrôles de la santé (Task 19) : les contrôles repris de bazzite-health, refaits une fois par jour par le
// relevé (controles.json) : image, Flatpak, runtimes, téléchargements, caches et journal, /boot.
ColumnLayout {
    id: onglet

    required property var page      // la page Santé : ses données et ses formats

    objectName: "sante-onglet-controles"
    spacing: Style.gouttiere

    Carte {
        id: carteControles

        readonly property var c: onglet.page.controles
        readonly property var lignes: [onglet.page.ligneImage(c), onglet.page.ligneFlatpak(c), onglet.page.ligneRuntimes(c),
                                       onglet.page.ligneTelechargements(c), onglet.page.ligneCaches(c), onglet.page.ligneBoot(c)]

        objectName: "carte-controles"
        Layout.fillWidth: true
        visible: c !== null
        titre: "Contrôles"
        teinte: onglet.page.teinteDe(lignes)

        Controls.Label {
            objectName: "controles-date"
            Layout.fillWidth: true
            text: "Vérifié le " + onglet.page.jourHeure(carteControles.c?.date)
            color: Style.texteAttenue
            wrapMode: Text.WordWrap
        }
        LigneControle {
            nom: "controle-image"
            libelle: "Image système"
            ligne: carteControles.lignes[0]
        }
        LigneControle {
            nom: "controle-flatpak"
            libelle: "Applications Flatpak"
            ligne: carteControles.lignes[1]
        }
        LigneControle {
            nom: "controle-runtimes"
            libelle: "Runtimes Flatpak"
            ligne: carteControles.lignes[2]
        }
        LigneControle {
            nom: "controle-telechargements"
            libelle: "Téléchargements"
            ligne: carteControles.lignes[3]
        }
        LigneControle {
            nom: "controle-caches"
            libelle: "Caches et journal"
            ligne: carteControles.lignes[4]
        }
        LigneControle {
            nom: "controle-boot"
            libelle: "Démarrage (/boot)"
            ligne: carteControles.lignes[5]
        }
    }
    EtatVide {
        objectName: "controles-vide"
        Layout.fillWidth: true
        visible: onglet.page.controles === null
        icone: "view-refresh"
        texte: "Contrôles pas encore faits."
        explication: "Ils passent avec le relevé horaire, une fois par jour."
    }
}
