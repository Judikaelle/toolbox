"""Faux LinStat pour les tests de Health Hub : la même API que le moteur réel (~/.local/share/linstat/linstat.py),
sans rien lire sur le disque. `Scanner.run()` rend un arbre fixe, celui d'un volume de jeux :
Emulateur 388 Gio, Bibliotheque 287 Gio, DossierA 51 Gio, DossierB 31 Gio.

Formes reprises du vrai moteur : `categories()` rend des listes `[nom, octets, nombre, [extensions]]` triées par
taille ; `Dir.cat` ne vaut une catégorie que si une règle de chemin s'applique (sinon `None`) ; `tree(root)` calcule
les totaux et `file_count`."""
import os
import time

GIO = 1024 ** 3
PAUSE_S = 0          # durée simulée de run(), pour les tests de l'avancement

CATEGORIES = [
    ("Modèles IA", (171, 71, 188), "gguf safetensors"),
    ("Jeux", (66, 133, 244), "pak vpk"),
    ("Vidéos", (234, 67, 53), "mp4 mkv"),
    ("VM & images disque", (38, 166, 154), "iso img"),
    ("Autres", (150, 150, 150), ""),
]
PATH_RULES = {"Jeux": ["*/Bibliotheque", "*/steamapps/common"], "Caches": ["~/.cache"]}

# (nom, octets des fichiers directs, nombre de fichiers directs, catégorie de chemin, sous-dossiers) ;
# volontairement dans le désordre, et Bibliotheque n'a rien en direct : son total vient de son sous-dossier.
ARBRE = [
    ("DossierA", 51 * GIO, 4200, None, []),
    ("Emulateur", 388 * GIO, 310, None, []),
    ("DossierB", 31 * GIO, 95, None, []),
    ("Bibliotheque", 0, 0, "Jeux", [("steamapps", 287 * GIO, 18000, None, [])]),
]


class Dir:
    __slots__ = ("name", "dirs", "fsize", "fcount", "total", "kept", "cat", "parent")

    def __init__(self, name):
        self.name = name
        self.dirs = []
        self.fsize = 0
        self.fcount = 0
        self.total = 0
        self.kept = None
        self.cat = None
        self.parent = None

    def path(self):
        parts, d = [], self
        while d is not None:
            parts.append(d.name)
            d = d.parent
        return os.path.join(*reversed(parts))


def _greffer(parent, entrees):
    for nom, octets, nombre, cat, enfants in entrees:
        d = Dir(nom)
        d.fsize, d.fcount, d.cat, d.parent = octets, nombre, cat, parent
        parent.dirs.append(d)
        _greffer(d, enfants)


class Scanner:
    def __init__(self, root, one_fs=True, procs=None, budget=40_000):
        self.root = os.path.realpath(root)
        self.one_fs = one_fs
        self.procs = procs
        self.errors = 0
        self._files = self._total = 0

    @property
    def files(self):
        return self._files

    @property
    def total(self):
        return self._total

    def run(self):
        root = Dir(self.root)
        _greffer(root, ARBRE)
        self._files, self._total = 22605, 757 * GIO
        time.sleep(PAUSE_S)
        self.errors = 3
        return root

    def tree(self, root):
        order, stack = [], [root]
        while stack:
            d = stack.pop()
            order.append(d)
            stack.extend(d.dirs)
        for d in reversed(order):
            d.total = d.fsize + sum(c.total for c in d.dirs)
        self.file_count = sum(d.fcount for d in order)
        return {"n": root.name, "s": root.total}

    def categories(self):
        return [["Jeux", 706 * GIO, 18405, ["pak", "(aucune)", "vpk"]],
                ["VM & images disque", 51 * GIO, 12, ["iso"]],
                ["Autres", 120 * 1024 ** 2, 4188, ["(aucune)", "txt", "ini"]]]
