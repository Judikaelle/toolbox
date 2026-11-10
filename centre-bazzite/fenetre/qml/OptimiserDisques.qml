import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Optimiser mes disques : les options A à D (stockage.optimiser), avec les vrais chiffres. Dans la vue d'ensemble de
// Stockage (Task 19), une ligne par option (lettre, titre, état écrit) ; un clic la déplie (une seule à la fois) pour son
// texte, ses applis et ses commandes. Health Hub ne lance jamais les commandes de l'option C : il les affiche, et
// « Copier les commandes » les met dans le presse-papiers.
Carte {
    id: section

    readonly property var optimiser: pont.stockage.optimiser ?? ({})
    readonly property var options: optimiser.options ?? []
    property string copiee: ""          // id de l'option dont les commandes viennent d'être copiées
    property string depliee: ""         // id de l'option dépliée ("" : toutes repliées)
    // Étroite (à côté du ménage) : l'état écrit passe sous le titre, qui garde ainsi sa place.
    readonly property bool etroite: width < Kirigami.Units.gridUnit * 26

    function etatBadge(etat) {
        switch (etat) {
        case "fait": return "ok";
        case "a_decider": return "attention";
        case "possible": return "info";
        default: return "neutre";
        }
    }

    objectName: "optimiser-section"
    visible: options.length > 0

    Kirigami.Heading {
        objectName: "optimiser-entete"
        level: 2
        font.pointSize: Style.tailleTitreCarte
        font.weight: Font.Bold
        text: "Optimiser mes disques"
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.espace(0.5)

        Repeater {
            model: section.options

            delegate: ColumnLayout {
                id: option

                required property var modelData
                readonly property string oid: modelData.id ?? ""
                readonly property bool aCommandes: (modelData.commandes ?? "") !== ""
                readonly property bool ouverte: section.depliee === oid

                Layout.fillWidth: true
                spacing: Style.espace(2)

                Controls.AbstractButton {
                    id: ligne

                    objectName: "optimiser-ligne-" + option.oid
                    Layout.fillWidth: true
                    hoverEnabled: true
                    topPadding: Style.espace(1)
                    bottomPadding: Style.espace(1)
                    leftPadding: Style.espace(1.5)
                    rightPadding: Style.espace(1.5)
                    Accessible.role: Accessible.Button
                    Accessible.name: "Option " + option.oid + " : " + (option.modelData.titre ?? "") + ", "
                                     + (option.modelData.badge ?? "") + (option.ouverte ? ". Replier." : ". Déplier.")
                    onClicked: section.depliee = option.ouverte ? "" : option.oid

                    contentItem: GridLayout {
                        columns: section.etroite ? 3 : 4
                        columnSpacing: Style.espace(2.5)
                        rowSpacing: Style.espace(1)

                        // La lettre de l'option, dans une pastille.
                        Rectangle {
                            Layout.row: 0
                            Layout.column: 0
                            Layout.rowSpan: section.etroite ? 2 : 1
                            Layout.alignment: Qt.AlignVCenter
                            implicitWidth: Kirigami.Units.iconSizes.smallMedium
                            implicitHeight: implicitWidth
                            radius: width / 2
                            color: Style.releve
                            border.width: 1
                            border.color: Style.ligne2

                            Controls.Label {
                                anchors.centerIn: parent
                                text: option.oid
                                font.weight: Font.Bold
                                font.pointSize: Style.tailleMeta
                            }
                        }
                        TexteAbrege {
                            objectName: "optimiser-titre-" + option.oid
                            Layout.row: 0
                            Layout.column: 1
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            text: option.modelData.titre ?? ""
                            font.weight: Font.DemiBold
                        }
                        Badge {
                            objectName: "optimiser-badge-" + option.oid
                            Layout.row: section.etroite ? 1 : 0
                            Layout.column: section.etroite ? 1 : 2
                            Layout.alignment: Qt.AlignLeft | Qt.AlignVCenter
                            texte: option.modelData.badge ?? ""
                            etat: section.etatBadge(option.modelData.etat)
                        }
                        Kirigami.Icon {
                            Layout.row: 0
                            Layout.column: section.etroite ? 2 : 3
                            Layout.rowSpan: section.etroite ? 2 : 1
                            Layout.alignment: Qt.AlignVCenter
                            implicitWidth: Kirigami.Units.iconSizes.small
                            implicitHeight: implicitWidth
                            source: option.ouverte ? "go-up-symbolic" : "go-down-symbolic"
                            color: ligne.hovered ? Style.texte : Style.texteDim
                        }
                    }
                    background: Rectangle {
                        radius: Style.rayonControle
                        color: ligne.hovered || ligne.down ? Style.releve : "transparent"
                        border.width: ligne.visualFocus ? 2 : 0
                        border.color: Style.accent

                        Behavior on color {
                            ColorAnimation { duration: Style.dureeSurvol }
                        }
                    }
                }

                // Le détail de l'option dépliée.
                ColumnLayout {
                    objectName: "optimiser-detail-" + option.oid
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.iconSizes.smallMedium + Style.espace(4)
                    Layout.bottomMargin: Style.espace(2)
                    visible: option.ouverte
                    spacing: Style.espace(2)

                    Controls.Label {
                        objectName: "optimiser-texte-" + option.oid
                        Layout.fillWidth: true
                        text: option.modelData.texte ?? ""
                        color: Style.texteAttenue
                        wrapMode: Text.WordWrap
                    }
                    // Option C : les applis Flatpak système, de la plus grosse à la plus petite.
                    Repeater {
                        model: option.modelData.applis ?? []

                        delegate: RowLayout {
                            id: appli

                            required property var modelData

                            objectName: "optimiser-appli-" + appli.modelData.id
                            Layout.fillWidth: true
                            spacing: Style.espace(3)

                            Controls.Label {
                                Layout.fillWidth: true
                                text: appli.modelData.nom
                                elide: Text.ElideRight
                            }
                            Controls.Label {
                                text: appli.modelData.taille
                                color: Style.texteAttenue
                            }
                        }
                    }
                    // Les commandes : une zone défilante à hauteur bornée ; « Copier les commandes » copie tout.
                    Controls.ScrollView {
                        id: zone

                        objectName: "optimiser-commandes-" + option.oid
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(texteCommandes.implicitHeight, Kirigami.Units.gridUnit * 10)
                        visible: option.aCommandes
                        clip: true
                        contentWidth: availableWidth

                        Controls.Label {
                            id: texteCommandes

                            objectName: "optimiser-commandes-texte-" + option.oid
                            width: zone.availableWidth
                            text: option.modelData.commandes ?? ""
                            textFormat: Text.PlainText
                            font.family: "monospace"
                            font.pointSize: Style.tailleMono
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        visible: option.aCommandes
                        spacing: Style.espace(2)

                        Bouton {
                            objectName: "optimiser-copier-" + option.oid
                            text: "Copier les commandes"
                            icon.name: "edit-copy"
                            onClicked: {
                                pont.copier(option.modelData.commandes);
                                section.copiee = option.oid;
                            }
                        }
                        Controls.Label {
                            objectName: "optimiser-copie-" + option.oid
                            Layout.fillWidth: true
                            visible: section.copiee === option.oid
                            text: "Commandes copiées. Colle-les dans un terminal."
                            color: Style.ok
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }

    Controls.Label {
        objectName: "optimiser-recommandation"
        Layout.fillWidth: true
        text: section.optimiser.recommandation ?? ""
        wrapMode: Text.WordWrap
    }
    Controls.Label {
        objectName: "optimiser-idee"
        Layout.fillWidth: true
        text: section.optimiser.idee ?? ""
        color: Style.texteAttenue
        font.pointSize: Style.tailleMeta
        wrapMode: Text.WordWrap
    }
}
