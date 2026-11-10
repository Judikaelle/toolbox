#!/usr/bin/env bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Redémarrer Steam
# @raycast.mode silent

# Optional parameters:
# @raycast.icon 🎮
# @raycast.packageName Health Hub

# Documentation:
# @raycast.description Ferme proprement Steam (puis force si besoin) et le relance. Refuse si un jeu tourne.
#
# Usage : redemarrer-steam.sh [--dry-run] [--force]
#   --dry-run  affiche ce qui serait fait, sans rien signaler ni lancer
#   --force    redémarre même si un jeu tourne (désactivé dans Vicinae)

set -u

dry=0
force=0
for a in "$@"; do
    case "$a" in
        --dry-run) dry=1 ;;
        --force) force=1 ;;
        *) echo "Argument inconnu : $a" >&2; exit 2 ;;
    esac
done

# Même règle que centre-bazzite/centre_bazzite/commun.py (est_jeu).
jeu_en_cours() {
    local d id comm
    for d in /proc/[0-9]*; do
        [ -r "$d/environ" ] || continue
        # SteamGameId non vide et différent de 0
        id="$({ tr '\0' '\n' < "$d/environ"; } 2>/dev/null | sed -n 's/^SteamGameId=//p' | head -n1)"
        { [ -n "$id" ] && [ "$id" != 0 ]; } || continue
        comm="$(cat "$d/comm" 2>/dev/null)" || continue
        case "$comm" in
            wineserver*|steam*|*winedevice*|*explorer*|*.so) continue ;;
        esac
        echo "$comm"
        return 0
    done
    return 1
}

steam_actif() { pgrep -x steam >/dev/null 2>&1 || pgrep -x steamwebhelper >/dev/null 2>&1; }

attendre() { # attendre N : jusqu'à N s que Steam soit parti
    local i
    for ((i = 0; i < $1 * 5; i++)); do
        steam_actif || return 0
        sleep 0.2
    done
    ! steam_actif
}

lancer() { setsid -f steam >/dev/null 2>&1; }

if ! steam_actif; then
    if [ "$dry" = 1 ]; then
        echo "[simulation] Steam ne tourne pas : lancement de Steam"
    else
        lancer
        echo "Steam n'était pas lancé : démarré"
    fi
    exit 0
fi

if jeu="$(jeu_en_cours)"; then
    if [ "$force" = 1 ]; then
        echo "Jeu en cours ($jeu), --force : on continue" >&2
    else
        echo "Un jeu tourne ($jeu) : redémarrage refusé"
        exit 1
    fi
fi

if [ "$dry" = 1 ]; then
    echo "[simulation] steam -shutdown ; attente jusqu'à 20 s de steam et steamwebhelper"
    echo "[simulation] si besoin : SIGTERM, attente 5 s, puis SIGKILL"
    echo "[simulation] relance : setsid -f steam"
    exit 0
fi

steam -shutdown >/dev/null 2>&1 || true
if ! attendre 20; then
    pkill -TERM -x steam; pkill -TERM -x steamwebhelper
    if ! attendre 5; then
        pkill -KILL -x steam; pkill -KILL -x steamwebhelper
        sleep 1
    fi
fi
lancer
echo "Steam redémarré"
