"""Les cinq signaux imposes par le brief : latence, cout, erreurs, score, part v1/v2.

Chaque requete servie depose une ligne dans `donnees/signaux.jsonl`. C'est la matiere
premiere du tableau de bord et des deux boucles pilotees par les metriques (rollback et
promotion) : ces boucles ne lisent jamais autre chose que ces lignes.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from mardik.config import SIGNAUX, Seuils, empreinte_execution, version_livree

# Tarif indicatif, aligne sur l'ordre de grandeur d'un modele de la classe utilisee.
EUROS_PAR_1K_TOKENS = 0.0012

_verrou = threading.Lock()


@dataclass
class Signal:
    horodatage: str
    version_modele: str
    version_livree: str
    # Identite complete de ce qui a servi : code + modele + config. C'est elle qui rend
    # une requete attribuable a un comportement, et non seulement a un commit.
    empreinte: str
    latence_ms: float
    cout_eur: float
    erreur: bool
    code_erreur: str | None
    score_confiance: float | None
    requete_id: str


def cout(tokens: int) -> float:
    return round(tokens / 1000 * EUROS_PAR_1K_TOKENS, 6)


def enregistrer(
    *,
    version_modele: str,
    latence_ms: float,
    tokens: int,
    requete_id: str,
    erreur: bool = False,
    code_erreur: str | None = None,
    score_confiance: float | None = None,
) -> Signal:
    signal = Signal(
        horodatage=datetime.now(timezone.utc).isoformat(),
        version_modele=version_modele,
        version_livree=version_livree(),
        empreinte=empreinte_execution()["empreinte"],
        latence_ms=round(latence_ms, 2),
        cout_eur=cout(tokens),
        erreur=erreur,
        code_erreur=code_erreur,
        score_confiance=score_confiance,
        requete_id=requete_id,
    )

    SIGNAUX.parent.mkdir(parents=True, exist_ok=True)
    with _verrou, SIGNAUX.open("a", encoding="utf-8") as fichier:
        fichier.write(json.dumps(asdict(signal), ensure_ascii=False) + "\n")

    return signal


def lire(limite: int | None = None, version_modele: str | None = None) -> list[dict]:
    """Relit les signaux, du plus recent au plus ancien."""
    if not SIGNAUX.exists():
        return []

    with _verrou, SIGNAUX.open(encoding="utf-8") as fichier:
        lignes = [json.loads(ligne) for ligne in fichier if ligne.strip()]

    lignes.reverse()
    if version_modele:
        lignes = [ligne for ligne in lignes if ligne["version_modele"] == version_modele]
    return lignes[:limite] if limite else lignes


def _percentile(valeurs: list[float], rang: float) -> float:
    if not valeurs:
        return 0.0
    ordonnees = sorted(valeurs)
    index = min(len(ordonnees) - 1, int(rang * len(ordonnees)))
    return round(ordonnees[index], 2)


def agreger(lignes: list[dict]) -> dict:
    """Condense une fenetre de signaux en indicateurs decisionnels."""
    if not lignes:
        return {
            "requetes": 0,
            "latence_p95_ms": 0.0,
            "latence_moyenne_ms": 0.0,
            "cout_total_eur": 0.0,
            "taux_erreur": 0.0,
            "part_faible_confiance": 0.0,
            "score_moyen": 0.0,
        }

    latences = [ligne["latence_ms"] for ligne in lignes]
    scores = [ligne["score_confiance"] for ligne in lignes if ligne["score_confiance"] is not None]
    erreurs = sum(1 for ligne in lignes if ligne["erreur"])
    faibles = sum(1 for score in scores if score < Seuils.FAIBLE_CONFIANCE)

    return {
        "requetes": len(lignes),
        "latence_p95_ms": _percentile(latences, 0.95),
        "latence_moyenne_ms": round(sum(latences) / len(latences), 2),
        "cout_total_eur": round(sum(ligne["cout_eur"] for ligne in lignes), 6),
        "taux_erreur": round(erreurs / len(lignes), 4),
        "part_faible_confiance": round(faibles / len(scores), 4) if scores else 0.0,
        "score_moyen": round(sum(scores) / len(scores), 4) if scores else 0.0,
    }


def part_trafic() -> dict:
    """Repartition observee du trafic entre les deux generations de modele."""
    lignes = lire()
    total = len(lignes)
    if not total:
        return {"v1": 0.0, "v2": 0.0, "total": 0}

    v2 = sum(1 for ligne in lignes if ligne["version_modele"] == "v2")
    return {
        "v1": round((total - v2) / total, 4),
        "v2": round(v2 / total, 4),
        "total": total,
    }


def distribution_scores(paliers: int = 10) -> list[dict]:
    """Histogramme du score de confiance — un des cinq signaux exiges."""
    scores = [ligne["score_confiance"] for ligne in lire() if ligne["score_confiance"] is not None]
    histogramme = [0] * paliers
    for score in scores:
        index = min(paliers - 1, int(score * paliers))
        histogramme[index] += 1

    return [
        {"palier": f"{i / paliers:.1f}-{(i + 1) / paliers:.1f}", "effectif": effectif}
        for i, effectif in enumerate(histogramme)
    ]
