"""Passerelle canary — decide, requete par requete, quelle generation de modele sert.

Le choix d'une repartition applicative plutot qu'un proxy pondere est deliberé : la part
de trafic v1/v2 devient mesurable a la source (c'est un des cinq signaux exiges), le
rollback se reduit a une ecriture d'etat — donc a un bouton — et chaque bascule est tracee
au journal de pilotage avec le signal qui l'a declenchee.
"""

from __future__ import annotations

import json
import random
import threading
from datetime import datetime, timezone

from mardik.config import ETAT_CANARY, Seuils, config
from mardik.observabilite import journal

_verrou = threading.Lock()

ETAT_INITIAL = {
    "poids_v2": 0,
    "gele": False,
    "motif_gel": None,
    "derniere_maj": None,
}


def etat() -> dict:
    """Etat courant de la repartition. Le fichier fait autorite sur la variable d'env."""
    if not ETAT_CANARY.exists():
        return {**ETAT_INITIAL, "poids_v2": config.mardik_canary_v2}

    with _verrou, ETAT_CANARY.open(encoding="utf-8") as fichier:
        return {**ETAT_INITIAL, **json.load(fichier)}


def _ecrire(nouvel_etat: dict) -> None:
    ETAT_CANARY.parent.mkdir(parents=True, exist_ok=True)
    nouvel_etat["derniere_maj"] = datetime.now(timezone.utc).isoformat()
    with _verrou, ETAT_CANARY.open("w", encoding="utf-8") as fichier:
        json.dump(nouvel_etat, fichier, ensure_ascii=False, indent=2)


def definir_poids(
    poids: int,
    *,
    evenement: str,
    signal_declencheur: str,
    auteur: str,
    valeur_observee: float | str | None = None,
    seuil: float | str | None = None,
    geler: bool = False,
    motif_gel: str | None = None,
) -> dict:
    """Modifie la repartition et trace systematiquement la decision.

    Aucune bascule n'est possible sans passer par ici : c'est ce qui garantit qu'il
    n'existe aucun changement de trafic non trace.
    """
    precedent = etat()
    poids = max(0, min(100, poids))

    nouvel_etat = {
        **precedent,
        "poids_v2": poids,
        "gele": geler,
        "motif_gel": motif_gel if geler else None,
    }
    _ecrire(nouvel_etat)

    journal.tracer(
        evenement=evenement,
        signal_declencheur=signal_declencheur,
        auteur=auteur,
        valeur_observee=valeur_observee,
        seuil=seuil,
        poids_v2_avant=precedent["poids_v2"],
        poids_v2_apres=poids,
        gele=geler,
    )
    return nouvel_etat


def palier_suivant(poids_actuel: int) -> int | None:
    """Palier de promotion immediatement superieur, ou None si deja a 100 %."""
    for palier in Seuils.PALIERS_CANARY:
        if palier > poids_actuel:
            return palier
    return None


def choisir_version(tirage: float | None = None) -> str:
    """Tire la generation qui servira cette requete, selon le poids courant."""
    poids = etat()["poids_v2"]
    valeur = random.random() * 100 if tirage is None else tirage * 100
    return "v2" if valeur < poids else "v1"
