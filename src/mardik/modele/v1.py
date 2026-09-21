"""Modele v1 — la generation historique, figee.

Ses deux defauts sont intentionnels et documentes dans `besoin_client.md` : elle tronque
le document a 8 000 caracteres sans le signaler, et ne produit aucun indice de fiabilite.
Ce module ne doit pas evoluer : `scripts/client_v1.py` en est le temoin executable.
"""

from __future__ import annotations

from dataclasses import dataclass

from mardik.config import Seuils
from mardik.modele.llm import analyser_segment


@dataclass
class ResultatV1:
    clauses: dict[str, str]
    tokens: int


def analyser(contrat: str) -> ResultatV1:
    """Analyse le debut du contrat uniquement, sans indiquer ce qui a ete ignore."""
    debut = contrat[: Seuils.TRONCATURE_V1]
    analyse = analyser_segment(debut)
    return ResultatV1(clauses=analyse.clauses, tokens=analyse.tokens)
