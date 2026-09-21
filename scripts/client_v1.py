"""Client historique de l'API Mardik — ecrit avant l'existence de la v2.

Ce fichier est le temoin executable de l'exigence « le client v1 ne casse jamais ». Il ne
connait que le champ `contrat` en entree et le champ `clauses` en sortie ; il ignore
totalement le score de confiance et les champs ajoutes par la v2.

**Il ne doit jamais etre modifie.** Si une evolution de l'API oblige a le retoucher, c'est
que la compatibilite ascendante a ete rompue.

    uv run python scripts/client_v1.py
    uv run python scripts/client_v1.py --hote http://localhost:8000 --repetitions 5
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

CONTRAT = """CONTRAT DE PRESTATION DE SERVICES

Le present contrat prend effet le 1er janvier 2026 pour une duree ferme de trois annees.

ARTICLE - RESILIATION
Chaque partie pourra resilier le contrat sous reserve d'un preavis de trois mois notifie
par lettre recommandee.

ARTICLE - PAIEMENT
La remuneration est fixee a 4 500 euros hors taxes par mois. Le reglement intervient a
trente jours date de facture. Tout retard entraine une penalite de retard.

ARTICLE - RESPONSABILITE
La responsabilite du Prestataire est limitee aux dommages directs, dans la limite du
plafond correspondant aux sommes versees au cours des douze derniers mois.

ARTICLE - CONFIDENTIALITE
Chaque partie s'engage a considerer comme confidentielles les informations recues, sans
divulgation a un tiers.
"""


def analyser(hote: str, contrat: str) -> dict:
    """Appelle l'API exactement comme le faisait le client d'origine."""
    requete = urllib.request.Request(
        f"{hote.rstrip('/')}/analyser",
        data=json.dumps({"contrat": contrat}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def main() -> int:
    analyseur = argparse.ArgumentParser(description="Client historique de l'API Mardik.")
    analyseur.add_argument("--hote", default="http://localhost:8000")
    analyseur.add_argument("--repetitions", type=int, default=3)
    arguments = analyseur.parse_args()

    versions_rencontrees = set()

    for tour in range(1, arguments.repetitions + 1):
        try:
            reponse = analyser(arguments.hote, CONTRAT)
        except urllib.error.URLError as erreur:
            print(f"ECHEC : l'API est injoignable sur {arguments.hote} ({erreur})")
            return 1

        # Le contrat d'origine : un dictionnaire de clauses, rien d'autre n'est attendu.
        if "clauses" not in reponse:
            print(f"ECHEC : le champ 'clauses' a disparu de la reponse — {sorted(reponse)}")
            return 1
        if not isinstance(reponse["clauses"], dict):
            print(f"ECHEC : 'clauses' n'est plus un objet mais {type(reponse['clauses'])}")
            return 1

        versions_rencontrees.add(reponse.get("version_modele", "?"))
        clauses = sorted(reponse["clauses"])
        print(
            f"  appel {tour} : servi par {reponse.get('version_modele', '?')} — clauses {clauses}"
        )

    print()
    print(
        f"OK : {arguments.repetitions} appels reussis, generations rencontrees "
        f"{sorted(versions_rencontrees)}"
    )
    print("Le client v1 fonctionne sans modification, quelle que soit la version servie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
