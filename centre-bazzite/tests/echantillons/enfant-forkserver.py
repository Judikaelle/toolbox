"""Enfant factice pour test_analyse : la même mécanique que LinStat.Scanner.run (contexte forkserver, compteurs
partagés, ProcessPoolExecutor), sans rien lire. Ses processus d'analyse dorment jusqu'à ce qu'on les arrête."""
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor


def dormir(x):
    time.sleep(120)
    return x


if __name__ == "__main__":
    ctx = multiprocessing.get_context("forkserver")
    compteurs = (ctx.Value("q", 0), ctx.Value("q", 0))
    with ProcessPoolExecutor(2, mp_context=ctx) as pool:
        pool.submit(int).result()
        futs = [pool.submit(dormir, i) for i in range(2)]
        time.sleep(120)
