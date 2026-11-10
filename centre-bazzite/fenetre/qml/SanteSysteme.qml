import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Onglet Système de la santé (Task 19) : les services en échec, puis le bilan de la semaine en détail (spec 7.5 : module
// hebdo, notification du lundi), chaque point avec son niveau écrit.
ColumnLayout {
    id: onglet

    required property var page      // la page Santé : ses données et ses formats

    readonly property var services: page.sante.services_en_echec ?? null
    readonly property int nombreServices: services ? services.length : 0
    readonly property var bilan: page.sante.bilan_hebdo ?? null

    objectName: "sante-onglet-systeme"
    spacing: Style.gouttiere

    Carte {
        objectName: "systeme-services"
        Layout.fillWidth: true
        titre: "Services"

        RowLayout {
            Layout.fillWidth: true
            spacing: Style.espace(3)

            Badge {
                visible: onglet.services !== null
                texte: onglet.nombreServices > 0 ? "Échec" : "OK"
                etat: onglet.nombreServices > 0 ? "echec" : "ok"
            }
            Controls.Label {
                Layout.fillWidth: true
                text: onglet.services === null ? "Services pas encore vérifiés."
                      : onglet.nombreServices > 0
                        ? onglet.nombreServices + (onglet.nombreServices > 1 ? " services en échec : " : " service en échec : ") + onglet.services.join(", ")
                        : "Aucun service en échec."
                color: onglet.services === null ? Style.texteAttenue : Style.texte
                wrapMode: Text.WordWrap
            }
        }
    }

    Carte {
        objectName: "systeme-bilan"
        Layout.fillWidth: true

        Controls.Label {
            objectName: "bilan-titre"
            Layout.fillWidth: true
            text: onglet.bilan ? "Bilan de la semaine du " + onglet.page.jourCourt(onglet.bilan.semaine?.du ?? onglet.bilan.date)
                               : "Pas encore de bilan hebdomadaire."
            font.weight: Font.Bold
            font.pointSize: Style.tailleTitreCarte
            wrapMode: Text.WordWrap
        }
        Controls.Label {
            objectName: "bilan-synthese"
            Layout.fillWidth: true
            visible: onglet.bilan?.semaine !== undefined
            text: onglet.page.syntheseSemaine(onglet.bilan?.semaine)
            color: Style.texteAttenue
            wrapMode: Text.WordWrap
        }
        Repeater {
            model: onglet.bilan?.points ?? []

            delegate: RowLayout {
                id: resultat

                required property var modelData
                readonly property var niveau: onglet.page.niveaux[modelData.niveau]
                                              ?? { "mot": String(modelData.niveau ?? "?"), "etat": "neutre" }
                readonly property string details: onglet.page.detailsBilan(modelData.details)

                Layout.fillWidth: true
                spacing: Kirigami.Units.largeSpacing

                Item {
                    Layout.alignment: Qt.AlignTop
                    Layout.preferredWidth: Kirigami.Units.gridUnit * 6
                    implicitHeight: pastille.implicitHeight

                    Badge {
                        id: pastille

                        texte: resultat.niveau.mot
                        etat: resultat.niveau.etat
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    Controls.Label {
                        Layout.fillWidth: true
                        text: String(resultat.modelData.titre ?? "")
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                    }
                    Controls.Label {
                        Layout.fillWidth: true
                        visible: resultat.details !== ""
                        text: resultat.details
                        textFormat: Text.PlainText
                        color: Style.texteAttenue
                        font.family: Kirigami.Theme.fixedWidthFont.family
                        font.pointSize: Style.tailleMono
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }
        }
    }
}
