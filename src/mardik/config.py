"""Source unique de verite pour les seuils, les chemins et l'identite de la version.

Toute constante chiffree du projet est definie ici et nulle part ailleurs : les gates de la
chaine, les regles de rollback et de promotion, et les tests s'y referent tous. Les valeurs
proviennent de `besoin_client.md`.
"""

from __future__ import annotations

import hashlib
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
    """Etiquette de la version de **code** — injectee au build par la chaine LLMOps.

    Repli sur `RENDER_GIT_COMMIT` pour l'hebergement de demonstration, qui construit
    l'image lui-meme et ne passe donc pas par l'argument de build : l'etiquette reste
    ainsi rattachee au commit reellement deploye, jamais a une valeur saisie a la main.
    """
    if etiquette := os.getenv("MARDIK_VERSION"):
        return etiquette
    if commit := os.getenv("RENDER_GIT_COMMIT"):
        return f"render-{commit[:7]}"
    return "dev-local"


def empreinte_config() -> str:
    """Empreinte des seuils qui gouvernent le comportement en production.

    Deux deploiements du meme code avec des seuils differents ne se comportent pas
    pareil : ils ne doivent donc pas porter la meme identite. Seules les constantes qui
    changent une decision entrent dans l'empreinte.
    """
    gouvernantes = sorted(
        (nom, valeur)
        for nom, valeur in vars(Seuils).items()
        if not nom.startswith("_") and isinstance(valeur, (int, float, tuple))
    )
    brut = ";".join(f"{nom}={valeur}" for nom, valeur in gouvernantes)
    return "cfg-" + hashlib.sha256(brut.encode()).hexdigest()[:8]


def empreinte_execution() -> dict[str, str]:
    """Identite complete de ce qui tourne : **code + modele + configuration**.

    Le brief exige qu'une fusion produise « une version etiquetee (code + modele +
    config) ». L'etiquette de code seule ne suffit pas : changer le modele ou un seuil
    modifie le comportement sans changer le commit. `empreinte` resume les trois et
    change des que l'un d'eux bouge — c'est elle qui accompagne chaque signal et chaque
    entree du journal, donc elle qui permet d'attribuer un comportement a une identite.
    """
    code = version_livree()
    modele = "factice" if config.mardik_fake_llm else config.azure_ai_model
    conf = empreinte_config()
    resume = hashlib.sha256(f"{code}|{modele}|{conf}".encode()).hexdigest()[:8]

    return {
        "code": code,
        "modele": modele,
        "config": conf,
        "empreinte": f"v-{resume}",
    }


config = Config()
