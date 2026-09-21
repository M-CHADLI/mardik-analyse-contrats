"""Boucle 1 — rollback sur signal.

Apres chaque requete servie par la v2, on relit la fenetre glissante des derniers signaux
v2 et on la confronte aux trois conditions de `besoin_client.md`. Une seule condition
vraie suffit a ramener le trafic a 0 % et a geler la promotion : en production, on arrete
l'hemorragie d'abord, on diagnostique ensuite.
"""

from __future__ import annotations

from mardik.api import canary
from mardik.config import Seuils
from mardik.observabilite import journal, signaux


def diagnostiquer() -> tuple[str, float, float] | None:
    """Renvoie (signal, valeur observee, seuil) si une condition de rollback est remplie."""
    fenetre = signaux.lire(limite=Seuils.FENETRE_ROLLBACK, version_modele="v2")
    if len(fenetre) < Seuils.FENETRE_ROLLBACK:
        return None

    indicateurs = signaux.agreger(fenetre)

    latence_s = indicateurs["latence_p95_ms"] / 1000
    if latence_s > Seuils.ROLLBACK_LATENCE_P95_S:
        return ("latence_p95", round(latence_s, 2), Seuils.ROLLBACK_LATENCE_P95_S)

    if indicateurs["taux_erreur"] > Seuils.ROLLBACK_TAUX_ERREUR:
        return ("taux_erreur", indicateurs["taux_erreur"], Seuils.ROLLBACK_TAUX_ERREUR)

    part_faible = indicateurs["part_faible_confiance"]
    if part_faible > Seuils.ROLLBACK_PART_FAIBLE_CONFIANCE:
        return (
            "part_faible_confiance",
            part_faible,
            Seuils.ROLLBACK_PART_FAIBLE_CONFIANCE,
        )

    return None


def evaluer() -> dict | None:
    """Declenche le rollback si un signal l'exige. Appelee apres chaque requete v2."""
    etat = canary.etat()
    if etat["poids_v2"] == 0:
        return None

    constat = diagnostiquer()
    if constat is None:
        return None

    signal, valeur, seuil = constat
    return canary.definir_poids(
        0,
        evenement=journal.ROLLBACK,
        signal_declencheur=signal,
        auteur="automatique",
        valeur_observee=valeur,
        seuil=seuil,
        geler=True,
        motif_gel=f"rollback automatique sur {signal}",
    )


def declencher_manuellement(auteur: str, motif: str) -> dict:
    """Le bouton de rollback du tableau de bord."""
    return canary.definir_poids(
        0,
        evenement=journal.ROLLBACK,
        signal_declencheur="decision_humaine",
        auteur=auteur,
        valeur_observee=motif,
        geler=True,
        motif_gel=motif,
    )
