import QtQuick
import org.kde.kirigami as Kirigami
import "."

// Barre de progression de 4 px : valeur de 0 à 1 ; négative = indéterminée (un segment qui balaie). L'accent se
// remplit en dégradé émeraude ; une couleur d'état (attention, échec) reste pleine.
Rectangle {
    id: barre

    property real valeur: 0
    property color teinte: Style.accent

    readonly property bool indeterminee: valeur < 0
    readonly property bool degrade: Qt.colorEqual(teinte, Style.accent)

    implicitWidth: Kirigami.Units.gridUnit * 10
    implicitHeight: Style.epaisseurBarre
    radius: Style.rayonBarre
    color: Style.releve
    clip: true
    Accessible.role: Accessible.ProgressBar
    Accessible.name: indeterminee ? "En cours" : Math.round(valeur * 100) + " %"

    Rectangle {
        id: remplissage

        x: barre.indeterminee ? balayage.position * (barre.width + width) - width : 0
        width: barre.indeterminee ? barre.width * 0.3 : barre.width * Math.max(0, Math.min(barre.valeur, 1))
        height: parent.height
        radius: parent.radius
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: barre.degrade ? Style.accent2 : barre.teinte }
            GradientStop { position: 1; color: barre.teinte }
        }

        Behavior on width {
            enabled: !barre.indeterminee
            NumberAnimation { duration: Style.dureePanneau; easing.type: Easing.OutCubic }
        }
    }

    // Figé (segment visible à 35 %) si les animations sont coupées.
    QtObject {
        id: balayage

        property real position: Kirigami.Units.longDuration > 0 ? 0 : 0.35
    }
    NumberAnimation {
        target: balayage
        property: "position"
        from: 0
        to: 1
        duration: 1200
        loops: Animation.Infinite
        running: barre.indeterminee && barre.visible && Kirigami.Units.longDuration > 0
    }
}
