"""LinStat (analyseur de disque de BiasedMonkey) : dépôt git tenu à jour en avance rapide, puis réinstallé."""

from .outils import A_FAIRE, A_JOUR, ECHEC, HOME, MANUEL, MIS_A_JOUR, Resultat, run

DEPOT = HOME / "developer/linstat"
# La nuit, personne ne répond : aucun git ne doit attendre un identifiant (dépôt devenu privé, jeton expiré…).
GIT_SANS_INVITE = ["env", "GIT_TERMINAL_PROMPT=0", "GIT_ASKPASS=true", "git", "-c", "credential.helper="]


def _sha(code, sortie):
    sortie = sortie.strip()
    ok = code == 0 and len(sortie) == 40 and all(c in "0123456789abcdef" for c in sortie)
    return sortie if ok else None


def mod_linstat(simulation):
    if not DEPOT.exists():
        return None
    git = GIT_SANS_INVITE + ["-C", DEPOT]
    run(git + ["fetch", "--quiet"], timeout=60)
    avant = _sha(*run(git + ["rev-parse", "HEAD"], timeout=30))
    apres = _sha(*run(git + ["rev-parse", "@{u}"], timeout=30))
    if not avant or not apres:
        return Resultat("linstat", ECHEC, "LinStat : état du dépôt illisible", "")
    court_avant, court_apres = avant[:7], apres[:7]
    # HEAD égal à @{u}, ou local en avance / divergé (rien à tirer en avance rapide) : rien à faire
    if avant == apres or run(git + ["merge-base", "--is-ancestor", "HEAD", "@{u}"], timeout=30)[0] != 0:
        return Resultat("linstat", A_JOUR, "LinStat %s à jour" % court_avant, "")
    titre = "LinStat %s → %s" % (court_avant, court_apres)
    if simulation:
        return Resultat("linstat", A_FAIRE, titre, "")
    # Avance rapide jusqu'au commit vérifié, sans nouveau fetch (pas de `pull`) : l'install.sh exécuté plus bas est
    # exactement celui que `diff avant apres` a comparé (V48).
    code, sortie = run(git + ["merge", "--ff-only", apres], timeout=120)
    if code != 0:
        return Resultat("linstat", ECHEC, "LinStat : git merge --ff-only a échoué", sortie.strip()[-500:])
    _, notes = run(git + ["log", "--oneline", "%s..%s" % (court_avant, court_apres)], timeout=30)
    notes = notes[:20000]
    # un install.sh tiers modifié n'est jamais exécuté sans relecture
    if run(git + ["diff", "--quiet", avant, apres, "--", "install.sh"], timeout=30)[0] != 0:
        return Resultat("linstat", MANUEL, "LinStat : install.sh a changé — relis-le puis lance "
                        "bash ~/developer/linstat/install.sh", "", court_avant, court_apres, notes)
    code, sortie = run(["bash", "install.sh"], timeout=300, cwd=DEPOT)
    if code != 0:
        return Resultat("linstat", ECHEC, "LinStat : install.sh a échoué", sortie.strip()[-500:])
    return Resultat("linstat", MIS_A_JOUR, titre, "", court_avant, court_apres, notes)
