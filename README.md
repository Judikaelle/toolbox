# Health Hub

Une petite appli KDE pour [Bazzite](https://bazzite.gg) qui réunit trois choses au même endroit :

- **Mises à jour** : l'image système, les Flatpak et Homebrew (par `uupd`, le service de Bazzite), plus ce que `uupd`
  ignore (outils installés à la main, AppImages, conteneurs distrobox), avec un résumé des notes de version ;
- **Santé** : SSD (usure, température), GPU, services en échec, erreurs du journal, plantages, contrôles hebdomadaires,
  noyau (carte graphique, processeur et mémoire, USB), pression mémoire et sécurité légère (pare-feu, ports ouverts,
  fichiers de démarrage, dossiers temporaires), en lecture seule ;
- **Stockage** : disques physiques et volumes, analyse de l'espace (avec LinStat, facultatif), ménage guidé et pistes
  pour libérer de la place.

Une fenêtre Kirigami (PySide6), un widget Plasma pour la barre des tâches et un moteur Python (`centre_bazzite`, commande
`centre-bazzite`) qui écrit l'état lu par les deux. Le ménage ne supprime rien sans confirmation, et les commandes qui
touchent au système (`sudo`, réinstallation de Flatpak) sont affichées pour être copiées, jamais lancées.

Pas de capture d'écran ici : elles montreraient les données d'une vraie machine.

## Prérequis

- Bazzite, ou un autre Fedora Atomic avec KDE Plasma 6 (`rpm-ostree`, `flatpak`, systemd utilisateur) ;
- Python 3.11 au moins (pour `tomllib`), avec PySide6 et Kirigami installés dans le système (la fenêtre en a besoin ;
  le moteur et `maj-apps` n'utilisent que la bibliothèque standard) ;
- facultatif : Ollama (résumés des notes de version), `nvidia-smi` (carte NVIDIA), LinStat (analyse des volumes).

## Installation

```sh
git clone https://github.com/Judikaelle/toolbox.git
cd toolbox/centre-bazzite
./install.sh
```

`install.sh` peut être relancé à tout moment. Il crée les commandes dans `~/.local/bin` (`centre-bazzite`,
`health-hub` pour la fenêtre, `maj-apps`, `bazzite-health`), installe l'icône, le lanceur et le widget Plasma, active les
minuteurs systemd utilisateur (relevé toutes les heures, `maj-apps` chaque nuit à 4 h 45, bilan le lundi), pose le
modèle de configuration s'il n'y en a pas encore, et installe LinStat s'il le peut.

## Configuration

Ce qui est propre à ta machine vit dans `~/.config/health-hub/config.toml`, jamais dans le dépôt. Le modèle commenté est
[`centre-bazzite/config.exemple.toml`](centre-bazzite/config.exemple.toml) ; sans configuration, Health Hub suit
seulement Système (`/var`) et Home (`/var/home`) et n'ajoute rien de personnel.

- `[[volumes]]` : les volumes suivis, ceux qui doivent être montés (`attendu`) ou peuvent être débranchés
  (`facultatif`) ;
- `[[majapps.appimages]]` : les AppImages que `maj-apps` tient à jour depuis leurs releases GitHub ;
- `[majapps.distrobox]` : les conteneurs à ne jamais mettre à jour (`exclure`) et ceux dont l'appli doit être fermée
  avant (`applis`) ;
- `[optimiser]` : les pistes « libérer un disque externe » et « fusionner deux volumes » de la page Stockage ;
- `[resume]` : qui lit les résumés des notes de version (`contexte`).

Le fichier est relu à chaque relevé ; s'il est illisible, Health Hub garde les valeurs par défaut et le dit dans son
journal.

## maj-apps

`maj-apps` met à jour ce que `uupd` ne couvre pas : Vicinae, Ollama, uv, les conteneurs distrobox, les AppImages de la
configuration et LinStat ; il signale aussi une nouvelle version de GE-Proton ou de Godot. Chaque téléchargement est
vérifié (SHA-256), l'ancienne version est gardée, et rien n'est remplacé pendant qu'un jeu ou l'appli concernée tourne.

```sh
maj-apps --check     # simulation : ce qui serait fait, sans rien toucher
maj-apps --report    # le dernier rapport
```

## LinStat (facultatif)

L'analyse des volumes (catégories, plus gros dossiers) utilise le moteur de
[LinStat](https://github.com/BiasedMonkey/linstat), un analyseur de disque libre. `install.sh` le clone dans
`~/developer/linstat` et lance son installeur ; sans lui, la page Stockage montre l'espace libre seul.

## Tests

```sh
cd centre-bazzite
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests
```

Les tests ne lancent aucune vraie mise à jour, n'envoient aucune notification et ne lisent jamais la configuration
locale : ils ont la leur (`tests/echantillons/config.toml`), avec des noms d'exemple.

## Remerciements

Les contrôles du noyau, de la mémoire et de la sécurité sont repris et adaptés de
[Bilan Santé PC](https://github.com/BiasedMonkey/bilan-sante) de BiasedMonkey (GPL-3.0).

## Licence

GPL-3.0-or-later : voir [LICENSE](LICENSE).
