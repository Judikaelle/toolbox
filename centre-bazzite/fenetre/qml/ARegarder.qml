import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import "."

// « À regarder » en tête d'une page : les points de sa rubrique (champ « rubrique » d'etat.json, calculé par
// points.rubrique) que le compteur du menu compte — hors sourdine, hors information sauf « mise à jour disponible »,
// la règle de points.compteurs. Chaque point a son action et « Ne plus signaler », comme sur l'accueil ; redémarrer
// demande une confirmation et attend la fin d'une mise à jour en cours. Rien à regarder : la carte n'apparaît pas.
Carte {
    id: carte

    property string rubrique
    property int lignesTitre: 0               // transmis à PointLigne : titres abrégés au-delà de ce nombre de lignes
    property var masques: []                  // mis en sourdine depuis l'ouverture (la sourdine arrive au relevé)

    readonly property bool majEnCours: !!pont.etat.en_cours
    readonly property var liste: (pont.etat.points ?? []).filter(p => p.rubrique === rubrique && !p.en_sourdine
        && (p.gravite !== "info" || String(p.id).startsWith("maj:dispo:")) && !masques.includes(p.id))

    function estRedemarrage(point) {
        return String(point.id).startsWith("redemarrage:");
    }
    function agir(point) {
        if (estRedemarrage(point))
            confirmationRedemarrage.open();
        else
            pont.agir(point.id);
    }
    function nePlusSignaler(point) {
        masques = masques.concat([point.id]);
        pont.sourdine(point.id);
        applicationWindow().showPassiveNotification("« " + point.titre + " » ne sera plus signalé, sauf s'il empire.",
                                                     "long", "Annuler", () => {
            masques = masques.filter(id => id !== point.id);
            pont.sansSourdine(point.id);
        });
    }

    objectName: "a-regarder-" + rubrique
    visible: liste.length > 0
    titre: "À regarder"

    ColumnLayout {
        objectName: "a-regarder-liste-" + carte.rubrique
        Layout.fillWidth: true
        spacing: 0

        Repeater {
            model: carte.liste

            delegate: ColumnLayout {
                id: rang

                required property var modelData
                required property int index

                objectName: "a-regarder-ligne-" + modelData.id
                Layout.fillWidth: true
                spacing: 0

                Kirigami.Separator {
                    Layout.fillWidth: true
                    color: Style.ligne
                    visible: rang.index > 0
                }
                PointLigne {
                    Layout.fillWidth: true
                    Layout.topMargin: Style.espace(3)
                    Layout.bottomMargin: Style.espace(3)
                    point: rang.modelData
                    lignesTitre: carte.lignesTitre
                    // Redémarrer pendant une mise à jour la couperait : le bouton attend la fin.
                    actionPermise: !(carte.estRedemarrage(rang.modelData) && carte.majEnCours)
                    onAgir: carte.agir(rang.modelData)
                    onNePlusSignaler: carte.nePlusSignaler(rang.modelData)
                }
            }
        }

        Dialogue {
            id: confirmationRedemarrage

            title: "Redémarrer maintenant ?"
            subtitle: "Les applications ouvertes vont se fermer : enregistre ton travail avant."
            standardButtons: Kirigami.Dialog.NoButton
            customFooterActions: [
                Kirigami.Action {
                    text: "Redémarrer"
                    icon.name: "system-reboot"
                    onTriggered: {
                        confirmationRedemarrage.close();
                        if (!carte.majEnCours)          // jamais pendant une mise à jour (elle serait coupée)
                            pont.redemarrer();
                    }
                },
                Kirigami.Action {
                    text: "Annuler"
                    icon.name: "dialog-cancel"
                    onTriggered: confirmationRedemarrage.close()
                }
            ]
        }
    }
}
