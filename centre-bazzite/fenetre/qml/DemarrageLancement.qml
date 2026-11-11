import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// L'onglet « Au lancement » : ce qui démarre avec la session. Tes applis, tes services et minuteurs et ceux de Health
// Hub se règlent (une confirmation, puis « demarrage regler » : la CLI revérifie tout, republie demarrage.json, que le
// pont relit ; la page ne fait rien d'autre). Ce qu'active Bazzite et les essentiels du bureau sont en lecture seule,
// dans deux sections repliées. Les deux premières sections défilent dans une zone bornée à l'écran.
// Pendant qu'une commande tourne, sa ligne dit « En cours… » (le pont la tient occupée) ; sa phrase, réussite, échec ou
// refus, s'affiche ensuite en haut de l'onglet, jusqu'au relevé suivant (I-4).
ColumnLayout {
    id: onglet

    required property var page      // la page Démarrage : ses données

    readonly property var entrees: onglet.page.demarrage.lancement?.entrees ?? []
    readonly property int ignorees: onglet.page.demarrage.lancement?.ignorees ?? 0
    readonly property var reglables: entrees.filter(e => e.groupe === "toi" || e.groupe === "healthhub")
    readonly property var applis: reglables.filter(e => e.type === "appli")
    readonly property var unites: reglables.filter(e => e.type !== "appli")
    readonly property var bazzite: entrees.filter(e => e.groupe === "bazzite")
    readonly property var essentiel: entrees.filter(e => e.groupe === "essentiel")
    // L'entrée dont la confirmation est ouverte, telle qu'elle était à l'ouverture.
    property var ouverte: null
    // Vrai dès que la confirmation ouverte a lancé sa commande : une seule par ouverture (A-3).
    property bool confirme: false
    // Le retour de la dernière bascule ou remise (CLI), et ce qui l'identifie pour la croix « fermer ».
    readonly property var retour: onglet.page.demarrage.retour ?? null
    readonly property string cleRetour: retour ? JSON.stringify(retour) : ""

    objectName: "demarrage-lancement"
    spacing: Style.gouttiere

    // Les mots de la confirmation, selon ce que c'est (appli, minuteur, service ou socket) et le sens de la bascule.
    function genre(e) {
        return e.type === "appli" ? "appli" : e.type === "minuteur" ? "minuteur" : "service";
    }
    function titreConfirmation(e) {
        if (!e)
            return "";
        const nom = "« " + (e.nom ?? "") + " »";
        const g = genre(e);
        if (g === "appli")
            return e.actif ? "Ne plus lancer " + nom + " à l'ouverture de session ?" : "Lancer " + nom + " à l'ouverture de session ?";
        if (g === "minuteur")
            return e.actif ? "Arrêter le minuteur " + nom + " ?" : "Remettre en route le minuteur " + nom + " ?";
        return e.actif ? "Ne plus démarrer " + nom + " avec ta session ?" : "Démarrer " + nom + " avec ta session ?";
    }
    function texteConfirmation(e) {
        if (!e)
            return "";
        const g = genre(e);
        if (g === "appli")
            return e.actif ? "Elle ne se lancera plus à ta prochaine ouverture de session. Si elle tourne déjà, elle reste ouverte. Tu pourras la remettre d'un clic."
                           : "Elle se lancera à ta prochaine ouverture de session.";
        if (g === "minuteur")
            return e.actif ? "Il ne se déclenchera plus, même après un redémarrage. Tu pourras le remettre d'un clic."
                           : "Il se déclenchera de nouveau, dès maintenant.";
        return e.actif ? "Il ne démarrera plus à ta prochaine ouverture de session. S'il tourne déjà, il continue jusque-là. Tu pourras le remettre d'un clic."
                       : "Il démarrera à ta prochaine ouverture de session.";
    }
    function ouvrir(e) {
        ouverte = e;
        confirme = false;
        dialogue.open();
    }
    function confirmer() {
        if (!ouverte || confirme)
            return;
        confirme = true;
        pont.reglerDemarrage(ouverte.id, !ouverte.actif);
        dialogue.close();
    }
    function occupee(e) {
        return pont.demarrageOccupes.includes(e.id);
    }
    // demarrage.json est réécrit (la CLI, le relevé) : si l'entrée du dialogue a changé ou disparu, on ferme sans rien lancer.
    onEntreesChanged: {
        if (ouverte === null)
            return;
        const e = entrees.find(x => x.id === ouverte.id);
        if (!e || e.actif !== ouverte.actif)
            dialogue.close();
    }

    // Une section repliable, lecture seule : l'intertitre avec le compte, un clic le déplie.
    component SectionRepliee: ColumnLayout {
        id: bloc

        required property string cle
        required property string titre
        required property var elements
        property bool ouverte: false

        objectName: "section-" + cle + "-bloc"
        Layout.fillWidth: true
        spacing: Style.espace(2)

        Controls.AbstractButton {
            objectName: "section-" + bloc.cle
            Layout.fillWidth: true
            implicitHeight: Math.max(entete.implicitHeight, Kirigami.Units.gridUnit * 1.5)
            property bool ouverte: bloc.ouverte
            Accessible.name: bloc.titre + " · " + bloc.elements.length
            Accessible.role: Accessible.Button
            onClicked: bloc.ouverte = !bloc.ouverte

            contentItem: RowLayout {
                id: entete

                spacing: Style.espace(2)

                Kirigami.Icon {
                    source: bloc.ouverte ? "arrow-down" : "arrow-right"
                    color: Style.texteDim
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: implicitWidth
                }
                Intertitre {
                    objectName: "section-" + bloc.cle + "-titre"
                    Layout.fillWidth: true
                    text: bloc.titre + " · " + bloc.elements.length
                }
            }
        }
        Repeater {
            model: bloc.ouverte ? bloc.elements : []

            delegate: DemarrageLigne {
                required property var modelData

                entree: modelData
                section: bloc.cle
            }
        }
    }

    // La phrase de la CLI : positive si l'action a réussi, avertissement pour un échec ou un refus. La croix de
    // Kirigami la cache (visible = false) : on retient laquelle, et seul un nouveau retour revient.
    Loader {
        id: chargeurRetour

        Layout.fillWidth: true
        active: onglet.cleRetour !== "" && onglet.cleRetour !== onglet.page.retourFerme
        visible: active
        sourceComponent: Component {
            Kirigami.InlineMessage {
                objectName: "lancement-retour"
                width: chargeurRetour.width
                visible: true           // caché par défaut dans Kirigami
                type: (onglet.retour?.code ?? 1) === 0 ? Kirigami.MessageType.Positive : Kirigami.MessageType.Warning
                text: onglet.retour?.phrase ?? ""
                showCloseButton: true
                onVisibleChanged: {
                    if (!visible && chargeurRetour.visible)
                        onglet.page.retourFerme = onglet.cleRetour;
                }
            }
        }
    }

    Carte {
        id: carte

        objectName: "lancement-carte"
        Layout.fillWidth: true

        Controls.Label {
            objectName: "lancement-aucun"
            Layout.fillWidth: true
            visible: onglet.reglables.length === 0
            text: "Rien ne démarre avec ta session pour l'instant."
            color: Style.texteAttenue
        }
        Flickable {
            id: liste

            objectName: "lancement-liste"
            Layout.fillWidth: true
            visible: onglet.reglables.length > 0
            // Bornée au reste de l'écran : les deux sections repliées et la phrase d'en bas gardent leur place.
            Layout.preferredHeight: Math.min(contentHeight, Math.max(Kirigami.Units.gridUnit * 6,
                onglet.page.hauteurOnglet - carte.y - carte.decalageContenu - liste.y - Style.margeCarte
                - bas.hauteurReplie - (phrase.visible ? phrase.implicitHeight + onglet.spacing : 0) - onglet.spacing))
            contentWidth: width
            contentHeight: lignes.implicitHeight
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            Controls.ScrollBar.vertical: Controls.ScrollBar {
                policy: Controls.ScrollBar.AsNeeded
            }

            ColumnLayout {
                id: lignes

                width: liste.width - (liste.contentHeight > liste.height ? Style.espace(4) : 0)
                spacing: Style.espace(2)

                Intertitre {
                    objectName: "section-appli-titre"
                    text: "Applis au démarrage de la session"
                }
                Controls.Label {
                    Layout.fillWidth: true
                    visible: onglet.applis.length === 0
                    text: "Aucune."
                    color: Style.texteAttenue
                }
                Repeater {
                    model: onglet.applis

                    delegate: ColumnLayout {
                        required property var modelData
                        required property int index

                        Layout.fillWidth: true
                        spacing: Style.espace(1.5)

                        Kirigami.Separator {
                            Layout.fillWidth: true
                            visible: index > 0
                            color: Style.ligne
                        }
                        DemarrageLigne {
                            entree: modelData
                            section: "appli"
                            occupee: onglet.occupee(modelData)
                            onBasculer: e => onglet.ouvrir(e)
                            onRemettre: id => pont.remettreDemarrage(id)
                        }
                    }
                }
                Intertitre {
                    objectName: "section-unites-titre"
                    Layout.topMargin: Style.espace(2)
                    text: "Tes services et minuteurs"
                }
                // systemd qui ne répond pas laisse la section vide : on le dit, plutôt que « Aucun. ».
                Controls.Label {
                    objectName: "unites-aucun"
                    Layout.fillWidth: true
                    visible: onglet.unites.length === 0
                    text: onglet.page.demarrage.lancement?.illisible
                          ? "Illisibles pour l'instant : systemd ne répond pas. Le prochain relevé réessaiera." : "Aucun."
                    color: Style.texteAttenue
                    wrapMode: Text.WordWrap
                }
                Repeater {
                    model: onglet.unites

                    delegate: ColumnLayout {
                        required property var modelData
                        required property int index

                        Layout.fillWidth: true
                        spacing: Style.espace(1.5)

                        Kirigami.Separator {
                            Layout.fillWidth: true
                            visible: index > 0
                            color: Style.ligne
                        }
                        DemarrageLigne {
                            entree: modelData
                            section: "unites"
                            occupee: onglet.occupee(modelData)
                            onBasculer: e => onglet.ouvrir(e)
                            onRemettre: id => pont.remettreDemarrage(id)
                        }
                    }
                }
            }
        }
    }

    Carte {
        id: bas

        objectName: "lancement-bas"
        Layout.fillWidth: true
        // Sa hauteur repliée : la liste du haut la garde en réserve, qu'elle soit dépliée ou non.
        readonly property real hauteurReplie: 2 * Style.margeCarte + 2 * Kirigami.Units.gridUnit * 1.5 + Style.espace(2)

        SectionRepliee {
            cle: "bazzite"
            titre: "Activés par Bazzite (lecture seule)"
            elements: onglet.bazzite
        }
        SectionRepliee {
            cle: "essentiel"
            titre: "Essentiels du bureau (verrouillés)"
            elements: onglet.essentiel
        }
    }
    Controls.Label {
        id: phrase

        objectName: "lancement-ignorees"
        Layout.fillWidth: true
        visible: onglet.ignorees > 0
        text: onglet.ignorees > 1
              ? onglet.ignorees + " entrées prévues pour d'autres bureaux ou des programmes absents ne sont pas montrées."
              : "1 entrée prévue pour un autre bureau ou un programme absent n'est pas montrée."
        color: Style.texteDim
        font.pointSize: Style.tailleMeta
        wrapMode: Text.WordWrap
    }

    // La confirmation : ce qui va changer, puis le choix. Seul « Désactiver » / « Activer » appelle la CLI.
    Dialogue {
        id: dialogue

        objectName: "confirmation-demarrage"
        title: onglet.titreConfirmation(onglet.ouverte)
        subtitle: onglet.texteConfirmation(onglet.ouverte)
        standardButtons: Kirigami.Dialog.NoButton
        preferredWidth: Kirigami.Units.gridUnit * 28
        onClosed: onglet.ouverte = null

        ColumnLayout {
            Layout.fillWidth: true
            Layout.topMargin: Style.espace(2)
            spacing: Style.espace(2)

            Kirigami.InlineMessage {
                id: avertissement

                objectName: "confirmation-avertissement"
                Layout.fillWidth: true
                visible: !!onglet.ouverte?.avertissement
                type: Kirigami.MessageType.Warning
                text: onglet.ouverte?.avertissement ?? ""
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: Style.espace(2)

                Item {
                    Layout.fillWidth: true
                }
                Bouton {
                    id: annuler

                    objectName: "confirmation-annuler"
                    text: "Annuler"
                    icon.name: "dialog-cancel"
                    onClicked: dialogue.close()
                }
                Bouton {
                    id: confirmer

                    objectName: "confirmation-valider"
                    enabled: !onglet.confirme
                    text: onglet.ouverte?.actif ? "Désactiver" : "Activer"
                    onClicked: onglet.confirmer()
                }
            }
        }
    }
}
