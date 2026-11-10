import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import org.kde.kirigami as Kirigami
import "."

// Rien à montrer : cadre en pointillés autour d'une phrase et, si utile, d'une action.
Item {
    id: vide

    property string icone: "dialog-information"
    property string texte
    property string explication: ""
    property Kirigami.Action action: null

    implicitWidth: Kirigami.Units.gridUnit * 20
    implicitHeight: message.implicitHeight + 2 * Style.margeCarte

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            strokeWidth: 1
            strokeColor: Style.ligne2
            strokeStyle: ShapePath.DashLine
            dashPattern: [4, 4]
            fillColor: "transparent"
            startX: 0.5 + Style.rayonCarte
            startY: 0.5

            PathLine { x: vide.width - 0.5 - Style.rayonCarte; y: 0.5 }
            PathArc { x: vide.width - 0.5; y: 0.5 + Style.rayonCarte; radiusX: Style.rayonCarte; radiusY: Style.rayonCarte }
            PathLine { x: vide.width - 0.5; y: vide.height - 0.5 - Style.rayonCarte }
            PathArc { x: vide.width - 0.5 - Style.rayonCarte; y: vide.height - 0.5; radiusX: Style.rayonCarte; radiusY: Style.rayonCarte }
            PathLine { x: 0.5 + Style.rayonCarte; y: vide.height - 0.5 }
            PathArc { x: 0.5; y: vide.height - 0.5 - Style.rayonCarte; radiusX: Style.rayonCarte; radiusY: Style.rayonCarte }
            PathLine { x: 0.5; y: 0.5 + Style.rayonCarte }
            PathArc { x: 0.5 + Style.rayonCarte; y: 0.5; radiusX: Style.rayonCarte; radiusY: Style.rayonCarte }
        }
    }

    Kirigami.PlaceholderMessage {
        id: message

        anchors {
            left: parent.left
            right: parent.right
            verticalCenter: parent.verticalCenter
            margins: Style.margeCarte
        }
        icon.name: vide.icone
        text: vide.texte
        explanation: vide.explication
        helpfulAction: vide.action
    }
}
