"""Boucle 2 — promotion canary pilotee par les metriques.

La v2 ne monte en trafic que si elle a fait ses preuves sur une fenetre d'observation
complete : aucune condition de rollback remplie, et un score de confiance moyen au moins
egal a celui mesure sur le jeu d'evaluation a la sortie de la chaine. Ce second critere
repond a la question « derive par rapport a quoi » : la reference est la distribution
constatee au moment ou la version a passe le gate, pas une moyenne glissante mouvante.
"""

from __future__ import annotations

import json

from mardik.api import canary
from mardik.boucles import rollback
from mardik.config import DOSSIER_EVAL, Seuils
from mardik.observabilite import journal, signaux

REFERENCE = DOSSIER_EVAL / "reference_gate.json"


def score_reference() -> float:
    """Score moyen mesure par le gate d'evaluation pour la version actuellement livree."""
    if not REFERENCE.exists():
        return Seuils.GATE_EVALUATION
    with REFERENCE.open(encoding="utf-8") as fichier:
        return float(json.load(fichier).get("score_moyen", Seuils.GATE_EVALUATION))


def evaluer(auteur: str = "automatique") -> dict | None:
    """Promeut la v2 au palier suivant si la fenetre d'observation est concluante."""
    etat = canary.etat()

    if etat["gele"]:
        return None

    poids = etat["poids_v2"]
    suivant = canary.palier_suivant(poids)
    if poids == 0 or suivant is None:
        return None

    fenetre = signaux.lire(limite=Seuils.FENETRE_PROMOTION, version_modele="v2")
    if len(fenetre) < Seuils.FENETRE_PROMOTION:
        return None

    if rollback.diagnostiquer() is not None:
        return None

    indicateurs = signaux.agreger(fenetre)
    reference = score_reference()
    if indicateurs["score_moyen"] < reference:
        journal.tracer(
            evenement="promotion_refusee",
            signal_declencheur="score_moyen",
            auteur=auteur,
            valeur_observee=indicateurs["score_moyen"],
            seuil=reference,
            poids_v2=poids,
        )
        return None

    return canary.definir_poids(
        suivant,
        evenement=journal.PROMOTION,
        signal_declencheur="score_moyen",
        auteur=auteur,
        valeur_observee=indicateurs["score_moyen"],
        seuil=reference,
        fenetre=len(fenetre),
        latence_p95_ms=indicateurs["latence_p95_ms"],
        taux_erreur=indicateurs["taux_erreur"],
    )
