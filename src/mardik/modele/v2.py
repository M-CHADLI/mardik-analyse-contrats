"""Modele v2 — decoupe le contrat entier et produit un score de confiance explicable.

Deux corrections par rapport a la v1 :

1. **Documents longs** — le contrat est segmente, chaque segment analyse, puis les clauses
   sont agregees. La part du texte reellement analysee devient une grandeur mesurable.
2. **Score de confiance** — composite et majoritairement deterministe, pour qu'il soit
   explicable a un juriste et reproductible en test. Une note purement auto-declaree par
   le modele serait mal calibree et rendrait la demonstration de derive aleatoire.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mardik.config import CLAUSES_ATTENDUES, Seuils
from mardik.modele.llm import AnalyseSegment, ErreurMoteur, analyser_segment

TAILLE_SEGMENT = 6_000
RECOUVREMENT = 400

# Ponderation du score de confiance. La part deterministe (couverture + completude) pese
# 75 % : c'est ce qui rend le score reproductible et opposable.
POIDS_COUVERTURE = 0.40
POIDS_COMPLETUDE = 0.35
POIDS_AUTOEVALUATION = 0.25


@dataclass
class ResultatV2:
    clauses: dict[str, str]
    score_confiance: float
    couverture: float
    completude: float
    autoevaluation: float
    segments_analyses: int
    segments_total: int
    tokens: int
    clauses_manquantes: list[str] = field(default_factory=list)

    @property
    def fiable(self) -> bool:
        return self.score_confiance >= Seuils.FAIBLE_CONFIANCE


def segmenter(contrat: str) -> list[str]:
    """Decoupe avec recouvrement, pour qu'une clause a cheval sur deux segments survive."""
    if len(contrat) <= TAILLE_SEGMENT:
        return [contrat]

    segments: list[str] = []
    debut = 0
    while debut < len(contrat):
        segments.append(contrat[debut : debut + TAILLE_SEGMENT])
        debut += TAILLE_SEGMENT - RECOUVREMENT
    return segments


def analyser(contrat: str) -> ResultatV2:
    """Analyse l'integralite du contrat et calcule le score de confiance composite."""
    segments = segmenter(contrat)
    clauses: dict[str, str] = {}
    analyses: list[AnalyseSegment] = []
    caracteres_analyses = 0
    tokens = 0

    for segment in segments:
        try:
            analyse = analyser_segment(segment)
        except ErreurMoteur:
            # Un segment perdu n'invalide pas l'analyse : il fait chuter la couverture,
            # donc le score de confiance, ce qui est precisement le signal attendu.
            continue

        analyses.append(analyse)
        caracteres_analyses += len(segment)
        tokens += analyse.tokens
        for clause, extrait in analyse.clauses.items():
            clauses.setdefault(clause, extrait)

    couverture = min(1.0, caracteres_analyses / len(contrat)) if contrat else 0.0
    completude = len(clauses) / len(CLAUSES_ATTENDUES)
    autoevaluation = sum(a.autoevaluation for a in analyses) / len(analyses) if analyses else 0.0

    score = (
        POIDS_COUVERTURE * couverture
        + POIDS_COMPLETUDE * completude
        + POIDS_AUTOEVALUATION * autoevaluation
    )

    return ResultatV2(
        clauses=clauses,
        score_confiance=round(score, 3),
        couverture=round(couverture, 3),
        completude=round(completude, 3),
        autoevaluation=round(autoevaluation, 3),
        segments_analyses=len(analyses),
        segments_total=len(segments),
        tokens=tokens,
        clauses_manquantes=[c for c in CLAUSES_ATTENDUES if c not in clauses],
    )
