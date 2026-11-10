"""maj-apps — met à jour ce que uupd ne couvre pas.

uupd (Bazzite) met à jour chaque nuit l'image système, les Flatpak et Homebrew.
Tout ce qui a été installé à la main lui échappe : maj-apps prend le relais,
juste après lui (timer utilisateur maj-apps.timer, 04:45).

    maj-apps            met à jour, écrit le rapport, notifie s'il y a du nouveau
    maj-apps --check    simulation : montre ce qui serait fait, ne touche à rien
    maj-apps --report   affiche le dernier rapport
    maj-apps --quiet    met à jour sans notification

Modules (liste MODULES dans principal.py, un fichier par outil) :
  vicinae    (vicinae.py) réinstallé depuis la release GitHub (somme SHA-256
             vérifiée), retour automatique à l'ancienne version si la nouvelle
             ne démarre pas
  ollama     (ollama.py) idem ; remis au lendemain si le serveur tourne (ia-on)
  uv         (uv.py) idem
  distrobox  (distrobox.py) distrobox upgrade, sauf les conteneurs exclus ; celui
             d'une appli ouverte attend la passe suivante (les deux listes :
             [majapps.distrobox] de la configuration locale)
  ge-proton  (geproton.py) signale une nouvelle version (à installer avec
             ProtonPlus)
  godot      (godot.py) signale une nouvelle version
  appimages  (appimages.py) les AppImages de la configuration locale
             ([[majapps.appimages]]) : remplacée (l'ancienne gardée en
             .ancien), jamais pendant qu'elle tourne
  linstat    (linstat.py) dépôt ~/developer/linstat avancé jusqu'au commit
             vérifié (git sans invite d'identifiants), puis son install.sh ;
             un install.sh amont modifié n'est jamais lancé sans relecture
  doublons   (doublons.py) signale un binaire de ~/.local/bin qui masque la
             version Homebrew

Configuration locale : ~/.config/health-hub/config.toml (modèle :
config.exemple.toml) ; sans elle, aucune AppImage suivie, aucun conteneur exclu.

Code de sortie 75 : reporté (jeu en cours ou pas de réseau) ; systemd relance
alors le service 30 min plus tard. Code 1 : au moins un module a échoué.

Lancement : bin/maj-apps (lien ~/.local/bin/maj-apps), ou
python3 -m centre_bazzite.majapps.
"""
