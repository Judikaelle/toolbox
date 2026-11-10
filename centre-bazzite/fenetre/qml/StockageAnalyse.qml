import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Ce que l'analyse LinStat a trouvé sur un volume, dans l'onglet de ce volume : date et boutons « Analyser » et
// « Carte détaillée » en tête, puis catégories et plus gros dossiers, côte à côte quand la largeur le permet (Task 19).
// Aucun espace utilisé n'est montré comme jauge : seulement des tailles de contenu.
// Sans moteur (LinStat absent ou changé, spec §6.2), seul « Carte détaillée » reste, si la commande est connue.
ColumnLayout {
    id: analyse

    property var volume: ({})
    property var analyse_: null          // l'Analyse du moteur (stockage.analyses[chemin]) ou null
    property var tache: null             // la tâche « analyse:<chemin> » du panneau Activité, si elle existe
    property bool carteDisponible: false // la commande LinStat est connue
    property bool moteur: true           // le moteur de LinStat s'importe : l'analyse est possible

    readonly property bool enEchec: tache !== null && tache.statut === "echec"
    readonly property bool interrompue: tache !== null && tache.statut === "interrompu"
    readonly property string chemin: volume.chemin ?? ""
    readonly property bool enCours: tache !== null && tache.statut === "en_cours"
    readonly property bool analyserVisible: moteur && (analyse_ !== null || enCours)
    readonly property var categories: analyse_ ? (analyse_.categories ?? []) : []
    readonly property var dossiers: analyse_ ? (analyse_.dossiers ?? []) : []
    readonly property real plusGrosse: categories.reduce((m, c) => Math.max(m, c.octets ?? 0), 0)
    readonly property var mois: ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.",
                                 "nov.", "déc."]
    // Catégories | plus gros dossiers côte à côte dès 40 unités de grille (720 px) : c'est le cas à 1100 px de fenêtre
    // (environ 765 px pour l'analyse), pas à 800 px (environ 650 px), où elles s'empilent.
    readonly property bool deuxColonnes: width >= Kirigami.Units.gridUnit * 40

    function dateLisible(iso, duree) {
        const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(iso));
        if (!m)
            return "Analysé";
        const s = Number(duree ?? 0);
        const longueur = s >= 60 ? Math.round(s / 60) + " min" : Math.max(1, Math.round(s)) + " s";
        return "Analysé le " + Number(m[3]) + " " + mois[Number(m[2]) - 1] + " à " + Number(m[4]) + " h " + m[5]
            + " (" + longueur + ")";
    }

    objectName: "stockage-analyse-" + chemin
    Layout.fillWidth: true
    spacing: Style.espace(2)

    // En tête : la date de la dernière analyse, puis « Analyser » (celui de la ligne vide suffit quand le volume n'a
    // jamais été analysé) et « Carte détaillée », dès que la commande LinStat est connue : analysé ou non, moteur ou non.
    RowLayout {
        Layout.fillWidth: true
        visible: analyse.analyserVisible || analyse.carteDisponible || dateAnalyse.visible
        spacing: Style.espace(2)

        Controls.Label {
            id: dateAnalyse

            objectName: "analyse-date-" + analyse.chemin
            Layout.fillWidth: true
            visible: analyse.moteur && analyse.analyse_ !== null
            text: analyse.analyse_ ? analyse.dateLisible(analyse.analyse_.date, analyse.analyse_.duree_s) : ""
            color: Style.texteAttenue
            font.pointSize: Style.tailleMeta
            elide: Text.ElideRight
        }
        Item {
            Layout.fillWidth: true
            visible: !dateAnalyse.visible
        }
        Bouton {
            objectName: "analyse-analyser-" + analyse.chemin
            visible: analyse.analyserVisible
            text: "Analyser"
            icon.name: "view-refresh"
            enabled: !analyse.enCours
            onClicked: pont.analyser(analyse.chemin)
        }
        Bouton {
            objectName: "analyse-carte-" + analyse.chemin
            visible: analyse.carteDisponible
            text: "Carte détaillée"
            icon.name: "view-list-tree"
            onClicked: pont.carteDetaillee(analyse.chemin)
        }
    }

    // Pendant l'analyse : barre indéterminée, ce que la tâche a vu jusqu'ici, et « Arrêter » à côté.
    RowLayout {
        objectName: "analyse-en-cours-" + analyse.chemin
        Layout.fillWidth: true
        visible: analyse.moteur && analyse.enCours
        spacing: Style.espace(3)

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.espace(1)

            Progression {
                objectName: "analyse-progression-" + analyse.chemin
                Layout.fillWidth: true
                valeur: -1
            }
            Controls.Label {
                objectName: "analyse-detail-" + analyse.chemin
                Layout.fillWidth: true
                text: analyse.tache ? (analyse.tache.detail ?? "") : ""
                color: Style.texteAttenue
                font.pointSize: Style.tailleMeta
                wrapMode: Text.WordWrap
            }
        }
        // L'analyse s'arrête ; le bloc dit ensuite « Analyse arrêtée à ta demande. » (ligne d'interruption).
        Bouton {
            objectName: "analyse-arreter-" + analyse.chemin
            visible: analyse.enCours
            text: "Arrêter"
            icon.name: "media-playback-stop"
            onClicked: pont.arreterAnalyse()
        }
    }

    // La dernière analyse a échoué ou a été interrompue : on le dit, au-dessus de l'ancien résultat s'il y en a un.
    Controls.Label {
        objectName: "analyse-probleme-" + analyse.chemin
        Layout.fillWidth: true
        visible: analyse.moteur && (analyse.enEchec || analyse.interrompue)
        text: analyse.tache ? (analyse.tache.detail ?? "") : ""
        color: analyse.enEchec ? Style.echec : Style.attention
        font.pointSize: Style.tailleMeta
        wrapMode: Text.WordWrap
    }

    // Pas encore analysé : une ligne encadrée, pas un grand état vide.
    Rectangle {
        id: vide

        property string texte: "Pas encore analysé."

        objectName: "analyse-vide-" + analyse.chemin
        Layout.fillWidth: true
        visible: analyse.moteur && analyse.analyse_ === null && !analyse.enCours
        implicitHeight: ligneVide.implicitHeight + 2 * Style.espace(2)
        radius: Style.rayonControle
        color: "transparent"
        border.width: 1
        border.color: Style.ligne

        RowLayout {
            id: ligneVide

            anchors {
                left: parent.left
                right: parent.right
                verticalCenter: parent.verticalCenter
                margins: Style.espace(3)
            }
            spacing: Style.espace(3)

            Kirigami.Icon {
                source: "folder-search"
                implicitWidth: Kirigami.Units.iconSizes.smallMedium
                implicitHeight: Kirigami.Units.iconSizes.smallMedium
                color: Style.texteAttenue
            }
            Controls.Label {
                Layout.fillWidth: true
                text: vide.texte
                color: Style.texteAttenue
                elide: Text.ElideRight
            }
            Bouton {
                objectName: "analyse-vide-analyser-" + analyse.chemin
                text: "Analyser"
                icon.name: "view-refresh"
                onClicked: pont.analyser(analyse.chemin)
            }
        }
    }

    ColumnLayout {
        objectName: "analyse-resultat-" + analyse.chemin
        Layout.fillWidth: true
        visible: analyse.moteur && analyse.analyse_ !== null
        spacing: Style.espace(2)

        Controls.Label {
            objectName: "analyse-note-" + analyse.chemin
            visible: analyse.chemin === "/var"
            Layout.fillWidth: true
            text: "Seul ce que ton compte peut lire est compté : le dépôt système et les dossiers réservés à root restent hors de l'analyse."
            color: Style.texteAttenue
            font.pointSize: Style.tailleMeta
            wrapMode: Text.WordWrap
        }

        GridLayout {
            id: grille

            // Tirée de la largeur du bloc, pas de celle de la grille : un maximum tiré de la grille la bloquerait.
            readonly property real largeurColonne: analyse.deuxColonnes ? (analyse.width - columnSpacing) / 2 : analyse.width

            Layout.fillWidth: true
            columns: analyse.deuxColonnes ? 2 : 1
            columnSpacing: Style.gouttiere * 2
            rowSpacing: Style.gouttiere

            ColumnLayout {
                Layout.alignment: Qt.AlignTop
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: grille.largeurColonne
                Layout.maximumWidth: grille.largeurColonne
                spacing: Style.espace(1.5)

                Intertitre {
                    text: "Par catégorie"
                }
                Repeater {
                    model: analyse.categories

                    delegate: RowLayout {
                        id: ligneCategorie

                        required property var modelData
                        required property int index

                        Layout.fillWidth: true
                        spacing: Style.espace(3)

                        Controls.Label {
                            objectName: "analyse-categorie-nom-" + analyse.chemin + "-" + ligneCategorie.index
                            Layout.preferredWidth: Kirigami.Units.gridUnit * (analyse.deuxColonnes ? 9 : 10)
                            text: ligneCategorie.modelData.nom ?? ""
                            elide: Text.ElideRight
                        }
                        Progression {
                            objectName: "analyse-categorie-barre-" + analyse.chemin + "-" + ligneCategorie.index
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            valeur: analyse.plusGrosse > 0 ? (ligneCategorie.modelData.octets ?? 0) / analyse.plusGrosse : 0
                        }
                        Controls.Label {
                            objectName: "analyse-categorie-taille-" + analyse.chemin + "-" + ligneCategorie.index
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                            horizontalAlignment: Text.AlignRight
                            text: ligneCategorie.modelData.taille ?? ""
                            font.features: ({ "tnum": 1 })
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.alignment: Qt.AlignTop
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: grille.largeurColonne
                Layout.maximumWidth: grille.largeurColonne
                visible: analyse.dossiers.length > 0
                spacing: Style.espace(1.5)

                Intertitre {
                    text: "Plus gros dossiers"
                }
                Repeater {
                    model: analyse.dossiers

                    delegate: RowLayout {
                        id: ligneDossier

                        required property var modelData
                        required property int index

                        Layout.fillWidth: true
                        spacing: Style.espace(3)

                        Controls.Label {
                            objectName: "analyse-dossier-nom-" + analyse.chemin + "-" + ligneDossier.index
                            Layout.fillWidth: true
                            text: ligneDossier.modelData.nom ?? ""
                            elide: Text.ElideMiddle
                        }
                        Badge {
                            objectName: "analyse-dossier-categorie-" + analyse.chemin + "-" + ligneDossier.index
                            visible: texte !== ""
                            texte: ligneDossier.modelData.categorie ?? ""
                            point: false
                        }
                        Controls.Label {
                            objectName: "analyse-dossier-taille-" + analyse.chemin + "-" + ligneDossier.index
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 4
                            horizontalAlignment: Text.AlignRight
                            text: ligneDossier.modelData.taille ?? ""
                            font.features: ({ "tnum": 1 })
                        }
                    }
                }
            }
        }
    }
}
