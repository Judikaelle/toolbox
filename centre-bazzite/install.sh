#!/usr/bin/env bash
# Installe le Health Hub pour l'utilisateur courant. Idempotent : peut être relancé
# à tout moment (les éléments absents, comme la fenêtre ou le plasmoïde, sont ignorés).
set -euo pipefail

ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin="$HOME/.local/bin"
icones="$HOME/.local/share/icons/hicolor/scalable/apps"
unites="$HOME/.config/systemd/user"

mkdir -p "$bin" "$icones" "$unites"

# Configuration locale (volumes, AppImages suivies, conteneurs distrobox…) : le modèle commenté, posé une seule fois ;
# une configuration existante n'est jamais écrasée.
# debut-config
config="$HOME/.config/health-hub/config.toml"
if [ -e "$config" ]; then
    echo "configuration : $config gardée"
else
    mkdir -p "$(dirname "$config")"
    cp -n "$ici/config.exemple.toml" "$config"
    echo "configuration : $config (modèle à adapter, voir config.exemple.toml)"
fi
# fin-config

ln -sfn "$ici/bin/centre-bazzite" "$bin/centre-bazzite"
echo "lien : $bin/centre-bazzite"

if [ -e "$ici/fenetre/centre-bazzite-fenetre" ]; then
    ln -sfn "$ici/fenetre/centre-bazzite-fenetre" "$bin/centre-bazzite-fenetre"
    echo "lien : $bin/centre-bazzite-fenetre"
    ln -sfn "$ici/fenetre/centre-bazzite-fenetre" "$bin/health-hub"
    echo "lien : $bin/health-hub"
else
    echo "ignoré : fenetre/centre-bazzite-fenetre n'existe pas encore"
fi

cp -f "$ici/icones/centre-bazzite.svg" "$ici/icones/centre-bazzite-symbolic.svg" "$icones/"
echo "icônes : $icones"

if [ -e "$ici/centre-bazzite.desktop" ]; then
    mkdir -p "$HOME/.local/share/applications"
    cp -f "$ici/centre-bazzite.desktop" "$HOME/.local/share/applications/centre-bazzite.desktop"
    echo "lanceur : centre-bazzite.desktop"
else
    echo "ignoré : centre-bazzite.desktop n'existe pas encore"
fi

plasmoide="$ici/plasmoide/org.toolbox.centrebazzite"
if [ -d "$plasmoide" ]; then
    if command -v kpackagetool6 >/dev/null 2>&1; then
        # Mise à jour si le plasmoïde est déjà installé, installation sinon ; les erreurs restent visibles.
        installes="$(kpackagetool6 --type Plasma/Applet --list)"
        if grep -qxF "org.toolbox.centrebazzite" <<<"$installes"; then
            kpackagetool6 --type Plasma/Applet --upgrade "$plasmoide"
            echo "plasmoïde : mis à jour (pour recharger celui de la barre : systemctl --user restart plasma-plasmashell)"
        else
            kpackagetool6 --type Plasma/Applet --install "$plasmoide"
            echo "plasmoïde : installé"
        fi
    else
        echo "ignoré : kpackagetool6 est introuvable"
    fi
else
    echo "ignoré : le plasmoïde n'existe pas encore"
fi

cp -f "$ici/systemd/centre-bazzite-releve.service" "$ici/systemd/centre-bazzite-releve.timer" "$unites/"
systemctl --user daemon-reload
systemctl --user enable --now centre-bazzite-releve.timer
echo "minuteur : centre-bazzite-releve.timer actif"

# Mode jeu automatique : un service de la session graphique. try-restart relance un service déjà actif, pour qu'il
# prenne le nouveau code ; son SIGTERM le suspend sans rien perdre (la partie en cours reste notée, la reprise décide).
# Il passe avant enable --now : à la première installation, le service ne démarre qu'une fois.
# debut-modejeu
cp -f "$ici/systemd/health-hub-modejeu.service" "$unites/"
systemctl --user daemon-reload
systemctl --user try-restart health-hub-modejeu.service
systemctl --user enable --now health-hub-modejeu.service
echo "mode jeu : health-hub-modejeu actif"
# fin-modejeu

