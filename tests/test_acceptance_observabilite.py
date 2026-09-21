"""Tests d'acceptance — « L'observabilite qui pilote » (brief, criteres de performance).

Ces cinq tests verifient que l'observabilite ne se contente pas d'afficher : elle decide.
"""

from __future__ import annotations

import json

from conftest import entrees_journal
from mardik.api import canary
from mardik.boucles import enrichissement, promotion, rollback
from mardik.config import Seuils
from mardik.observabilite import journal, signaux


def _deployer_canary(poids: int) -> None:
    canary.definir_poids(
        poids,
        evenement=journal.DEPLOIEMENT,
        signal_declencheur="test",
        auteur="test",
    )


def test_derive_du_score_declenche_un_rollback_trace(client, contrat_bruite):
    """Derive simulee du score de confiance → rollback via la chaine + evenement trace."""
    _deployer_canary(100)

    # Le simulateur envoie des documents degrades : le score de confiance s'effondre.
    for _ in range(Seuils.FENETRE_ROLLBACK):
        assert client.post("/analyser", json={"contrat": contrat_bruite}).status_code == 200

    fenetre = signaux.lire(limite=Seuils.FENETRE_ROLLBACK, version_modele="v2")
    assert signaux.agreger(fenetre)["part_faible_confiance"] > Seuils.ROLLBACK_PART_FAIBLE_CONFIANCE

    # Le trafic est revenu a la v1 et la promotion est gelee.
    etat = canary.etat()
    assert etat["poids_v2"] == 0
    assert etat["gele"] is True

    trace = next(e for e in entrees_journal() if e["evenement"] == journal.ROLLBACK)
    assert trace["signal_declencheur"] == "part_faible_confiance"
    assert trace["auteur"] == "automatique"
    assert trace["valeur_observee"] > trace["seuil"]
    assert trace["details"]["poids_v2_apres"] == 0


def test_promotion_conditionnee_aux_metriques_canary(etat_isole):
    """Metriques conformes → la v2 est promue ; metriques non conformes → pas de promotion."""
    promotion.REFERENCE.write_text(json.dumps({"score_moyen": 0.75}), encoding="utf-8")
    _deployer_canary(10)

    def remplir_fenetre(score: float, latence_ms: float = 500.0) -> None:
        for index in range(Seuils.FENETRE_PROMOTION):
            signaux.enregistrer(
                version_modele="v2",
                latence_ms=latence_ms,
                tokens=1000,
                requete_id=f"r{index}",
                score_confiance=score,
            )

    # Fenetre incomplete : aucune promotion, on n'avance pas sans preuve suffisante.
    signaux.enregistrer(
        version_modele="v2", latence_ms=500, tokens=10, requete_id="seul", score_confiance=0.9
    )
    assert promotion.evaluer() is None
    assert canary.etat()["poids_v2"] == 10

    # Fenetre complete et metriques conformes : promotion au palier suivant.
    remplir_fenetre(score=0.90)
    assert promotion.evaluer() is not None
    assert canary.etat()["poids_v2"] == 50

    trace = next(e for e in entrees_journal() if e["evenement"] == journal.PROMOTION)
    assert trace["signal_declencheur"] == "score_moyen"
    assert trace["details"]["poids_v2_apres"] == 50


def test_promotion_refusee_si_metriques_non_conformes(etat_isole):
    """Metriques non conformes a l'issue de la fenetre → la promotion n'a pas lieu."""
    promotion.REFERENCE.write_text(json.dumps({"score_moyen": 0.85}), encoding="utf-8")
    _deployer_canary(10)

    # Score durablement sous la reference mesuree au gate : la v2 ne merite pas plus de trafic.
    for index in range(Seuils.FENETRE_PROMOTION):
        signaux.enregistrer(
            version_modele="v2",
            latence_ms=500,
            tokens=1000,
            requete_id=f"r{index}",
            score_confiance=0.70,
        )

    assert promotion.evaluer() is None
    assert canary.etat()["poids_v2"] == 10

    refus = next(e for e in entrees_journal() if e["evenement"] == "promotion_refusee")
    assert refus["valeur_observee"] < refus["seuil"]


