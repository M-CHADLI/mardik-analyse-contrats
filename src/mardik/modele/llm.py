"""Acces au moteur de langage, avec un moteur factice deterministe interchangeable.

Le moteur factice n'est pas un bouchon de test : c'est ce qui permet au gate d'evaluation
et aux tests d'acceptance de s'executer en integration continue sans cle d'API, sans cout
et sans variabilite. Le vrai moteur se branche en basculant `MARDIK_FAKE_LLM=0`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import httpx

from mardik.config import CLAUSES_ATTENDUES, config


class ErreurMoteur(RuntimeError):
    """Le moteur de langage n'a pas pu produire d'analyse exploitable."""


@dataclass
class AnalyseSegment:
    """Ce que le moteur extrait d'un segment de contrat."""

    clauses: dict[str, str] = field(default_factory=dict)
    autoevaluation: float = 0.0
    tokens: int = 0


# Vocabulaire juridique servant au moteur factice. Volontairement explicite : c'est aussi
# la definition operationnelle de « clause trouvee » utilisee par le jeu d'evaluation.
# Normalisation du vocabulaire : on ne conserve que l'orthographe accentuee, correcte
# en francais, pour alleger la liste devenue difficile a maintenir.
INDICES_CLAUSES: dict[str, tuple[str, ...]] = {
    "duree": ("durée", "échéance", "entre en vigueur"),
    "resiliation": ("résilia", "préavis", "dénonc"),
    "paiement": ("règlement", "pénalité"),
    "responsabilite": ("préjudice", "indemnisation"),
    "confidentialite": ("confidentialité", "divulgation à"),
}

PROMPT = (
    "Tu analyses un extrait de contrat commercial. Repere les clauses suivantes : "
    + ", ".join(CLAUSES_ATTENDUES)
    + ". Reponds uniquement en JSON avec les cles 'clauses' (objet clause -> citation "
    "courte, uniquement les clauses reellement presentes) et 'autoevaluation' (nombre "
    "entre 0 et 1 exprimant ta certitude). Extrait :\n\n"
)


def _analyser_factice(texte: str) -> AnalyseSegment:
    """Analyse deterministe par reperage de vocabulaire juridique.

    L'autoevaluation est derivee de la densite d'indices trouves, ce qui rend le score de
    confiance reproductible : c'est la condition pour qu'une derive simulee declenche le
    rollback de facon fiable, et non au hasard.
    """
    minuscules = texte.lower()
    clauses: dict[str, str] = {}

    for clause, indices in INDICES_CLAUSES.items():
        for indice in indices:
            position = minuscules.find(indice)
            if position == -1:
                continue
            debut = max(0, position - 40)
            clauses[clause] = texte[debut : position + 120].strip()
            break

    densite = len(clauses) / len(CLAUSES_ATTENDUES)
    # Un segment tres court ou tres bruite inspire moins de confiance au modele.
    lisibilite = min(1.0, len(re.findall(r"[a-zA-ZÀ-ÿ]{4,}", texte)) / 80)
    autoevaluation = round(min(1.0, 0.45 * densite + 0.55 * lisibilite), 3)

    return AnalyseSegment(
        clauses=clauses,
        autoevaluation=autoevaluation,
        tokens=max(1, len(texte) // 4),
    )


def _analyser_distant(texte: str) -> AnalyseSegment:
    """Appelle le moteur de langage distant (Azure AI Inference, format OpenAI)."""
    if not config.llm_configure:
        raise ErreurMoteur("AZURE_AI_ENDPOINT ou AZURE_AI_API_KEY absent de l'environnement")

    charge = {
        "model": config.azure_ai_model,
        "messages": [{"role": "user", "content": PROMPT + texte}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    try:
        reponse = httpx.post(
            f"{config.azure_ai_endpoint.rstrip('/')}/chat/completions",
            headers={
                "api-key": config.azure_ai_api_key,
                "Authorization": f"Bearer {config.azure_ai_api_key}",
                "Content-Type": "application/json",
            },
            json=charge,
            timeout=config.mardik_llm_timeout_s,
        )
        reponse.raise_for_status()
        corps = reponse.json()
        brut = json.loads(corps["choices"][0]["message"]["content"])
    except httpx.TimeoutException as erreur:
        raise ErreurMoteur(f"delai depasse ({config.mardik_llm_timeout_s} s)") from erreur
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError) as erreur:
        raise ErreurMoteur(f"reponse inexploitable du moteur : {erreur}") from erreur

    clauses = {
        cle: str(valeur)
        for cle, valeur in (brut.get("clauses") or {}).items()
        if cle in CLAUSES_ATTENDUES and valeur
    }
    usage = corps.get("usage") or {}

    return AnalyseSegment(
        clauses=clauses,
        autoevaluation=float(brut.get("autoevaluation") or 0.0),
        tokens=int(usage.get("total_tokens") or max(1, len(texte) // 4)),
    )


def analyser_segment(texte: str) -> AnalyseSegment:
    """Point d'entree unique : route vers le moteur factice ou le moteur distant."""
    if config.mardik_fake_llm:
        return _analyser_factice(texte)
    return _analyser_distant(texte)
