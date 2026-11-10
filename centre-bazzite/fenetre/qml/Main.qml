import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// Fenêtre du Health Hub : le menu latéral à gauche, la page choisie à droite. Le lancement des mises à jour
// vit ici (confirmations, jeu, boutons bloqués) : l'accueil et le menu passent par le même chemin.
Kirigami.ApplicationWindow {
    id: fenetre

    // Fichier QML de chaque page du rail (« pageInitiale » vient du lanceur).
    readonly property var fichiers: ({
        "accueil": "AccueilPage.qml",
        "majs": "MisesAJourPage.qml",
        "sante": "SantePage.qml",
        "stockage": "StockagePage.qml",
        "jeux": "JeuxPage.qml"
    })
    property string page: pageInitiale
    // Onglet ouvert des pages Stockage, Santé et Jeux (Task 19) : quitter la page puis y revenir rouvre le même ; le
    // lanceur peut le choisir (--onglet, captures).
    property string ongletStockage: "ensemble"
    property string ongletSante: "resume"
    property string ongletJeux: "ensemble"
    // Le filtre de l'onglet Bibliothèques de Jeux : "" (toutes), "doublons", ou l'id d'une bibliothèque.
    property string filtreJeux: ""
    // « auto » : le menu se déplie si la place le permet ; « deplie » / « replie » : choix de l'utilisateur.
    property string menuChoisi: "auto"
    property bool activiteOuverte: false      // le panneau Activité réduit la place du contenu
    readonly property bool menuDeplie: menuChoisi === "deplie" || (menuChoisi === "auto"
        && fenetre.width - (activiteOuverte ? Style.largeurActivite : 0) >= Kirigami.Units.gridUnit * 52)

    // --- Panneau Activité : il s'ouvre seul sur un échec, et signale la fin d'une tâche suivie ---
    readonly property var taches: pont.taches
    readonly property date ouverture: new Date()
    property string tacheDepliee: ""
    property string derniereNotification: ""   // dernier message passif (lu par les tests)
    property var suivies: ({})                 // tâches vues « en cours » depuis l'ouverture de cette fenêtre
    property var echecsSignales: ({})

    function suivreTaches() {
        for (const t of taches) {
            if (t.statut === "en_cours") {
                suivies[t.id] = true;
            } else if (t.statut === "fini" && suivies[t.id]) {
                delete suivies[t.id];
                derniereNotification = "✔ " + t.titre + " : terminé";
                showPassiveNotification(derniereNotification);
            } else if (t.statut === "echec") {
                const fin = Style.dateDe(t.fin);
                const cle = t.id + "@" + t.fin;
                if (fin && fin > ouverture && !echecsSignales[cle]) {
                    echecsSignales[cle] = true;
                    delete suivies[t.id];
                    tacheDepliee = t.id;
                    activiteOuverte = true;
                }
            }
        }
    }
    onTachesChanged: suivreTaches()
    Component.onCompleted: suivreTaches()

    // --- Lancement des mises à jour ---
    readonly property var etat: pont.etat
    readonly property var enCours: etat.en_cours ?? null
    readonly property string jeu: etat.jeu ?? ""
    readonly property var extinction: etat.extinction ?? null
    // « Mettre à jour et éteindre » : l'extinction est prévue pendant toute la session, annulable à tout moment.
    readonly property bool extinctionPrevue: !!enCours?.eteindre || !!extinction?.a
    property string extinctionAnnulee: ""     // session (début) dont l'annulation de l'extinction est demandée
    readonly property bool extinctionAnnuleeIci: !!etat.extinction_annulee
        || (extinctionAnnulee !== "" && extinctionAnnulee === (enCours?.debut ?? extinction?.a ?? ""))
    property string majDemandee: ""           // "maj" ou "eteindre" : action en attente d'une réponse
    property bool lancement: false            // une mise à jour vient d'être demandée
    // Une session de Health Hub tourne (ou vient d'être demandée) : les boutons attendent sa fin. Pendant un
    // rattrapage de uupd seul, ils restent actifs : la session suit la mise à jour en cours puis fait le reste.
    readonly property bool boutonsBloques: !!enCours?.debut || lancement

    function annulerExtinction() {
        extinctionAnnulee = enCours?.debut ?? extinction?.a ?? "";
        pont.annulerExtinction();
    }
    // Un clic sur un bouton de mise à jour : confirmation de l'extinction d'abord, puis le jeu éventuel.
    function demanderMaj(eteindre) {
        if (boutonsBloques)
            return;
        if (eteindre)
            confirmationExtinction.open();
        else
            lancerMaj(false, false);
    }
    // Spec 7.3 : si un jeu tourne, proposer d'attendre la fin de la partie (la CLI refuse sans --meme-si-jeu).
    function lancerMaj(eteindre, memeSiJeu) {
        majDemandee = eteindre ? "eteindre" : "maj";
        if (!memeSiJeu && jeu !== "") {
            confirmationJeu.open();
            return;
        }
        lancement = true;
        if (eteindre)
            pont.mettreAJourEtEteindre(memeSiJeu);
        else
            pont.toutMettreAJour(memeSiJeu);
    }

    onEnCoursChanged: if (enCours?.debut) lancement = false
    // La CLI a refusé parce qu'un jeu a démarré depuis le dernier état : elle réécrit l'état avec le jeu.
    onJeuChanged: {
        if (lancement && jeu !== "" && !enCours?.debut) {
            lancement = false;
            confirmationJeu.open();
        }
    }

    Timer {
        // Sans session visible au bout de 30 s, le lancement est considéré comme terminé.
        running: fenetre.lancement
        interval: 30000
        onTriggered: fenetre.lancement = false
    }
    Dialogue {
        id: confirmationExtinction

        objectName: "confirmation-extinction"
        title: "Mettre à jour, puis éteindre ?"
        subtitle: "Ton PC s'éteindra à la fin de la mise à jour, après un compte à rebours de 60 s. Tu pourras annuler l'extinction à tout moment."
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                objectName: "action-extinction-lancer"
                text: "Mettre à jour et éteindre"
                icon.name: "system-shutdown"
                onTriggered: {
                    confirmationExtinction.close();
                    fenetre.lancerMaj(true, false);
                }
            },
            Kirigami.Action {
                objectName: "action-extinction-annuler"
                text: "Annuler"
                icon.name: "dialog-cancel"
                onTriggered: confirmationExtinction.close()
            }
        ]
    }
    Dialogue {
        id: confirmationJeu

        objectName: "confirmation-jeu"
        title: "Un jeu tourne (" + (fenetre.jeu || "inconnu") + ") : lancer quand même ?"
        subtitle: "La mise à jour peut ralentir ta partie. Tu peux aussi attendre la fin de la partie, puis relancer."
                  + (fenetre.majDemandee === "eteindre" ? " Ton PC ne s'éteindra pas tant qu'un jeu tourne." : "")
        standardButtons: Kirigami.Dialog.NoButton
        customFooterActions: [
            Kirigami.Action {
                objectName: "action-jeu-lancer"
                text: "Lancer quand même"
                icon.name: "system-software-update"
                onTriggered: {
                    confirmationJeu.close();
                    fenetre.lancerMaj(fenetre.majDemandee === "eteindre", true);
                }
            },
            Kirigami.Action {
                objectName: "action-jeu-attendre"
                text: "Attendre"
                icon.name: "chronometer"
                onTriggered: confirmationJeu.close()
            }
        ]
    }

    title: "Health Hub"
    width: 1100
    height: 720
    minimumWidth: Kirigami.Units.gridUnit * 40
    minimumHeight: Kirigami.Units.gridUnit * 26

    pageStack.globalToolBar.style: Kirigami.ApplicationHeaderStyle.None
    pageStack.initialPage: Kirigami.Page {
        padding: 0
        // La palette de Style posée à la racine : toujours sombre, accent émeraude, quel que soit le thème de Plasma.
        // Tout ce qui est dessous en hérite ; les dialogues et infobulles prennent la même par apparence.py.
        Kirigami.Theme.colorSet: Kirigami.Theme.Window
        Kirigami.Theme.inherit: false
        Kirigami.Theme.backgroundColor: Style.fond
        Kirigami.Theme.alternateBackgroundColor: Style.carte
        Kirigami.Theme.textColor: Style.texte
        Kirigami.Theme.disabledTextColor: Style.texteDim
        Kirigami.Theme.highlightColor: Style.accent
        Kirigami.Theme.highlightedTextColor: Style.texteSurAccent
        Kirigami.Theme.activeTextColor: Style.accent
        Kirigami.Theme.linkColor: Style.accent    // (pas visitedLinkColor : Kirigami l'écrit aussi dans textColor)
        Kirigami.Theme.positiveTextColor: Style.ok
        Kirigami.Theme.neutralTextColor: Style.attention
        Kirigami.Theme.negativeTextColor: Style.echec
        Kirigami.Theme.focusColor: Style.accent
        Kirigami.Theme.hoverColor: Style.accent

        RowLayout {
            anchors.fill: parent
            spacing: 0

            MenuLateral {
                Layout.fillHeight: true
                Layout.preferredWidth: fenetre.menuDeplie ? Style.largeurMenu : Style.largeurRail
                page: fenetre.page
                deplie: fenetre.menuDeplie
                onChoisir: nom => fenetre.page = nom
                activiteOuverte: fenetre.activiteOuverte
                onBasculer: fenetre.menuChoisi = fenetre.menuDeplie ? "replie" : "deplie"
                onBasculerActivite: fenetre.activiteOuverte = !fenetre.activiteOuverte

                Behavior on Layout.preferredWidth {
                    NumberAnimation {
                        duration: Style.dureePanneau
                        easing.type: Easing.OutCubic
                    }
                }
            }

            Kirigami.Separator {
                Layout.fillHeight: true
                color: Style.ligne
            }

            Loader {
                id: contenu

                Layout.fillWidth: true
                Layout.fillHeight: true
                source: Qt.resolvedUrl(fenetre.fichiers[fenetre.page] ?? fenetre.fichiers["accueil"])
            }

            Kirigami.Separator {
                visible: activite.visible
                Layout.fillHeight: true
                color: Style.ligne
            }

            ActivitePanneau {
                id: activite

                Layout.fillHeight: true
                Layout.preferredWidth: fenetre.activiteOuverte ? Style.largeurActivite : 0
                visible: Layout.preferredWidth > 0     // pas `width` : un élément invisible n'a pas de largeur
                depliee: fenetre.tacheDepliee
                onFermer: fenetre.activiteOuverte = false

                Behavior on Layout.preferredWidth {
                    NumberAnimation {
                        duration: Style.dureePanneau
                        easing.type: Easing.OutCubic
                    }
                }
            }
        }
    }

    Connections {
        target: contenu.item
        ignoreUnknownSignals: true

        function onOuvrirPage(nom) {
            fenetre.page = nom;
        }
    }
}
