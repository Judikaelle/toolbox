import QtQuick
import org.kde.kirigami as Kirigami

// Barre de progression du widget : valeur de 0 à 1 ; négative = indéterminée (un segment qui balaie).
// Copie adaptée de fenetre/qml/Progression.qml (pas de singleton Style ici). Le widget garde le style de Plasma,
// sauf l'accent : l'émeraude de la fenêtre (Ruling V57), la claire (Style.accent) sur un thème Plasma sombre, la plus
// foncée (Style.accent2) sur un thème clair.
Rectangle {
    id: barre

    readonly property color accent: Kirigami.Theme.backgroundColor.hslLightness > 0.5 ? "#10b981" : "#34d399"
    property real valeur: 0
    property color teinte: accent

    readonly property bool indeterminee: valeur < 0

    implicitWidth: Kirigami.Units.gridUnit * 10
    implicitHeight: Kirigami.Units.smallSpacing * 2
    radius: height / 2
    color: Qt.alpha(Kirigami.Theme.textColor, 0.12)
    clip: true
    Accessible.role: Accessible.ProgressBar
    Accessible.name: indeterminee ? "En cours" : Math.round(valeur * 100) + " %"

    Rectangle {
        x: barre.indeterminee ? balayage.position * (barre.width + width) - width : 0
        width: barre.indeterminee ? barre.width * 0.3 : barre.width * Math.max(0, Math.min(barre.valeur, 1))
        height: parent.height
        radius: parent.radius
        color: barre.teinte

        Behavior on width {
            enabled: !barre.indeterminee
            NumberAnimation { duration: Kirigami.Units.longDuration; easing.type: Easing.OutCubic }
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
