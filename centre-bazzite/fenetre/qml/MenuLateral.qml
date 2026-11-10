import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Menu latéral : déplié (icône, nom, compteur) ou en rail d'icônes. Il ne décide de rien : la page choisie
// et la largeur viennent de Main.qml, les compteurs et l'état global viennent du moteur (pont.etat).
Rectangle {
    id: menu

    property string page: "accueil"
    property bool deplie: true
    property bool activiteOuverte: false

    signal choisir(string nom)
    signal basculer()
    signal basculerActivite()

    readonly property var etat: pont.etat
    readonly property var compteurs: etat.compteurs ?? {}
    readonly property int tachesEnCours: (pont.taches ?? []).filter(t => t.statut === "en_cours").length
    readonly property bool bloque: applicationWindow().boutonsBloques
    // « Vérifier maintenant » reste occupé jusqu'au prochain changement de etat.genere (ou 3 minutes au plus).
    property bool verification: false
    property date maintenant: new Date()
    readonly property bool extinctionPrevue: applicationWindow().extinctionPrevue
    readonly property bool extinctionAnnulee: applicationWindow().extinctionAnnuleeIci
    readonly property var etatGlobal: Style.etatsGlobaux[etat.couleur] ?? null
    readonly property var entrees: [
        { "nom": "accueil", "texte": "Accueil", "icone": "go-home", "compteur": "" },
        { "nom": "majs", "texte": "Mises à jour", "icone": "view-refresh", "compteur": "majs" },
        { "nom": "sante", "texte": "Santé", "icone": "love", "compteur": "sante" },
        { "nom": "stockage", "texte": "Stockage", "icone": "drive-harddisk", "compteur": "stockage" },
        { "nom": "jeux", "texte": "Jeux", "icone": "applications-games", "compteur": "" }
    ]
    // Pas encore disponibles : grisées, sous l'intertitre « BIENTÔT ».
    readonly property var bientot: [
        { "nom": "demarrage", "texte": "Démarrage", "icone": "chronometer", "compteur": "" }
    ]

    function nombre(entree) {
        return entree.compteur === "" ? 0 : (compteurs[entree.compteur] ?? 0);
    }
    function derniereVerification() {
        return Style.derniereVerification(etat.genere, maintenant);
    }
    function nomAccessible(entree) {
        const n = nombre(entree);
        return n > 0 ? entree.texte + " : " + n + " à regarder" : entree.texte;
    }

    // Le moteur a écrit un nouvel état : la vérification est finie.
    readonly property string genere: etat.genere ?? ""
    onGenereChanged: verification = false
    Timer {
        // Horloge des libellés (« hier », heure de la dernière vérification).
        running: true
        repeat: true
        interval: 60000
        onTriggered: menu.maintenant = new Date()
    }
    Timer {
        running: menu.verification
        interval: 180000
        onTriggered: menu.verification = false
    }

    objectName: "menu-lateral"
    color: Style.fondMenu
    clip: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Style.espace(2)
        spacing: Style.espace(1)

        Controls.ToolButton {
            objectName: "menu-basculer"
            Layout.alignment: menu.deplie ? Qt.AlignRight : Qt.AlignHCenter
            icon.name: menu.deplie ? "sidebar-collapse-left" : "sidebar-expand-left"
            display: Controls.AbstractButton.IconOnly
            text: menu.deplie ? "Replier le menu" : "Déplier le menu"
            Accessible.name: text
            Controls.ToolTip.visible: hovered
            Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
            Controls.ToolTip.text: text
            onClicked: menu.basculer()
        }

        // Les entrées défilent quand la fenêtre est basse ; le pied, lui, reste fixe et entier.
        Flickable {
            id: defilement

            objectName: "menu-defilement"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 0
            contentWidth: width
            contentHeight: entreesColonne.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Controls.ScrollBar.vertical: Controls.ScrollBar {
                policy: Controls.ScrollBar.AsNeeded
            }

            ColumnLayout {
                id: entreesColonne

                width: defilement.width - (defilement.contentHeight > defilement.height ? Style.espace(2) : 0)
                spacing: Style.espace(1)

                Repeater {
                    model: menu.entrees
                    delegate: Entree {
                        required property var modelData

                        entree: modelData
                    }
                }

                Intertitre {
                    visible: menu.deplie
                    Layout.topMargin: Style.espace(3)
                    Layout.leftMargin: Style.espace(2)
                    text: "BIENTÔT"
                }
                Kirigami.Separator {
                    visible: !menu.deplie
                    color: Style.ligne
                    Layout.fillWidth: true
                    Layout.topMargin: Style.espace(2)
                    Layout.bottomMargin: Style.espace(1)
                }
                Repeater {
                    model: menu.bientot
                    delegate: Entree {
                        required property var modelData

                        entree: modelData
                        disponible: false
                    }
                }
            }
        }

        // --- Pied : l'état, la dernière vérification, « Vérifier maintenant », « Tout mettre à jour » ---
        Rectangle {
            Layout.fillWidth: true
            Layout.leftMargin: -Style.espace(2)
            Layout.rightMargin: -Style.espace(2)
            Layout.bottomMargin: Style.espace(1)
            implicitHeight: 1
            color: Style.ligne
        }
        Badge {
            objectName: "menu-etat"
            visible: menu.deplie && menu.etatGlobal !== null
            Layout.leftMargin: Style.espace(2)
            texte: menu.etatGlobal?.mot ?? ""
            etat: menu.etatGlobal?.badge ?? "neutre"
        }
        Controls.Label {
            objectName: "menu-verification"
            visible: menu.deplie
            Layout.fillWidth: true
            Layout.leftMargin: Style.espace(2)
            text: menu.derniereVerification()
            color: Style.texteAttenue
            font.pointSize: Style.tailleMeta
            wrapMode: Text.WordWrap
        }
        Controls.ToolButton {
            objectName: "menu-annuler-extinction"

            readonly property string infobulle: "Annuler l'extinction"

            visible: menu.extinctionPrevue && !menu.extinctionAnnulee
            Layout.fillWidth: menu.deplie
            Layout.alignment: Qt.AlignHCenter
            icon.name: "dialog-cancel"
            display: menu.deplie ? Controls.AbstractButton.TextBesideIcon : Controls.AbstractButton.IconOnly
            text: menu.deplie ? infobulle : ""
            Accessible.name: infobulle
            Controls.ToolTip.visible: hovered && !menu.deplie
            Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
            Controls.ToolTip.text: infobulle
            onClicked: applicationWindow().annulerExtinction()
        }
        Controls.ToolButton {
            objectName: "menu-verifier"

            readonly property bool occupe: menu.verification

            Layout.fillWidth: menu.deplie
            Layout.alignment: Qt.AlignHCenter
            enabled: !occupe
            icon.name: "view-refresh"
            display: menu.deplie ? Controls.AbstractButton.TextBesideIcon : Controls.AbstractButton.IconOnly
            text: occupe ? "Vérification…" : "Vérifier maintenant"
            Accessible.name: text
            Controls.ToolTip.visible: hovered && !menu.deplie
            Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
            Controls.ToolTip.text: text + " · " + menu.derniereVerification()
            onClicked: {
                menu.verification = true;
                pont.verifier();
            }
        }
        // Bascule du panneau Activité : le nombre de tâches en cours, en toutes lettres (déplié) ou en pastille (rail).
        // Déplié : le badge est à côté du bouton, jamais dessus ; en rail, la pastille est dans son coin.
        RowLayout {
            Layout.fillWidth: true
            spacing: Style.espace(1)

            Controls.ToolButton {
                id: activiteBouton

                objectName: "menu-activite"

                readonly property string infobulle: menu.tachesEnCours > 0
                    ? "Activité : " + menu.tachesEnCours + " en cours" : "Activité"

                Layout.fillWidth: true
                highlighted: menu.activiteOuverte
                icon.name: "view-list-details"
                display: menu.deplie ? Controls.AbstractButton.TextBesideIcon : Controls.AbstractButton.IconOnly
                text: menu.deplie ? "Activité" : ""
                Accessible.name: infobulle
                Controls.ToolTip.visible: hovered && !menu.deplie
                Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
                Controls.ToolTip.text: infobulle
                onClicked: menu.basculerActivite()
                Rectangle {
                    objectName: "menu-activite-pastille"
                    visible: !menu.deplie && menu.tachesEnCours > 0
                    // En rail : dans le coin haut droit du bouton, sans le dépasser.
                    x: parent.width - width - Style.espace(0.5)
                    y: Style.espace(0.5)
                    implicitWidth: Math.max(height, pastilleTexte.implicitWidth + Style.espace(2))
                    implicitHeight: pastilleTexte.implicitHeight + Style.espace(0.5)
                    width: implicitWidth
                    height: implicitHeight
                    radius: height / 2
                    color: Style.teinteFond(Style.accent)
                    border.width: 1
                    border.color: Style.teinteBordure(Style.accent)

                    Controls.Label {
                        id: pastilleTexte

                        anchors.centerIn: parent
                        text: String(menu.tachesEnCours)
                        color: Style.accent
                        font.weight: Font.DemiBold
                        font.pointSize: Style.tailleBadge
                    }
                }
            }
            Badge {
                objectName: "menu-activite-badge"
                visible: menu.deplie && menu.tachesEnCours > 0
                Layout.rightMargin: Style.espace(2)
                texte: menu.tachesEnCours + " en cours"
                etat: "en_cours"
            }
        }
        BoutonPrincipal {
            objectName: "menu-tout-mettre-a-jour"
            visible: menu.page !== "accueil"
            Layout.fillWidth: true
            enabled: !menu.bloque
            occupe: menu.bloque
            icon.name: "system-software-update"
            text: menu.deplie ? "Tout mettre à jour" : ""
            libelle: "Tout mettre à jour"
            raccourci: "Ctrl+U"
            leftPadding: menu.deplie ? Style.espace(4) : Style.espace(2)
            rightPadding: leftPadding
            Accessible.name: "Tout mettre à jour (Ctrl+U)"
            onClicked: applicationWindow().demanderMaj(false)
        }
    }

    // Une entrée du menu : icône et nom (déplié) ou icône seule avec compteur en surimpression (rail).
    component Entree: Item {
        id: entreeItem

        property var entree
        property bool disponible: true
        readonly property bool active: disponible && menu.page === entree.nom
        readonly property int nombre: menu.nombre(entree)

        objectName: "menu-" + entree.nom
        property string nomAccessible: disponible ? menu.nomAccessible(entree) : entree.texte + " (bientôt)"
        readonly property string infobulle: disponible ? menu.nomAccessible(entree) : entree.texte + " : bientôt"

        Layout.fillWidth: true
        implicitHeight: Style.espace(9)          // 36 px, comme une entrée de GitHub Hub

        Controls.AbstractButton {
            id: bouton

            objectName: "menu-bouton-" + entreeItem.entree.nom
            anchors.fill: parent
            enabled: entreeItem.disponible
            text: entreeItem.entree.texte
            activeFocusOnTab: true
            hoverEnabled: true
            Accessible.name: entreeItem.nomAccessible
            onClicked: menu.choisir(entreeItem.entree.nom)

            background: Rectangle {
                radius: Style.rayonEntree
                color: bouton.hovered && !entreeItem.active ? Style.carte : "transparent"
                gradient: entreeItem.active ? actif : undefined
                border.width: bouton.visualFocus ? 1 : 0
                border.color: Style.accent

                Gradient {
                    id: actif

                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Qt.alpha(Style.accent, 0.18) }
                    GradientStop { position: 1; color: Qt.alpha(Style.accent, 0.04) }
                }

                Rectangle {
                    visible: entreeItem.active
                    width: 2
                    height: parent.height - Style.espace(2)
                    anchors.verticalCenter: parent.verticalCenter
                    color: Style.accent
                }
            }
            contentItem: Item {
                Kirigami.Icon {
                    id: icone

                    x: menu.deplie ? Style.espace(3) : Math.round((parent.width - width) / 2)
                    anchors.verticalCenter: parent.verticalCenter
                    implicitWidth: Kirigami.Units.iconSizes.smallMedium
                    implicitHeight: Kirigami.Units.iconSizes.smallMedium
                    source: entreeItem.entree.icone
                    color: entreeItem.active ? Style.accent
                         : !entreeItem.disponible ? Style.texteDim
                         : bouton.hovered ? Style.texte : Style.texteAttenue
                }
                Controls.Label {
                    visible: menu.deplie
                    anchors.left: icone.right
                    anchors.leftMargin: Style.espace(2)
                    anchors.right: pilule.left
                    anchors.rightMargin: Style.espace(1)
                    anchors.verticalCenter: parent.verticalCenter
                    text: entreeItem.entree.texte
                    elide: Text.ElideRight
                    font.weight: entreeItem.active ? Font.DemiBold : Font.Normal
                    color: entreeItem.active || bouton.hovered ? Style.texte
                         : entreeItem.disponible ? Style.texteAttenue
                         : Style.texteDim
                }
                // Compteur : pilule « attention », masquée à 0 ; en rail, posée sur le coin de l'icône.
                Rectangle {
                    id: pilule

                    objectName: "compteur-" + entreeItem.entree.nom
                    property string texte: String(entreeItem.nombre)

                    visible: entreeItem.nombre > 0
                    x: menu.deplie ? parent.width - width - Style.espace(2) : icone.x + icone.width - width / 2
                    y: menu.deplie ? Math.round((parent.height - height) / 2) : icone.y - height / 3
                    implicitWidth: Math.max(height, nombreTexte.implicitWidth + Style.espace(2))
                    implicitHeight: nombreTexte.implicitHeight + Style.espace(0.5)
                    width: implicitWidth
                    height: implicitHeight
                    radius: height / 2
                    color: Qt.alpha(Style.attention, 0.16)

                    Controls.Label {
                        id: nombreTexte

                        anchors.centerIn: parent
                        text: pilule.texte
                        color: Style.attention
                        font.weight: Font.DemiBold
                        font.pointSize: Style.tailleBadge
                    }
                }
            }
        }

        HoverHandler {
            id: survol
        }
        Controls.ToolTip.visible: survol.hovered && (!menu.deplie || !disponible)
        Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
        Controls.ToolTip.text: infobulle
    }
}
