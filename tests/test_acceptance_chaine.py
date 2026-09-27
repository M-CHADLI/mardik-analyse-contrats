"""Tests d'acceptance — « La chaine LLMOps » (brief, criteres de performance).

Les cinq enonces du brief sont repris tels quels en docstring de chaque test.
"""

from __future__ import annotations

import json
from pathlib import Path

from mardik.api import canary
from mardik.config import Seuils
from mardik.observabilite import journal

RACINE = Path(__file__).resolve().parents[1]


def test_document_long_renvoie_un_score_de_confiance(client, contrat_long):
    """Requete valide avec un document long sur /v2 → contrat respecte + score de confiance."""
    assert len(contrat_long) > Seuils.TRONCATURE_V1

    reponse = client.post("/v2/analyser", json={"contrat": contrat_long})
    assert reponse.status_code == 200

    corps = reponse.json()
    assert 0.0 <= corps["score_confiance"] <= 1.0
    assert corps["version_modele"] == "v2"
    # Le contrat entier a ete analyse, pas seulement le debut comme le faisait la v1.
    assert corps["couverture"] >= Seuils.COUVERTURE_MIN
    assert corps["segments_analyses"] == corps["segments_total"] > 1
    for champ in ("clauses", "fiable", "completude", "clauses_manquantes", "version_livree"):
        assert champ in corps


def test_requete_invalide_erreur_explicite_sans_planter(client):
    """Requete invalide → erreur explicite (code + message), sans plantage."""
    cas = [
        ({"contrat": "   "}, 400, "CONTRAT_VIDE"),
        ({"contrat": "x" * (Seuils.TAILLE_MAX_CONTRAT + 1)}, 413, "CONTRAT_TROP_LONG"),
    ]
    for charge, statut, code in cas:
        reponse = client.post("/analyser", json=charge)
        assert reponse.status_code == statut
        corps = reponse.json()
        assert corps["code"] == code
        assert corps["message"]

    # Champ absent : rejete par la validation du schema, toujours sans exception serveur.
    assert client.post("/analyser", json={}).status_code == 422

    # Le service reste disponible apres les erreurs.
    assert client.get("/sante").status_code == 200


def test_client_v1_continue_de_fonctionner_sous_canary(client, contrat_long):
    """Le client v1 continue de fonctionner sans modification quand la v2 est en canary."""
    canary.definir_poids(
        100,
        evenement=journal.DEPLOIEMENT,
        signal_declencheur="test",
        auteur="test",
    )

    # Le client v1 ne connait que 'contrat' en entree et 'clauses' en sortie.
    reponse = client.post("/analyser", json={"contrat": contrat_long})
    assert reponse.status_code == 200

    corps = reponse.json()
    assert corps["version_modele"] == "v2", "le canary a bien route vers la v2"
    assert isinstance(corps["clauses"], dict), "le champ attendu par le client v1 est present"
    assert all(isinstance(valeur, str) for valeur in corps["clauses"].values())

    # La v2 ajoute des champs mais n'en retire aucun : c'est ce qui garantit la
    # compatibilite ascendante, independamment de la version qui a servi.
    from mardik.api.schemas import ReponseV1, ReponseV2

    assert set(ReponseV1.model_fields) <= set(ReponseV2.model_fields)
    ReponseV1.model_validate({k: corps[k] for k in ReponseV1.model_fields})


def test_version_etiquetee_identifiable(client, contrat_long, monkeypatch):
    """Une fusion publie une version etiquetee, et l'on identifie quelle version sert quel trafic."""
    monkeypatch.setenv("MARDIK_VERSION", "1.4.2-abc1234")

    reponse = client.post("/v2/analyser", json={"contrat": contrat_long})
    assert reponse.json()["version_livree"] == "1.4.2-abc1234"
    assert client.get("/sante").json()["version_livree"] == "1.4.2-abc1234"

    # Chaque signal porte la version livree et la generation de modele : on peut donc
    # attribuer n'importe quelle requete servie a une version precise.
    signaux = client.get("/api/signaux").json()
    assert signaux["version_livree"] == "1.4.2-abc1234"
    assert set(signaux["part_trafic"]) == {"v1", "v2", "total"}

    # La chaine qui produit cette etiquette est versionnee avec le code.
    chaine = RACINE / ".github" / "workflows" / "llmops.yml"
    assert chaine.exists(), "la chaine LLMOps doit etre dans le depot"
    contenu = chaine.read_text(encoding="utf-8")
    assert "MARDIK_VERSION" in contenu


