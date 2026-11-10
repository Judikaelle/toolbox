import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Rangée d'onglets de GitHub Hub (Task 19) : libellés 13 px demi-gras, l'onglet actif en texte plein souligné d'un filet
// de 2 px en accent, les autres atténués. Un onglet qui a quelque chose à dire porte une pastille de compte, ou un petit
// point de la couleur de son état ; le mot de cet état est dans son infobulle et sa description accessible (la couleur
// ne porte jamais seule l'information : le contenu de l'onglet l'écrit aussi). Trop étroite, la rangée défile à
// l'horizontale ; au clavier, Tab y entre, Gauche et Droite changent d'onglet.
Item {
    id: onglets

    property var modele: []          // [{ cle, libelle, etat?: "ok"|"attention"|"echec"|"info"|"en_cours"|"", compte?: int }]
    property string courant

    signal choisir(string cle)

    readonly property int indexCourant: modele.findIndex(o => o.cle === courant)
    readonly property var mots: ({ "attention": "Attention", "echec": "Échec", "info": "Info", "en_cours": "En cours" })

    // Gauche (-1) ou Droite (+1) : l'onglet voisin, sans faire le tour.
    function aller(pas) {
        if (modele.length === 0)
            return;
        const i = Math.max(0, Math.min(modele.length - 1, indexCourant + pas));
        if (i !== indexCourant)
            choisir(modele[i].cle);
    }
    // L'onglet courant reste dans la partie visible de la rangée.
    function montrerCourant() {
        const onglet = repetiteur.itemAt(indexCourant);
        if (!onglet)
            return;
        if (onglet.x < defilement.contentX)
            defilement.contentX = onglet.x;
        else if (onglet.x + onglet.width > defilement.contentX + defilement.width)
            defilement.contentX = onglet.x + onglet.width - defilement.width;
    }

    onIndexCourantChanged: Qt.callLater(montrerCourant)
    onWidthChanged: Qt.callLater(montrerCourant)

    implicitWidth: rangee.implicitWidth
    implicitHeight: rangee.implicitHeight
    activeFocusOnTab: true
    Accessible.role: Accessible.PageTabList
    Keys.onLeftPressed: aller(-1)
    Keys.onRightPressed: aller(1)

    // Le filet du bas, sous toute la rangée ; celui de l'onglet actif passe par-dessus.
    Rectangle {
        anchors {
            left: parent.left
            right: parent.right
            bottom: parent.bottom
        }
        height: 1
        color: Style.ligne
    }

    Flickable {
        id: defilement

        anchors.fill: parent
        contentWidth: rangee.implicitWidth
        contentHeight: height
        flickableDirection: Flickable.HorizontalFlick
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentWidth > width
        clip: interactive

        Behavior on contentX {
            NumberAnimation {
                duration: Style.dureeSurvol
                easing.type: Easing.OutCubic
            }
        }

        // La molette fait défiler la rangée quand elle déborde.
        WheelHandler {
            enabled: defilement.interactive
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            onWheel: evenement => {
                const delta = evenement.angleDelta.y !== 0 ? evenement.angleDelta.y : evenement.angleDelta.x;
                defilement.contentX = Math.max(0, Math.min(defilement.contentWidth - defilement.width,
                                                           defilement.contentX - delta / 2));
            }
        }

        Row {
            id: rangee

            Repeater {
                id: repetiteur

                model: onglets.modele

                delegate: Controls.AbstractButton {
                    id: onglet

                    required property var modelData
                    required property int index
                    readonly property string cle: modelData.cle ?? ""
                    readonly property bool actif: cle === onglets.courant
                    readonly property string etat: modelData.etat ?? ""
                    readonly property int compte: modelData.compte ?? 0
                    readonly property string motEtat: onglets.mots[etat] ?? ""
                    readonly property string nomAccessible: text + ", onglet " + (index + 1) + " sur " + onglets.modele.length

                    objectName: "onglet-" + cle
                    text: modelData.libelle ?? ""
                    focusPolicy: Qt.NoFocus        // le clavier reste sur la rangée (Gauche, Droite)
                    hoverEnabled: true
                    topPadding: Style.espace(2)
                    bottomPadding: Style.espace(2.5)
                    leftPadding: Style.espace(3)
                    rightPadding: Style.espace(3)
                    Accessible.role: Accessible.PageTab
                    Accessible.name: nomAccessible
                    Accessible.description: motEtat
                    Accessible.selected: actif
                    Controls.ToolTip.visible: hovered && motEtat !== ""
                    Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
                    Controls.ToolTip.text: motEtat
                    onClicked: onglets.choisir(cle)

                    contentItem: Row {
                        spacing: Style.espace(1.5)

                        Controls.Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: onglet.text
                            color: onglet.actif || onglet.hovered ? Style.texte : Style.texteAttenue
                            font.pointSize: Style.tailleBouton
                            font.weight: Font.DemiBold

                            Behavior on color {
                                ColorAnimation { duration: Style.dureeSurvol }
                            }
                        }
                        // Pastille de compte : le nombre, dans la teinte de l'état.
                        Rectangle {
                            objectName: "compte-onglet-" + onglet.cle
                            anchors.verticalCenter: parent.verticalCenter
                            visible: onglet.compte > 0
                            implicitWidth: Math.max(implicitHeight, nombre.implicitWidth + Style.espace(2.5))
                            implicitHeight: nombre.implicitHeight + Style.espace(0.5)
                            radius: height / 2
                            color: Style.teinteFond(Style.couleurEtat(onglet.etat))
                            border.width: 1
                            border.color: Style.teinteBordure(Style.couleurEtat(onglet.etat))

                            Controls.Label {
                                id: nombre

                                anchors.centerIn: parent
                                text: onglet.compte
                                color: Style.couleurEtat(onglet.etat)
                                font.pointSize: Style.tailleBadge
                                font.weight: Font.DemiBold
                                font.features: ({ "tnum": 1 })
                            }
                        }
                        // Sinon, un petit point quand l'onglet a quelque chose à regarder.
                        Rectangle {
                            objectName: "point-onglet-" + onglet.cle
                            anchors.verticalCenter: parent.verticalCenter
                            visible: onglet.compte <= 0 && onglet.etat !== "" && onglet.etat !== "ok"
                            implicitWidth: Style.espace(1.5)
                            implicitHeight: implicitWidth
                            radius: width / 2
                            color: Style.couleurEtat(onglet.etat)
                        }
                    }

                    background: Item {
                        // Le focus clavier : un cadre en accent autour de l'onglet courant.
                        Rectangle {
                            anchors {
                                fill: parent
                                topMargin: Style.espace(0.5)
                                bottomMargin: Style.espace(1)
                            }
                            visible: onglets.activeFocus && onglet.actif
                            radius: Style.rayonControle
                            color: "transparent"
                            border.width: 2
                            border.color: Style.accent
                        }
                        Rectangle {
                            objectName: "filet-onglet-" + onglet.cle
                            x: onglet.leftPadding
                            y: parent.height - height
                            width: onglet.availableWidth
                            height: 2
                            radius: 1
                            visible: onglet.actif
                            color: Style.accent
                        }
                    }
                }
            }
        }
    }
}
