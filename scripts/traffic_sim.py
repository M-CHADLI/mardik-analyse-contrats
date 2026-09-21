"""Simulateur de trafic — sert a provoquer, en direct, une derive du score de confiance.

Deux profils :

- `normal`   : des contrats bien rediges, le score reste haut, la promotion peut avancer.
- `degrade`  : des documents longs mais pauvres en vocabulaire juridique (scans mal
               reconnus, pieces jointes hors sujet). Le modele ne trouve plus les clauses,
               son score s'effondre, et la boucle de rollback doit reagir seule.

Le profil degrade ne triche pas : il ne force aucun score, il change la distribution des
documents entrants. C'est une derive de donnees reelle, telle qu'elle se produirait en
production, et c'est l'observabilite qui doit la detecter.

    uv run python scripts/traffic_sim.py --profil degrade --nombre 25
    uv run python scripts/traffic_sim.py --profil normal --nombre 60
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE))

from mardik.config import Seuils  # noqa: E402

BRUIT = (
    "Piece jointe numerisee. Page illisible. Document scanne a basse resolution. "
    "Annexe technique sans portee juridique. Tableau de chiffres sans legende. "
)


def contrat_normal() -> str:
    from eval.generer_golden import CLAUSES, composer

    clauses = random.sample(list(CLAUSES), k=random.randint(4, len(CLAUSES)))
    return composer(clauses, blocs_remplissage=random.randint(1, 8))


def contrat_degrade() -> str:
    """Document long mais vide de contenu juridique exploitable."""
    return BRUIT * random.randint(250, 400)


def envoyer(hote: str, contrat: str) -> dict | None:
    requete = urllib.request.Request(
        f"{hote.rstrip('/')}/analyser",
        data=json.dumps({"contrat": contrat}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requete, timeout=120) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as erreur:
        return {"erreur": erreur.code, "corps": erreur.read().decode("utf-8", "ignore")[:120]}
    except urllib.error.URLError as erreur:
        print(f"API injoignable sur {hote} ({erreur})")
        return None


def etat_canary(hote: str) -> dict:
    with urllib.request.urlopen(f"{hote.rstrip('/')}/api/canary", timeout=30) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def main() -> int:
    analyseur = argparse.ArgumentParser(description="Simulateur de trafic Mardik.")
    analyseur.add_argument("--hote", default="http://localhost:8000")
    analyseur.add_argument("--profil", choices=("normal", "degrade"), default="normal")
    analyseur.add_argument("--nombre", type=int, default=Seuils.FENETRE_ROLLBACK)
    arguments = analyseur.parse_args()

    depart = etat_canary(arguments.hote)
    print(f"Repartition au depart : {depart['poids_v2']} % vers la v2")
    print(f"Envoi de {arguments.nombre} requetes (profil {arguments.profil})\n")

    scores: list[float] = []
    for tour in range(1, arguments.nombre + 1):
        contrat = contrat_degrade() if arguments.profil == "degrade" else contrat_normal()
        reponse = envoyer(arguments.hote, contrat)
        if reponse is None:
            return 1

        if "erreur" in reponse:
            print(f"  {tour:>3} : erreur HTTP {reponse['erreur']}")
            continue

        version = reponse.get("version_modele", "?")
        score = reponse.get("score_confiance")
        if score is None:
            print(f"  {tour:>3} : servi par {version} (aucun score — generation v1)")
            continue

        scores.append(score)
        marque = "  <- sous le seuil" if score < Seuils.FAIBLE_CONFIANCE else ""
        print(f"  {tour:>3} : servi par {version}  score {score:.3f}{marque}")

    arrivee = etat_canary(arguments.hote)
    print()
    if scores:
        faibles = sum(1 for score in scores if score < Seuils.FAIBLE_CONFIANCE)
        print(f"Score moyen v2      : {sum(scores) / len(scores):.3f}")
        print(
            f"Analyses peu fiables: {faibles}/{len(scores)} "
            f"({faibles / len(scores):.0%}, seuil {Seuils.ROLLBACK_PART_FAIBLE_CONFIANCE:.0%})"
        )

    print(f"Repartition a l'arrivee : {arrivee['poids_v2']} % vers la v2")
    if arrivee["poids_v2"] < depart["poids_v2"]:
        print("\nROLLBACK DECLENCHE par la boucle d'observabilite.")
        print(f"Motif : {arrivee.get('motif_gel')}")
        print("Consultez le journal de pilotage : /tableau-de-bord")
    elif arrivee["poids_v2"] > depart["poids_v2"]:
        print("\nPROMOTION : la v2 est passee au palier suivant.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
