"""Source unique de verite pour les seuils, les chemins et l'identite de la version.

Toute constante chiffree du projet est definie ici et nulle part ailleurs : les gates de la
chaine, les regles de rollback et de promotion, et les tests s'y referent tous. Les valeurs
proviennent de `besoin_client.md`.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RACINE = Path(__file__).resolve().parents[2]
DOSSIER_DONNEES = RACINE / "donnees"
DOSSIER_EVAL = RACINE / "eval"

JOURNAL_PILOTAGE = DOSSIER_DONNEES / "journal.jsonl"
SIGNAUX = DOSSIER_DONNEES / "signaux.jsonl"
FILE_VALIDATION = DOSSIER_DONNEES / "file_validation.jsonl"
ETAT_CANARY = DOSSIER_DONNEES / "etat_canary.json"
GOLDEN = DOSSIER_EVAL / "golden.jsonl"

CLAUSES_ATTENDUES = (
    "duree",
    "resiliation",
    "paiement",
    "responsabilite",
    "confidentialite",
)


class Seuils:
    """Contraintes issues de `besoin_client.md`, section 3 et 4."""

    TAILLE_MAX_CONTRAT = 150_000
    TRONCATURE_V1 = 8_000

    LATENCE_P95_MAX_S = 20.0
    COUT_MAX_EUR = 0.05

    FAIBLE_CONFIANCE = 0.60
    GATE_EVALUATION = 0.70
    COUVERTURE_MIN = 0.95

    # Rollback : une seule condition vraie suffit, sur une fenetre de N requetes v2.
    FENETRE_ROLLBACK = 20
    ROLLBACK_LATENCE_P95_S = 30.0
    ROLLBACK_TAUX_ERREUR = 0.05
    ROLLBACK_PART_FAIBLE_CONFIANCE = 0.25

    # Promotion canary : paliers successifs et taille de la fenetre d'observation.
    PALIERS_CANARY = (0, 10, 50, 100)
    FENETRE_PROMOTION = 50


class Config(BaseSettings):
    """Configuration lue depuis l'environnement (fichier `.env` en developpement)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"

    mardik_fake_llm: bool = True
    azure_ai_endpoint: str = ""
    azure_ai_api_key: str = ""
    azure_ai_model: str = "Kimi-K2.6"
    mardik_llm_timeout_s: float = 30.0

    mardik_otel_actif: bool = False
    otel_service_name: str = "mardik-contrats"
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    mardik_canary_v2: int = 0

    @property
    def llm_configure(self) -> bool:
        return bool(self.azure_ai_endpoint and self.azure_ai_api_key)


def version_livree() -> str:
    """Identifiant de la version servie — injecte au build par la chaine LLMOps.

    C'est cet identifiant qui rend verifiable l'exigence « on peut identifier quelle
    version sert quel trafic » : il apparait dans chaque reponse d'API, chaque metrique
    et chaque entree du journal de pilotage.
    """
    return os.getenv("MARDIK_VERSION", "dev-local")


config = Config()