def test_cas_a_faible_confiance_rejoue_par_le_gate(client, contrat_bruite, tmp_path, monkeypatch):
    """Cas de production a faible confiance capture → entre au jeu d'eval → rejoue au gate."""
    reponse = client.post("/v2/analyser", json={"contrat": contrat_bruite})
    assert reponse.json()["score_confiance"] < Seuils.FAIBLE_CONFIANCE

    # 1. Il est capture et attend une relecture humaine.
    attente = enrichissement.file_attente()
    assert len(attente) == 1
    cas_id = attente[0]["id"]

    capture = next(
        e for e in entrees_journal() if e["evenement"] == journal.CAPTURE_FAIBLE_CONFIANCE
    )
    assert capture["details"]["cas_id"] == cas_id

    # 2. Un juriste le relit et le verse au jeu d'evaluation.
    enrichissement.valider(cas_id, ["duree", "paiement"], auteur="juriste.test")
    assert enrichissement.file_attente() == []

    verses = [
        json.loads(ligne)
        for ligne in enrichissement.GOLDEN.read_text(encoding="utf-8").splitlines()
        if ligne.strip()
    ]
    assert [c["id"] for c in verses] == [cas_id]
    assert verses[0]["origine"] == "production"
    assert verses[0]["valide_par"] == "juriste.test"

    # 3. Le gate le rejoue a la fusion suivante, au meme titre que les cas initiaux.
    from eval import evaluer as module_gate

    monkeypatch.setattr(module_gate, "GOLDEN", enrichissement.GOLDEN)
    bilan = module_gate.evaluer()
    assert bilan["cas_production"] == 1
    assert cas_id in [resultat["id"] for resultat in bilan["resultats"]]


def test_tableau_de_bord_expose_les_cinq_signaux(client, contrat_long, contrat_bruite):
    """Le tableau de bord montre latence, cout, erreurs, distribution du score, part v1/v2."""
    _deployer_canary(100)
    client.post("/analyser", json={"contrat": contrat_long})
    client.post("/analyser", json={"contrat": contrat_bruite})
    _deployer_canary(0)
    client.post("/analyser", json={"contrat": contrat_long})

    tableau = client.get("/api/signaux").json()

    assert tableau["global"]["latence_moyenne_ms"] > 0  # 1. latence
    assert tableau["global"]["cout_total_eur"] > 0  # 2. cout
    assert "taux_erreur" in tableau["global"]  # 3. taux d'erreur
    assert sum(p["effectif"] for p in tableau["distribution_scores"]) == 2  # 4. distribution
    part = tableau["part_trafic"]  # 5. part v1/v2
    assert part["total"] == 3
    assert part["v1"] > 0 and part["v2"] > 0
    assert abs(part["v1"] + part["v2"] - 1.0) < 1e-6

    assert tableau["seuils"]["faible_confiance"] == Seuils.FAIBLE_CONFIANCE


def test_journal_trace_tout_ajustement_avec_son_signal(client, contrat_long):
    """Le journal de pilotage porte chaque ajustement avec le signal qui l'a declenche."""
    _deployer_canary(50)
    client.post("/analyser", json={"contrat": contrat_long})
    rollback.declencher_manuellement("mehdi", "doute sur la qualite des extractions")

    entrees = client.get("/api/journal").json()["entrees"]
    assert len(entrees) >= 2

    for entree in entrees:
        assert entree["signal_declencheur"], "aucune decision sans signal declencheur"
        assert entree["auteur"], "aucune decision sans auteur"
        assert entree["horodatage"]
        assert entree["version_livree"]

    manuel = next(e for e in entrees if e["auteur"] == "mehdi")
    assert manuel["evenement"] == journal.ROLLBACK
    assert manuel["signal_declencheur"] == "decision_humaine"
    assert manuel["details"]["poids_v2_avant"] == 50
    assert manuel["details"]["poids_v2_apres"] == 0

    # « par qui ou par quoi » : les deux origines sont distinguables au journal.
    auteurs = {e["auteur"] for e in entrees}
    assert "mehdi" in auteurs
