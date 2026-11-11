import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Onglet Sécurité de la santé : quatre cartes en grille 2 × 2 (pare-feu, ports ouverts sur le réseau, démarrage
// automatique, dossiers temporaires), relevées par securite.py. Lecture seule : l'état d'une ligne est celui de son point
// securite:* (SantePage.etatDuPoint), jamais un seuil recalculé ici ; une mesure illisible vaut « Vérification impossible ».
ColumnLayout {
    id: onglet

    required property var page      // la page Santé : ses données et ses formats

    readonly property var s: page.securite
    // Côte à côte dès 40 unités de grille (comme Journal).
    readonly property bool deuxColonnes: width >= Kirigami.Units.gridUnit * 40

    readonly property var lignePareFeu: page.ligneParefeu(s)
    readonly property var lignesPorts: page.lignesPorts(s)            // null : illisible
    readonly property var ligneAutres: page.ligneAutresPorts(s)       // null : rien à grouper
    readonly property var lignesDemarrage: page.lignesDemarrage(s)    // null : illisible
    readonly property var ligneLd: page.ligneLdPreload(s)             // null : vide
    readonly property var ligneTemporaires: page.ligneTemporaires(s)
    readonly property var ligneCache: page.ligneCache(s)

    objectName: "sante-onglet-securite"
    spacing: Style.gouttiere

    GridLayout {
        id: grille

        // Tirée de la largeur de l'onglet : un maximum tiré de la grille la bloquerait.
        readonly property real largeurColonne: onglet.deuxColonnes ? (onglet.width - columnSpacing) / 2 : onglet.width

        Layout.fillWidth: true
        columns: onglet.deuxColonnes ? 2 : 1
        columnSpacing: Style.gouttiere
        rowSpacing: Style.gouttiere

        Carte {
            objectName: "securite-pare-feu"
            Layout.alignment: Qt.AlignTop
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: grille.largeurColonne
            Layout.maximumWidth: grille.largeurColonne
            titre: "Pare-feu"
            teinte: onglet.page.teinteDe([onglet.lignePareFeu])

            LigneControle {
                nom: "ligne-pare-feu"
                libelle: "Pare-feu (firewalld)"
                ligne: onglet.lignePareFeu
            }
        }
        Carte {
            readonly property var lignes: (onglet.lignesPorts ?? []).concat(onglet.ligneAutres ? [onglet.ligneAutres] : [])

            objectName: "securite-ports"
            Layout.alignment: Qt.AlignTop
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: grille.largeurColonne
            Layout.maximumWidth: grille.largeurColonne
            titre: "Ports ouverts sur le réseau"
            teinte: onglet.page.teinteDe(lignes)

            LigneControle {
                visible: onglet.lignesPorts === null
                nom: "ports-impossible"
                libelle: "Ports ouverts"
                ligne: onglet.page.impossible("La liste des ports à l'écoute n'a pas pu être lue.")
            }
            Repeater {
                model: onglet.lignesPorts ?? []

                delegate: LigneControle {
                    required property var modelData
                    required property int index

                    nom: "port-" + index
                    libelle: (onglet.s.ports.inconnus[index]?.prog ?? "")
                    ligne: modelData
                }
            }
            LigneControle {
                visible: onglet.lignesPorts !== null && onglet.lignesPorts.length === 0 && onglet.ligneAutres === null
                nom: "ports-aucun"
                libelle: "Ports ouverts"
                ligne: onglet.page.ligne("Aucun", "ok", "Aucun programme n'accepte de connexion du réseau.")
            }
            LigneControle {
                visible: onglet.ligneAutres !== null
                nom: "ports-autres"
                libelle: "Autres ports ouverts"
                ligne: onglet.ligneAutres ?? ({})
            }
        }
        Carte {
            readonly property var lignes: (onglet.lignesDemarrage ?? []).concat(onglet.ligneLd ? [onglet.ligneLd] : [])

            objectName: "securite-demarrage"
            Layout.alignment: Qt.AlignTop
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: grille.largeurColonne
            Layout.maximumWidth: grille.largeurColonne
            titre: "Démarrage automatique"
            teinte: onglet.page.teinteDe(lignes)

            LigneControle {
                visible: onglet.lignesDemarrage === null
                nom: "demarrage-impossible"
                libelle: "Fichiers de démarrage"
                ligne: onglet.page.impossible("Les fichiers de démarrage n'ont pas pu être lus.")
            }
            Repeater {
                model: onglet.lignesDemarrage ?? []

                delegate: LigneControle {
                    required property var modelData
                    required property int index

                    nom: "demarrage-" + index
                    libelle: onglet.page.nomDuFichier(onglet.s.demarrage.trouves[index]?.chemin ?? "")
                    ligne: modelData
                }
            }
            LigneControle {
                visible: onglet.lignesDemarrage !== null && onglet.lignesDemarrage.length === 0
                nom: "demarrage-ok"
                libelle: "Fichiers de démarrage"
                ligne: onglet.page.ligneDemarrageOk(onglet.s)
            }
            LigneControle {
                visible: onglet.ligneLd !== null
                nom: "demarrage-ld-preload"
                libelle: "Bibliothèque injectée (ld.so.preload)"
                ligne: onglet.ligneLd ?? ({})
            }
        }
        Carte {
            objectName: "securite-temporaires"
            Layout.alignment: Qt.AlignTop
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: grille.largeurColonne
            Layout.maximumWidth: grille.largeurColonne
            titre: "Dossiers temporaires"
            teinte: onglet.page.teinteDe([onglet.ligneTemporaires, onglet.ligneCache])

            LigneControle {
                nom: "ligne-temporaires"
                libelle: "Programmes dans /tmp, /var/tmp, /dev/shm"
                ligne: onglet.ligneTemporaires
            }
            LigneControle {
                nom: "ligne-cache"
                libelle: "Programmes dans ~/.cache"
                ligne: onglet.ligneCache
            }
        }
    }
}
