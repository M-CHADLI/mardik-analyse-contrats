"""Application HTTP : les deux generations de modele derriere une passerelle canary.

Trois points d'entree d'analyse :

- `POST /analyser` — reparti par le canary, c'est celui que consomment les clients.
- `POST /v1/analyser` et `POST /v2/analyser` — forcent une generation, pour le jeu
  d'evaluation et les tests d'acceptance.

Une requete servie par la v2 declenche, dans l'ordre : l'enregistrement du signal, la
capture eventuelle pour enrichissement, puis l'evaluation des boucles de rollback et de
promotion. C'est ici, et nulle part ailleurs, que l'observabilite pilote la chaine.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from mardik.api import canary, schemas
from mardik.boucles import enrichissement, promotion, rollback
from mardik.config import CLAUSES_ATTENDUES, Seuils, config, version_livree
from mardik.modele import v1, v2
from mardik.modele.llm import ErreurMoteur
from mardik.observabilite import journal, signaux, telemetrie

WEB = Path(__file__).resolve().parents[3] / "web"

telemetrie.initialiser()

app = FastAPI(
    title="Mardik — analyse de contrats",
    version=version_livree(),
    description="API v1 (figee) et v2 (documents longs + score de confiance).",
)


def _erreur(statut: int, code: str, message: str, detail: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=statut,
        content=schemas.Erreur(code=code, message=message, detail=detail).model_dump(),
    )


def _valider(contrat: str) -> JSONResponse | None:
    if not contrat.strip():
        return _erreur(400, "CONTRAT_VIDE", "Le champ 'contrat' ne peut pas etre vide.")
    if len(contrat) > Seuils.TAILLE_MAX_CONTRAT:
        return _erreur(
            413,
            "CONTRAT_TROP_LONG",
            f"Le contrat depasse la taille maximale de {Seuils.TAILLE_MAX_CONTRAT} caracteres.",
            detail=f"taille recue : {len(contrat)}",
        )
    return None


def _repondre_v1(
    resultat: v1.ResultatV1,
    requete: schemas.Requete,
    requete_id: str,
    latence_ms: float,
) -> schemas.ReponseV1:
    signaux.enregistrer(
        version_modele="v1",
        latence_ms=latence_ms,
        tokens=resultat.tokens,
        requete_id=requete_id,
    )
    return schemas.ReponseV1(
        clauses=resultat.clauses,
        version_modele="v1",
        version_livree=version_livree(),
        reference=requete.reference,
    )


def _repondre_v2(
    resultat: v2.ResultatV2,
    requete: schemas.Requete,
    requete_id: str,
    latence_ms: float,
) -> schemas.ReponseV2:
    """Enregistre le signal, puis laisse les boucles decider de la suite.

    L'ordre compte : le signal doit etre ecrit avant que les boucles ne relisent la
    fenetre, sinon la requete courante serait absente de leur diagnostic.
    """
    signaux.enregistrer(
        version_modele="v2",
        latence_ms=latence_ms,
        tokens=resultat.tokens,
        requete_id=requete_id,
        score_confiance=resultat.score_confiance,
    )

    enrichissement.capturer(
        requete.contrat,
        score=resultat.score_confiance,
        clauses_trouvees=sorted(resultat.clauses),
        requete_id=requete_id,
    )
    # Un rollback rend la promotion sans objet : on ne relance pas la montee en trafic
    # dans le meme cycle que le retour arriere.
    if rollback.evaluer() is None:
        promotion.evaluer()

    return schemas.ReponseV2(
        clauses=resultat.clauses,
        version_modele="v2",
        version_livree=version_livree(),
        reference=requete.reference,
        score_confiance=resultat.score_confiance,
        fiable=resultat.fiable,
        couverture=resultat.couverture,
        completude=resultat.completude,
        clauses_manquantes=resultat.clauses_manquantes,
        segments_analyses=resultat.segments_analyses,
        segments_total=resultat.segments_total,
    )


def _servir(
    version: str, requete: schemas.Requete
) -> schemas.ReponseV1 | schemas.ReponseV2 | JSONResponse:
    requete_id = str(uuid.uuid4())[:12]
    debut = time.perf_counter()

    with telemetrie.span(
        "analyse_contrat",
        **{
            "mardik.version_modele": version,
            "mardik.version_livree": version_livree(),
            "mardik.taille_contrat": len(requete.contrat),
            "mardik.requete_id": requete_id,
        },
    ):
        try:
            if version == "v1":
                brut_v1 = v1.analyser(requete.contrat)
                latence_ms = (time.perf_counter() - debut) * 1000
                return _repondre_v1(brut_v1, requete, requete_id, latence_ms)

            brut_v2 = v2.analyser(requete.contrat)
            latence_ms = (time.perf_counter() - debut) * 1000
            return _repondre_v2(brut_v2, requete, requete_id, latence_ms)

        except ErreurMoteur as erreur:
            signaux.enregistrer(
                version_modele=version,
                latence_ms=(time.perf_counter() - debut) * 1000,
                tokens=0,
                requete_id=requete_id,
                erreur=True,
                code_erreur="MOTEUR_INDISPONIBLE",
            )
            # Une panne du moteur est elle aussi un signal : elle alimente le taux
            # d'erreur qui peut declencher le rollback.
            if version == "v2":
                rollback.evaluer()
            return _erreur(
                503,
                "MOTEUR_INDISPONIBLE",
                "Le moteur d'analyse n'a pas pu traiter la demande.",
                detail=str(erreur),
            )


@app.post("/analyser", summary="Analyse repartie par le canary")
def analyser(requete: schemas.Requete):
    if (probleme := _valider(requete.contrat)) is not None:
        return probleme
    return _servir(canary.choisir_version(), requete)


@app.post("/v1/analyser", response_model=schemas.ReponseV1, summary="Force la generation v1")
def analyser_v1(requete: schemas.Requete):
    if (probleme := _valider(requete.contrat)) is not None:
        return probleme
    return _servir("v1", requete)


@app.post("/v2/analyser", response_model=schemas.ReponseV2, summary="Force la generation v2")
def analyser_v2(requete: schemas.Requete):
    if (probleme := _valider(requete.contrat)) is not None:
        return probleme
    return _servir("v2", requete)


@app.get("/sante", summary="Sonde de vivacite")
def sante():
    return {
        "statut": "ok",
        "version_livree": version_livree(),
        "moteur": "factice" if config.mardik_fake_llm else config.azure_ai_model,
        "canary": canary.etat(),
    }


@app.get("/api/signaux", summary="Les cinq signaux du tableau de bord")
def api_signaux(fenetre: int = 200):
    recents = signaux.lire(limite=fenetre)
    return {
        "global": signaux.agreger(recents),
        "v1": signaux.agreger(signaux.lire(limite=fenetre, version_modele="v1")),
        "v2": signaux.agreger(signaux.lire(limite=fenetre, version_modele="v2")),
        "part_trafic": signaux.part_trafic(),
        "distribution_scores": signaux.distribution_scores(),
        "seuils": {
            "faible_confiance": Seuils.FAIBLE_CONFIANCE,
            "latence_p95_max_s": Seuils.LATENCE_P95_MAX_S,
            "rollback_latence_p95_s": Seuils.ROLLBACK_LATENCE_P95_S,
            "rollback_taux_erreur": Seuils.ROLLBACK_TAUX_ERREUR,
            "rollback_part_faible_confiance": Seuils.ROLLBACK_PART_FAIBLE_CONFIANCE,
        },
        "version_livree": version_livree(),
    }


@app.get("/api/journal", summary="Journal de pilotage")
def api_journal(limite: int = 50):
    return {"entrees": journal.lire(limite=limite)}


@app.get("/api/canary", summary="Etat de la repartition du trafic")
def api_canary():
    etat = canary.etat()
    return {
        **etat,
        "palier_suivant": canary.palier_suivant(etat["poids_v2"]),
        "paliers": list(Seuils.PALIERS_CANARY),
    }


@app.post("/api/canary/poids", summary="Fixe la repartition (deploiement manuel)")
def api_definir_poids(
    poids: int = Body(..., embed=True),
    auteur: str = Body("operateur", embed=True),
):
    return canary.definir_poids(
        poids,
        evenement=journal.DEPLOIEMENT,
        signal_declencheur="decision_humaine",
        auteur=auteur,
        valeur_observee=poids,
    )


@app.post("/api/canary/rollback", summary="Bouton de rollback")
def api_rollback(
    auteur: str = Body("operateur", embed=True),
    motif: str = Body("rollback manuel depuis le tableau de bord", embed=True),
):
    return rollback.declencher_manuellement(auteur, motif)


@app.post("/api/canary/promouvoir", summary="Force l'evaluation de la promotion")
def api_promouvoir(auteur: str = Body("operateur", embed=True)):
    resultat = promotion.evaluer(auteur=auteur)
    if resultat is None:
        return {"promu": False, "etat": canary.etat()}
    return {"promu": True, "etat": resultat}


@app.get("/api/validation", summary="Cas a faible confiance en attente de relecture")
def api_validation():
    return {"clauses_possibles": list(CLAUSES_ATTENDUES), "cas": enrichissement.file_attente()}


@app.post("/api/validation/{cas_id}", summary="Verse un cas relu dans le jeu d'evaluation")
def api_valider(
    cas_id: str,
    clauses_attendues: list[str] = Body(..., embed=True),
    auteur: str = Body("juriste", embed=True),
):
    try:
        return enrichissement.valider(cas_id, clauses_attendues, auteur)
    except KeyError:
        return _erreur(404, "CAS_INCONNU", f"Aucun cas capture avec l'identifiant {cas_id}.")


@app.get("/", include_in_schema=False)
def accueil(request: Request):
    page = WEB / "index.html"
    return FileResponse(page) if page.exists() else {"api": "mardik", "documentation": "/docs"}


@app.get("/tableau-de-bord", include_in_schema=False)
def tableau_de_bord():
    page = WEB / "tableau-de-bord.html"
    return FileResponse(page) if page.exists() else {"erreur": "tableau de bord absent"}


if WEB.exists():
    app.mount("/static", StaticFiles(directory=WEB), name="static")
