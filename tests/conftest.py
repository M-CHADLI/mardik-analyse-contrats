"""Fixtures communes.

Chaque test s'execute sur des fichiers d'etat isoles : signaux, journal, etat du canary,
file de validation et jeu d'evaluation sont rediriges vers un dossier temporaire. Sans
cela, un test polluerait la production locale et les tests deviendraient dependants de
leur ordre d'execution.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mardik.api import canary
from mardik.boucles import enrichissement, promotion
from mardik.observabilite import journal, signaux

RACINE = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def etat_isole(tmp_path, monkeypatch):
    """Redirige tous les fichiers d'etat vers un dossier temporaire."""
    monkeypatch.setattr(signaux, "SIGNAUX", tmp_path / "signaux.jsonl")
    monkeypatch.setattr(journal, "JOURNAL_PILOTAGE", tmp_path / "journal.jsonl")
    monkeypatch.setattr(canary, "ETAT_CANARY", tmp_path / "etat_canary.json")
    monkeypatch.setattr(enrichissement, "FILE_VALIDATION", tmp_path / "file_validation.jsonl")
    monkeypatch.setattr(enrichissement, "GOLDEN", tmp_path / "golden.jsonl")
    monkeypatch.setattr(promotion, "REFERENCE", tmp_path / "reference_gate.json")
    return tmp_path


@pytest.fixture
def client():
    from mardik.api.app import app

    return TestClient(app)


@pytest.fixture
def contrat_long() -> str:
    """Contrat de plus de 15 000 caracteres dont les clauses sont hors de portee de la v1."""
    from eval.generer_golden import CLAUSES, composer

    return composer(list(CLAUSES), blocs_remplissage=12)


@pytest.fixture
def contrat_bruite() -> str:
    """Document long sans vocabulaire juridique : la v2 doit y perdre confiance."""
    return "lorem ipsum dolor sit amet " * 900


def entrees_journal() -> list[dict]:
    chemin = journal.JOURNAL_PILOTAGE
    if not chemin.exists():
        return []
    with chemin.open(encoding="utf-8") as fichier:
        return [json.loads(ligne) for ligne in fichier if ligne.strip()]
