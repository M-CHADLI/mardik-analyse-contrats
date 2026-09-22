"""Confidentialite des cas captures en production.

Le brief demande : « comment capturez-vous les cas reels a faible confiance — et qu'en
est-il des donnees du client, anonymisation ? ». Ces tests verrouillent la reponse : un
cas capture part dans `golden.jsonl`, donc dans Git et dans l'integration continue ; rien
d'identifiant ne doit s'y trouver.
"""

from __future__ import annotations

import json

from mardik.boucles import enrichissement
from mardik.boucles.anonymisation import anonymiser
from mardik.config import Seuils
from mardik.modele import v2

EN_TETE_IDENTIFIANT = """CONTRAT DE PRESTATION DE SERVICES

Entre la societe MARDIK SAS, au capital de 50 000 euros, immatriculee au RCS de Paris
sous le numero 912 345 678, dont le siege est 14 rue de la Boetie, 75008 Paris,
representee par Monsieur Jean Dupont, joignable a jean.dupont@mardik.fr
ou au 01 44 55 66 77, IBAN FR76 3000 4000 0512 3456 7890 143.
"""

CONTRAT_AVEC_DONNEES = (
    EN_TETE_IDENTIFIANT
    + """
ARTICLE - DUREE : prend effet le 1er janvier 2026, duree de trois ans, echeance 2028.
ARTICLE - RESILIATION : resiliation avec preavis de trois mois.
ARTICLE - PAIEMENT : remuneration de 4 500 euros, reglement a 30 jours, penalite.
ARTICLE - RESPONSABILITE : responsabilite plafonnee, prejudice indirect exclu.
ARTICLE - CONFIDENTIALITE : obligation de confidentialite, aucune divulgation.
"""
)

IDENTIFIANTS = (
    "912 345 678",
    "jean.dupont@mardik.fr",
    "01 44 55 66 77",
    "FR76 3000 4000 0512 3456 7890",
    "14 rue de la Boetie",
    "75008 Paris",
    "MARDIK",
    "Jean Dupont",
)


def test_les_identifiants_disparaissent_du_texte():
    anonyme, substitutions = anonymiser(CONTRAT_AVEC_DONNEES)

    for identifiant in IDENTIFIANTS:
        assert identifiant not in anonyme, f"{identifiant!r} subsiste apres pseudonymisation"

    assert substitutions, "aucune substitution n'a ete comptabilisee"


def test_le_vocabulaire_juridique_survit():
    """La pseudonymisation ne doit pas abimer ce que le jeu d'evaluation mesure."""
    anonyme, _ = anonymiser(CONTRAT_AVEC_DONNEES)

    avant = v2.analyser(CONTRAT_AVEC_DONNEES)
    apres = v2.analyser(anonyme)

    assert sorted(apres.clauses) == sorted(avant.clauses)
    # Le montant est retire mais l'unite reste : la clause de paiement reste reperable.
    assert "euros" in anonyme
    assert "[MONTANT]" in anonyme


def test_le_cas_capture_est_pseudonymise_sur_disque(contrat_bruite):
    """Le texte d'origine ne doit jamais etre ecrit dans un fichier.

    Le contrat utilise ici porte l'en-tete identifiant mais aucune clause exploitable :
    c'est exactement le profil d'un document mal numerise, donc un cas a faible confiance
    tel que la boucle d'enrichissement en capture en production.
    """
    contrat = EN_TETE_IDENTIFIANT + contrat_bruite
    resultat = v2.analyser(contrat)
    assert resultat.score_confiance < Seuils.FAIBLE_CONFIANCE, "le cas doit etre capturable"

    cas = enrichissement.capturer(
        contrat,
        score=resultat.score_confiance,
        clauses_trouvees=sorted(resultat.clauses),
        requete_id="req-test",
    )
    assert cas is not None

    ecrit = enrichissement.FILE_VALIDATION.read_text(encoding="utf-8")
    for identifiant in IDENTIFIANTS:
        assert identifiant not in ecrit, f"{identifiant!r} a ete ecrit en clair sur disque"

    # Le versement au jeu d'evaluation ne doit pas reintroduire l'original.
    enrichissement.valider(cas["id"], ["duree", "paiement"], auteur="juriste.test")
    verse = enrichissement.GOLDEN.read_text(encoding="utf-8")
    for identifiant in IDENTIFIANTS:
        assert identifiant not in verse, f"{identifiant!r} est entre dans le jeu d'evaluation"

    entree = json.loads(verse.splitlines()[0])
    assert entree["anonymisation"], "le detail des substitutions doit accompagner le cas"
