"""Boucle 3 — enrichissement du jeu d'evaluation par les cas reels difficiles.

Une analyse dont le score passe sous le seuil de fiabilite est capturee, puis versee au
jeu d'evaluation ou elle sera rejouee par le gate a la fusion suivante. C'est le reflexe
« un incident de production devient un test de non-regression », transpose au modele.

**Une etape de validation humaine separe la capture du versement.** Elle remplit deux
roles a la fois :

1. *Exactitude* — un score bas signifie que le modele doute, pas qu'il s'est trompe.
   Verser sa sortie telle quelle comme verite de reference graverait une erreur dans le
   jeu qui garde la chaine.
2. *Confidentialite* — la pseudonymisation automatique (voir `anonymisation.py`) traite
   ce qui a une forme reconnaissable, mais laissera passer une raison sociale ecrite au
   fil du texte. Le relecteur est le dernier controle avant que le cas ne parte dans Git
   et dans l'integration continue.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from mardik.boucles.anonymisation import anonymiser
from mardik.config import CLAUSES_ATTENDUES, FILE_VALIDATION, GOLDEN, Seuils
from mardik.observabilite import journal

_verrou = threading.Lock()


def _lire_lignes(chemin) -> list[dict]:
    if not chemin.exists():
        return []
    with chemin.open(encoding="utf-8") as fichier:
        return [json.loads(ligne) for ligne in fichier if ligne.strip()]


def _ajouter(chemin, enregistrement: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with _verrou, chemin.open("a", encoding="utf-8") as fichier:
        fichier.write(json.dumps(enregistrement, ensure_ascii=False) + "\n")


def capturer(
    contrat: str, *, score: float, clauses_trouvees: list[str], requete_id: str
) -> dict | None:
    """Capture une analyse peu fiable. Sans effet si le score est au-dessus du seuil.

    Le contrat est pseudonymisé **avant** d'etre ecrit sur disque : le texte d'origine ne
    quitte jamais la memoire du processus. Un cas capture finit dans `golden.jsonl`, donc
    dans Git et dans l'integration continue ; y verser un contrat client en clair serait
    une fuite, pas un enrichissement.
    """
    if score >= Seuils.FAIBLE_CONFIANCE:
        return None

    contrat_anonyme, substitutions = anonymiser(contrat)

    cas = {
        "id": str(uuid.uuid4())[:8],
        "capture_le": datetime.now(timezone.utc).isoformat(),
        "requete_id": requete_id,
        "score_observe": score,
        "clauses_trouvees": clauses_trouvees,
        "contrat": contrat_anonyme,
        "anonymisation": substitutions,
        "statut": "a_valider",
    }
    _ajouter(FILE_VALIDATION, cas)

    journal.tracer(
        evenement=journal.CAPTURE_FAIBLE_CONFIANCE,
        signal_declencheur="score_confiance",
        auteur="automatique",
        valeur_observee=score,
        seuil=Seuils.FAIBLE_CONFIANCE,
        cas_id=cas["id"],
        anonymisation=substitutions,
    )
    return cas


def file_attente() -> list[dict]:
    """Cas captures en attente de relecture, sans le texte integral du contrat."""
    deja_verses = {cas["id"] for cas in _lire_lignes(GOLDEN) if cas.get("origine") == "production"}
    rejetes = {cas["id"] for cas in _lire_lignes(FILE_VALIDATION) if cas.get("statut") == "rejete"}

    vus: set[str] = set()
    attente = []
    for cas in reversed(_lire_lignes(FILE_VALIDATION)):
        if cas["id"] in vus or cas["id"] in deja_verses or cas["id"] in rejetes:
            continue
        vus.add(cas["id"])
        attente.append({**cas, "contrat": cas["contrat"][:400], "taille": len(cas["contrat"])})
    return attente


def valider(cas_id: str, clauses_attendues: list[str], auteur: str) -> dict:
    """Verse un cas relu dans le jeu d'evaluation ; il sera rejoue au prochain gate.

    Le texte verse est celui deja pseudonymise a la capture : la validation confirme,
    elle ne reintroduit jamais l'original.
    """
    cas = next((c for c in _lire_lignes(FILE_VALIDATION) if c["id"] == cas_id), None)
    if cas is None:
        raise KeyError(f"cas inconnu : {cas_id}")

    retenues = [clause for clause in clauses_attendues if clause in CLAUSES_ATTENDUES]
    entree = {
        "id": cas["id"],
        "origine": "production",
        "ajoute_le": datetime.now(timezone.utc).isoformat(),
        "valide_par": auteur,
        "score_observe": cas["score_observe"],
        "contrat": cas["contrat"],
        "anonymisation": cas.get("anonymisation", {}),
        "clauses_attendues": retenues,
    }
    _ajouter(GOLDEN, entree)

    journal.tracer(
        evenement="enrichissement_jeu_evaluation",
        signal_declencheur="validation_humaine",
        auteur=auteur,
        valeur_observee=cas["score_observe"],
        seuil=Seuils.FAIBLE_CONFIANCE,
        cas_id=cas_id,
        clauses_attendues=retenues,
        anonymisation=cas.get("anonymisation", {}),
    )
    return entree


def rejeter(cas_id: str, auteur: str, motif: str) -> None:
    """Ecarte un cas capture : il n'entrera pas dans le jeu d'evaluation."""
    _ajouter(FILE_VALIDATION, {"id": cas_id, "statut": "rejete", "motif": motif})
    journal.tracer(
        evenement="capture_rejetee",
        signal_declencheur="validation_humaine",
        auteur=auteur,
        valeur_observee=motif,
        cas_id=cas_id,
    )
