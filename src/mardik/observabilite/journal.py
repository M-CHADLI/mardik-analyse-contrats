"""Journal de pilotage — la trace de toute decision prise sur la chaine.

Exigence du CTO : « Tout ajustement de la chaine (changement de seuil, promotion,
rollback) est trace : quel signal l'a declenche, quand, par qui ou par quoi. » Ce module
est le seul point d'ecriture de ce journal, et chaque entree porte obligatoirement le
signal declencheur et son auteur.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from mardik.config import JOURNAL_PILOTAGE, empreinte_execution, version_livree

_verrou = threading.Lock()

ROLLBACK = "rollback"
PROMOTION = "promotion"
AJUSTEMENT_SEUIL = "ajustement_seuil"
CAPTURE_FAIBLE_CONFIANCE = "capture_faible_confiance"
DEPLOIEMENT = "deploiement"


@dataclass
class Entree:
    horodatage: str
    evenement: str
    signal_declencheur: str
    valeur_observee: float | str | None
    seuil: float | str | None
    auteur: str
    version_livree: str
    empreinte: str
    details: dict = field(default_factory=dict)


def tracer(
    *,
    evenement: str,
    signal_declencheur: str,
    auteur: str,
    valeur_observee: float | str | None = None,
    seuil: float | str | None = None,
    **details: object,
) -> Entree:
    """Inscrit une decision au journal.

    `auteur` vaut « automatique » lorsqu'une boucle a decide seule, ou l'identite de la
    personne lorsqu'un bouton a ete actionne — c'est la distinction « par qui ou par quoi »
    demandee par le brief.
    """
    entree = Entree(
        horodatage=datetime.now(timezone.utc).isoformat(),
        evenement=evenement,
        signal_declencheur=signal_declencheur,
        valeur_observee=valeur_observee,
        seuil=seuil,
        auteur=auteur,
        version_livree=version_livree(),
        empreinte=empreinte_execution()["empreinte"],
        details=dict(details),
    )

    JOURNAL_PILOTAGE.parent.mkdir(parents=True, exist_ok=True)
    with _verrou, JOURNAL_PILOTAGE.open("a", encoding="utf-8") as fichier:
        fichier.write(json.dumps(asdict(entree), ensure_ascii=False) + "\n")

    return entree


def lire(limite: int | None = None) -> list[dict]:
    """Relit le journal, du plus recent au plus ancien."""
    if not JOURNAL_PILOTAGE.exists():
        return []

    with _verrou, JOURNAL_PILOTAGE.open(encoding="utf-8") as fichier:
        entrees = [json.loads(ligne) for ligne in fichier if ligne.strip()]

    entrees.reverse()
    return entrees[:limite] if limite else entrees
