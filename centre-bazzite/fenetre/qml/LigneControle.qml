import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Un contrôle de la santé : son nom et sa phrase de détail à gauche, son badge (toujours un mot) à droite.
RowLayout {
    id: ligneControle

    property string nom
    property string libelle
    property var ligne: ({})

    Layout.fillWidth: true
    spacing: Kirigami.Units.largeSpacing

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 0

        Controls.Label {
            objectName: ligneControle.nom + "-libelle"
            Layout.fillWidth: true
            text: ligneControle.libelle
            font.weight: Font.Medium
            wrapMode: Text.WordWrap
        }
        Controls.Label {
            objectName: ligneControle.nom + "-detail"
            Layout.fillWidth: true
            visible: text !== ""
            text: ligneControle.ligne.detail ?? ""
            textFormat: Text.PlainText
            color: Style.texteAttenue
            font.pointSize: Style.tailleMeta
            wrapMode: Text.Wrap
        }
    }
    Badge {
        objectName: ligneControle.nom
        Layout.alignment: Qt.AlignTop
        texte: ligneControle.ligne.texte ?? ""
        etat: ligneControle.ligne.etat ?? "neutre"
    }
}
