"""Contrats d'API.

Regle structurante : `ReponseV2` est un **sur-ensemble strict** de `ReponseV1`. Un client
ecrit pour la v1 lit `clauses` et `version_modele` ; s'il est route vers la v2 par le
canary, il recoit ces memes champs plus les nouveaux, qu'il ignore. La compatibilite
ascendante est donc garantie par la forme du contrat, pas par un aiguillage de faveur.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mardik.config import Seuils


class Requete(BaseModel):
    contrat: str = Field(
        ...,
        min_length=1,
        description="Texte brut du contrat a analyser.",
    )
    reference: str | None = Field(
        default=None,
        description="Reference libre du client, reprise telle quelle dans la reponse.",
    )


class ReponseV1(BaseModel):
    """Contrat historique. Fige : aucun champ ne peut en etre retire ni renomme."""

    clauses: dict[str, str]
    version_modele: str
    version_livree: str
    reference: str | None = None


class ReponseV2(ReponseV1):
    """Ajoute l'indice de fiabilite et ses composantes, sans rien retirer."""

    score_confiance: float = Field(..., ge=0, le=1)
    fiable: bool = Field(
        ...,
        description=f"Faux si le score est sous le seuil de {Seuils.FAIBLE_CONFIANCE}.",
    )
    couverture: float = Field(..., ge=0, le=1, description="Part du contrat analysee.")
    completude: float = Field(..., ge=0, le=1, description="Part des clauses attendues trouvees.")
    clauses_manquantes: list[str]
    segments_analyses: int
    segments_total: int


class Erreur(BaseModel):
    """Erreur explicite : un code stable et un message lisible, jamais une trace brute."""

    code: str
    message: str
    detail: str | None = None