def test_la_version_etiquetee_couvre_code_modele_et_config(monkeypatch):
    """« Toute fusion produit une version etiquetee (code + modele + config) ».

    L'etiquette de code seule ne suffit pas : deux deploiements du meme commit avec un
    modele ou un seuil different ne se comportent pas pareil et ne doivent donc pas
    partager la meme identite.
    """
    from mardik import config as module_config

    monkeypatch.setenv("MARDIK_VERSION", "main-abc1234")
    reference = module_config.empreinte_execution()

    assert set(reference) == {"code", "modele", "config", "empreinte"}
    assert reference["code"] == "main-abc1234"

    # Meme code, meme config, mais un autre modele : l'empreinte doit changer.
    monkeypatch.setattr(module_config.config, "mardik_fake_llm", False)
    monkeypatch.setattr(module_config.config, "azure_ai_model", "un-autre-modele")
    autre_modele = module_config.empreinte_execution()
    assert autre_modele["code"] == reference["code"]
    assert autre_modele["empreinte"] != reference["empreinte"]

    # Meme code, meme modele, mais un seuil deplace : l'empreinte doit changer aussi.
    monkeypatch.setattr(module_config.config, "mardik_fake_llm", True)
    monkeypatch.setattr(module_config.Seuils, "FAIBLE_CONFIANCE", 0.70)
    autre_seuil = module_config.empreinte_execution()
    assert autre_seuil["code"] == reference["code"]
    assert autre_seuil["config"] != reference["config"]
    assert autre_seuil["empreinte"] != reference["empreinte"]


def test_chaque_signal_et_chaque_decision_portent_l_empreinte(client, contrat_long):
    """Sans empreinte sur le signal, on ne peut pas attribuer un comportement observe."""
    from mardik.observabilite import journal as module_journal
    from mardik.observabilite import signaux as module_signaux

    canary.definir_poids(
        100, evenement=journal.DEPLOIEMENT, signal_declencheur="test", auteur="test"
    )
    client.post("/analyser", json={"contrat": contrat_long})

    signal = module_signaux.lire(limite=1)[0]
    assert signal["empreinte"].startswith("v-")

    decision = module_journal.lire(limite=1)[0]
    assert decision["empreinte"] == signal["empreinte"]


def test_gate_en_echec_bloque_la_livraison(tmp_path, monkeypatch):
    """Un gate en echec (note d'evaluation sous le seuil) bloque la livraison."""
    from eval import evaluer as module_gate

    golden = tmp_path / "golden_degrade.jsonl"
    # Des attentes impossibles a satisfaire : le F1 s'effondre sous le seuil.
    cas = [
        {
            "id": f"degrade-{index}",
            "origine": "initial",
            "contrat": "Document sans aucune clause identifiable. " * 30,
            "clauses_attendues": ["duree", "resiliation", "paiement", "responsabilite"],
        }
        for index in range(3)
    ]
    golden.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cas) + "\n", encoding="utf-8"
    )

    monkeypatch.setattr(module_gate, "GOLDEN", golden)
    monkeypatch.setattr(module_gate, "HISTORIQUE", tmp_path / "historique.jsonl")
    monkeypatch.setattr(module_gate, "REFERENCE", tmp_path / "reference.json")
    monkeypatch.setattr(module_gate, "RAPPORT", tmp_path / "rapport.md")
    monkeypatch.setattr("sys.argv", ["evaluer.py"])

    bilan = module_gate.evaluer()
    assert bilan["score_global"] < Seuils.GATE_EVALUATION
    assert bilan["bloquant_franchi"] is False

    # Code de sortie non nul : c'est ce qui interrompt la chaine en integration continue.
    assert module_gate.main() == 1
