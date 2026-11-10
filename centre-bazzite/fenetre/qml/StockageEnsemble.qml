import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// La vue d'ensemble de Stockage, d'un coup d'œil (Task 19) : pourquoi LinStat ne répond pas (s'il y a lieu), ce qui est à
// regarder, une ligne par volume (un clic ouvre son onglet), puis le ménage et l'optimisation des disques, côte à côte
// sur une fenêtre large. Les points mis en sourdine tiennent en une ligne, dépliable. Aucune analyse ici : elles vivent
// dans l'onglet de leur volume.
ColumnLayout {
    id: ensemble

    property var disques: []
    property string sansLinstat: ""

    signal ouvrir(string chemin)

    // Les points de volume, de ménage et de stockage mis en sourdine, avec « Signaler à nouveau ».
    readonly property var sourdines: (pont.etat.points ?? [])
        .filter(p => p.en_sourdine && /^(volume|menage|stockage):/.test(String(p.id)))
    property bool sourdinesDepliees: false
    // Ménage et optimisation côte à côte dès 40 unités de grille (720 px de contenu : fenêtre de 1100 px, menu déplié).
    readonly property bool deuxColonnes: width >= Kirigami.Units.gridUnit * 40

    objectName: "stockage-ensemble"
    spacing: Style.gouttiere

    // Sans moteur, le message dit pourquoi : LinStat absent, ou installé mais changé (sa carte reste ouvrable).
    Kirigami.InlineMessage {
        objectName: "stockage-sans-linstat"
        Layout.fillWidth: true
        visible: ensemble.sansLinstat !== ""
        type: Kirigami.MessageType.Information
        text: ensemble.sansLinstat
    }
    ARegarder {
        Layout.fillWidth: true
        rubrique: "stockage"
    }
    EtatVide {
        objectName: "stockage-vide"
        Layout.fillWidth: true
        visible: ensemble.disques.length === 0
        icone: "drive-harddisk"
        texte: "Disques pas encore relevés."
        explication: "Le relevé se fait à l'ouverture de cette page, puis toutes les heures."
    }

    Carte {
        objectName: "stockage-disques"
        Layout.fillWidth: true
        visible: ensemble.disques.length > 0

        Repeater {
            model: ensemble.disques

            delegate: ColumnLayout {
                id: rang

                required property var modelData
                required property int index

                Layout.fillWidth: true
                spacing: Style.espace(2)

                Kirigami.Separator {
                    Layout.fillWidth: true
                    visible: rang.index > 0
                    color: Style.ligne
                }
                StockageDisque {
                    Layout.fillWidth: true
                    disque: rang.modelData
                    onOuvrir: chemin => ensemble.ouvrir(chemin)
                }
            }
        }
    }

    // Ménage un peu plus large que l'optimisation : ses lignes portent un bouton. Les largeurs viennent de celle de la
    // vue (remplir, minimum nul) : une largeur préférée seule deviendrait aussi la largeur minimale.
    GridLayout {
        id: grille

        readonly property bool deux: ensemble.deuxColonnes && menage.visible && optimiser.visible
        readonly property real largeurUtile: ensemble.width - columnSpacing

        Layout.fillWidth: true
        visible: menage.visible || optimiser.visible
        columns: deux ? 2 : 1
        columnSpacing: Style.gouttiere
        rowSpacing: Style.gouttiere

        MenageSection {
            id: menage

            Layout.alignment: Qt.AlignTop
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: grille.deux ? grille.largeurUtile * 0.55 : -1
            Layout.maximumWidth: grille.deux ? grille.largeurUtile * 0.55 : Number.POSITIVE_INFINITY
        }
        OptimiserDisques {
            id: optimiser

            Layout.alignment: Qt.AlignTop
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: grille.deux ? grille.largeurUtile * 0.45 : -1
            Layout.maximumWidth: grille.deux ? grille.largeurUtile * 0.45 : Number.POSITIVE_INFINITY
        }
    }

    // Les sourdines repliées en une ligne ; dépliées, chacune avec « Signaler à nouveau ».
    ColumnLayout {
        objectName: "stockage-sourdines"
        Layout.fillWidth: true
        visible: ensemble.sourdines.length > 0
        spacing: Style.espace(1)

        Bouton {
            objectName: "stockage-sourdines-bouton"
            flat: true
            text: ensemble.sourdines.length + (ensemble.sourdines.length > 1 ? " points en sourdine" : " point en sourdine")
            icon.name: ensemble.sourdinesDepliees ? "go-up-symbolic" : "go-down-symbolic"
            Accessible.name: text + (ensemble.sourdinesDepliees ? ", replier" : ", déplier")
            onClicked: ensemble.sourdinesDepliees = !ensemble.sourdinesDepliees
        }
        Repeater {
            model: ensemble.sourdines

            delegate: RowLayout {
                id: ligne

                required property var modelData

                objectName: "sourdine-" + modelData.id
                Layout.fillWidth: true
                Layout.leftMargin: Style.espace(3.5)
                visible: ensemble.sourdinesDepliees
                spacing: Kirigami.Units.largeSpacing

                Controls.Label {
                    objectName: "sourdine-titre-" + ligne.modelData.id
                    Layout.fillWidth: true
                    text: ligne.modelData.titre + " (ne plus signalé)"
                    color: Style.texteAttenue
                    wrapMode: Text.WordWrap
                }
                Bouton {
                    objectName: "sourdine-bouton-" + ligne.modelData.id
                    flat: true
                    text: "Signaler à nouveau"
                    icon.name: "notifications"
                    onClicked: pont.sansSourdine(ligne.modelData.id)
                }
            }
        }
    }
}