# maj-apps : lanceur du paquet centre_bazzite.majapps, unités versionnées (le service
# n'est jamais démarré ici : seul le minuteur l'est).
ln -sfn "$ici/bin/maj-apps" "$bin/maj-apps"
echo "lien : $bin/maj-apps"
cp -f "$ici/systemd/maj-apps.service" "$ici/systemd/maj-apps.timer" "$unites/"
systemctl --user daemon-reload
systemctl --user enable --now maj-apps.timer
echo "minuteur : maj-apps.timer actif"

# bazzite-health : lanceur du bilan hebdomadaire (module hebdo). L'ancien script autonome, s'il est
# encore là, est mis de côté une seule fois ; un lien existant (relance) n'est pas touché. Le service
# n'est jamais démarré ici (il enverrait une vraie notification) : seul le minuteur l'est.
# debut-lien-bazzite-health
f="$bin/bazzite-health"
if [ -f "$f" ] && [ ! -L "$f" ]; then
    sauvegarde="$bin/bazzite-health.avant-health-hub"
    # jamais d'écrasement : si la sauvegarde existe déjà, celle-ci prend un nom horodaté
    [ -e "$sauvegarde" ] && sauvegarde="$sauvegarde-$(date +%Y%m%d-%H%M%S)"
    mv -n "$f" "$sauvegarde"
    echo "ancien bazzite-health conservé : $sauvegarde"
fi
ln -sfn "$ici/bin/bazzite-health" "$f"
echo "lien : $f"
# fin-lien-bazzite-health
cp -f "$ici/systemd/bazzite-health.service" "$ici/systemd/bazzite-health.timer" "$unites/"
systemctl --user daemon-reload
systemctl --user enable --now bazzite-health.timer
echo "minuteur : bazzite-health.timer actif"

command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

# Commande Vicinae « Redémarrer Steam » : lien vers le script versionné dans le dossier
# de scripts par défaut de Vicinae (ignoré si Vicinae n'est pas installé).
if [ -x "$bin/vicinae" ] || command -v vicinae >/dev/null 2>&1; then
    scripts_vicinae="$HOME/.local/share/vicinae/scripts"
    mkdir -p "$scripts_vicinae"
    ln -sfn "$ici/../vicinae/scripts/redemarrer-steam.sh" "$scripts_vicinae/redemarrer-steam.sh"
    echo "vicinae : commande Redémarrer Steam (redémarrer Vicinae pour la voir : systemctl --user restart vicinae)"
else
    echo "ignoré : Vicinae n'est pas installé"
fi

# debut-linstat
# LinStat (analyseur de disque public de BiasedMonkey) : cloné une fois, puis son propre install.sh,
# seulement après ce clone neuf ou si linstat.py manque. Ensuite, maj-apps le tient à jour et ne relance
# jamais un install.sh amont modifié sans relecture (V48) : le relancer ici à chaque passage contournerait
# cette relecture. Un échec (hors ligne…) n'arrête pas l'installation.
linstat_depot="$HOME/developer/linstat"
linstat_clone_neuf=0
if [ ! -d "$linstat_depot/.git" ]; then
    mkdir -p "$HOME/developer"
    if GIT_TERMINAL_PROMPT=0 git clone https://github.com/BiasedMonkey/linstat.git "$linstat_depot"; then
        echo "LinStat : dépôt cloné"
        linstat_clone_neuf=1
    else
        echo "LinStat : installation impossible (hors ligne ?) — la page Stockage montrera l'espace libre seul"
    fi
fi
if [ -d "$linstat_depot/.git" ] && [ "$linstat_clone_neuf" = 0 ] && [ -f "$HOME/.local/share/linstat/linstat.py" ]; then
    echo "LinStat : déjà installé (mis à jour chaque nuit par maj-apps)"
elif [ -d "$linstat_depot/.git" ]; then
    if (cd "$linstat_depot" && bash install.sh); then
        echo "LinStat : installé"
    else
        echo "LinStat : l'installeur de LinStat a échoué — la page Stockage montrera l'espace libre seul"
    fi
fi
# fin-linstat
