import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import QtQuick.Shapes
import org.kde.kirigami as Kirigami
import "."

// Carte de GitHub Hub : fond de carte, bordure fine, rayon 14, marge de 18. Une teinte non transparente ajoute un
// liseré de 3 px en haut. « halo » en fait le bandeau d'accueil : rayon 18, halos de l'accent, bordure de l'accent.
Rectangle {
    id: carte

    property color teinte: "transparent"
    property string titre: ""
    property bool halo: false
    default property alias contenu: interieur.data

    readonly property bool teintee: teinte.a > 0 && !halo
    // Où commence le contenu dans la carte (marge, titre et son espacement) : une liste bornée au reste de l'écran
    // en déduit la place qui lui revient.
    readonly property real decalageContenu: Style.margeCarte + interieur.y

    implicitWidth: colonne.implicitWidth + 2 * Style.margeCarte
    implicitHeight: colonne.implicitHeight + 2 * Style.margeCarte
    radius: halo ? Style.rayonBandeau : Style.rayonCarte
    color: Style.carte
    border.width: 1
    border.color: halo ? Qt.tint(Style.ligne, Style.teinteBordure(Style.accent)) : Style.ligne

    // Les halos du bandeau : l'accent à 22 % en haut à gauche, son départ à 14 % en haut à droite (ellipses).
    Shape {
        id: halos

        visible: carte.halo
        anchors.fill: parent
        anchors.margins: carte.border.width
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            strokeWidth: -1
            fillGradient: RadialGradient {
                centerX: 0
                centerY: 0
                centerRadius: halos.width * 0.72
                focalX: 0
                focalY: 0
                GradientStop { position: 0; color: Qt.alpha(Style.accent, 0.22) }
                GradientStop { position: 1; color: Qt.alpha(Style.accent, 0) }
            }
            fillTransform: PlanarTransform.fromScale(1, halos.height * 0.84 / Math.max(1, halos.width * 0.72))

            PathRectangle {
                width: halos.width
                height: halos.height
                radius: carte.radius - carte.border.width
            }
        }
        ShapePath {
            strokeWidth: -1
            fillGradient: RadialGradient {
                centerX: halos.width
                centerY: 0
                centerRadius: halos.width * 0.54
                focalX: halos.width
                focalY: 0
                GradientStop { position: 0; color: Qt.alpha(Style.accent2, 0.14) }
                GradientStop { position: 1; color: Qt.alpha(Style.accent2, 0) }
            }
            fillTransform: PlanarTransform.fromScale(1, halos.height * 0.72 / Math.max(1, halos.width * 0.54), halos.width, 0)

            PathRectangle {
                width: halos.width
                height: halos.height
                radius: carte.radius - carte.border.width
            }
        }
    }

    // Le liseré : 3 px sous la bordure du haut, coupé par l'arrondi des coins.
    Shape {
        id: lisere

        readonly property real r: carte.radius - carte.border.width
        readonly property real b: carte.border.width
        readonly property real h: Style.lisere
        // Abscisse où l'arrondi intérieur croise le bas du liseré.
        readonly property real dx: r - Math.sqrt(r * r - (r - h) * (r - h))

        visible: carte.teintee
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            strokeWidth: -1
            fillColor: carte.teinte
            startX: lisere.b + lisere.dx
            startY: lisere.b + lisere.h

            PathArc { x: lisere.b + lisere.r; y: lisere.b; radiusX: lisere.r; radiusY: lisere.r }
            PathLine { x: carte.width - lisere.b - lisere.r; y: lisere.b }
            PathArc { x: carte.width - lisere.b - lisere.dx; y: lisere.b + lisere.h; radiusX: lisere.r; radiusY: lisere.r }
            PathLine { x: lisere.b + lisere.dx; y: lisere.b + lisere.h }
        }
    }

    ColumnLayout {
        id: colonne

        anchors {
            fill: parent
            margins: Style.margeCarte
        }
        spacing: Style.espace(3)

        Controls.Label {
            Layout.fillWidth: true
            visible: carte.titre !== ""
            text: carte.titre
            font.weight: Font.Bold
            font.pointSize: Style.tailleTitreCarte
            elide: Text.ElideRight
        }
        ColumnLayout {
            id: interieur

            Layout.fillWidth: true
            spacing: Style.espace(3)
        }
    }
}
