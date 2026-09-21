"""Construit le jeu d'evaluation initial.

Le brief evoque « quelques contrats » qui n'ont pas ete livres avec le sujet. Ce script
en compose de facon deterministe a partir de blocs de redaction juridique, pour que le
jeu d'evaluation soit reproductible a l'identique sur n'importe quelle machine et en
integration continue. Les cas captures en production viennent ensuite s'y ajouter par la
boucle d'enrichissement, avec `origine: production`.

Usage : `uv run python eval/generer_golden.py`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mardik.config import GOLDEN  # noqa: E402

PREAMBULE = """CONTRAT DE PRESTATION DE SERVICES

ENTRE LES SOUSSIGNES :
La societe MARDIK SAS, au capital de 50 000 euros, immatriculee au RCS de Paris sous le
numero 912 345 678, dont le siege social est situe 14 rue de la Boetie, 75008 Paris,
representee par son President dument habilite, ci-apres denommee « le Prestataire »,

ET :
La societe cliente, societe par actions simplifiee au capital de 120 000 euros,
representee par son Directeur General, ci-apres denommee « le Client »,

IL A ETE PREALABLEMENT EXPOSE CE QUI SUIT :
Le Client souhaite confier au Prestataire une mission d'analyse documentaire. Les parties
se sont rapprochees et ont convenu de ce qui suit.
"""

REMPLISSAGE = """
ARTICLE {n} - MODALITES D'EXECUTION
Le Prestataire s'engage a executer la mission conformement aux regles de l'art et aux
usages de la profession. Il met en oeuvre les moyens humains et techniques necessaires a
la bonne fin des prestations. Le Client s'engage a fournir au Prestataire l'ensemble des
informations et documents utiles a l'accomplissement de sa mission, dans des delais
compatibles avec le calendrier convenu entre les parties. Toute modification du perimetre
fera l'objet d'un avenant ecrit et signe par les representants habilites de chaque partie.
Les livrables sont reputes acceptes a defaut de reserve ecrite formulee dans les quinze
jours ouvres suivant leur remise. Les parties designent chacune un interlocuteur unique
charge du suivi operationnel et de la remontee des difficultes rencontrees.
"""

CLAUSES = {
    "duree": """
ARTICLE - DUREE DU CONTRAT
Le present contrat prend effet a compter du 1er janvier 2026 pour une duree ferme de
trois (3) annees. Il se renouvellera ensuite par tacite reconduction par periodes
successives d'un an, sauf denonciation par l'une des parties. L'echeance initiale est
fixee au 31 decembre 2028.
""",
    "resiliation": """
ARTICLE - RESILIATION
Chaque partie pourra resilier le present contrat a tout moment, sous reserve de respecter
un preavis de trois (3) mois notifie par lettre recommandee avec accuse de reception. En
cas de manquement grave non repare dans les trente jours suivant mise en demeure, la
resiliation interviendra de plein droit.
""",
    "paiement": """
ARTICLE - CONDITIONS FINANCIERES ET PAIEMENT
La remuneration est fixee a 4 500 euros hors taxes par mois. Le reglement des factures
intervient a trente (30) jours date de facture, par virement bancaire. Tout retard de
paiement entraine de plein droit l'application d'une penalite de retard calculee au taux
de trois fois le taux d'interet legal, ainsi qu'une indemnite forfaitaire de 40 euros.
""",
    "responsabilite": """
ARTICLE - RESPONSABILITE
La responsabilite du Prestataire est expressement limitee aux dommages directs et
previsibles. En tout etat de cause, le montant total des indemnisations dues au titre du
present contrat ne pourra exceder le plafond correspondant aux sommes effectivement
versees par le Client au cours des douze derniers mois. Le Prestataire ne saurait etre
tenu responsable d'un prejudice indirect, notamment d'une perte d'exploitation.
""",
    "confidentialite": """
ARTICLE - CONFIDENTIALITE
Chaque partie s'engage a considerer comme strictement confidentielles toutes les
informations recues de l'autre partie. Cette obligation de non-divulgation demeure en
vigueur pendant toute la duree du contrat et cinq annees apres son terme. Aucune
information couverte par le secret des affaires ne pourra etre divulguee a un tiers sans
accord ecrit prealable.
""",
}

SIGNATURE = """
ARTICLE - LITIGES
Le present contrat est soumis au droit francais. Tout differend releve de la competence
exclusive du Tribunal de commerce de Paris.

Fait a Paris, en deux exemplaires originaux.
"""


def composer(clauses: list[str], blocs_remplissage: int = 0) -> str:
    """Assemble un contrat contenant exactement les clauses demandees."""
    morceaux = [PREAMBULE]
    for index in range(blocs_remplissage):
        morceaux.append(REMPLISSAGE.format(n=index + 1))
    for clause in clauses:
        morceaux.append(CLAUSES[clause])
        # Du texte de remplissage entre les clauses, pour les eloigner les unes des autres.
        morceaux.append(REMPLISSAGE.format(n=100 + len(morceaux)))
    morceaux.append(SIGNATURE)
    return "\n".join(morceaux)


TOUTES = list(CLAUSES)

CAS = [
    {
        "id": "initial-01",
        "description": "Contrat court et complet — les cinq clauses presentes.",
        "clauses_attendues": TOUTES,
        "contrat": composer(TOUTES),
    },
    {
        "id": "initial-02",
        "description": "Contrat long : les clauses sont rejetees au-dela de la troncature v1.",
        "clauses_attendues": TOUTES,
        "contrat": composer(TOUTES, blocs_remplissage=12),
    },
    {
        "id": "initial-03",
        "description": "Contrat tres long (plus de 30 000 caracteres).",
        "clauses_attendues": TOUTES,
        "contrat": composer(TOUTES, blocs_remplissage=35),
    },
    {
        "id": "initial-04",
        "description": "Contrat sans clause de confidentialite.",
        "clauses_attendues": ["duree", "resiliation", "paiement", "responsabilite"],
        "contrat": composer(["duree", "resiliation", "paiement", "responsabilite"]),
    },
    {
        "id": "initial-05",
        "description": "Contrat minimal : duree et paiement uniquement.",
        "clauses_attendues": ["duree", "paiement"],
        "contrat": composer(["duree", "paiement"]),
    },
    {
        "id": "initial-06",
        "description": "Avenant court, une seule clause financiere.",
        "clauses_attendues": ["paiement"],
        "contrat": composer(["paiement"]),
    },
]


def main() -> None:
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    conserves = []
    if GOLDEN.exists():
        with GOLDEN.open(encoding="utf-8") as fichier:
            conserves = [
                json.loads(ligne)
                for ligne in fichier
                if ligne.strip() and json.loads(ligne).get("origine") == "production"
            ]

    with GOLDEN.open("w", encoding="utf-8") as fichier:
        for cas in CAS:
            fichier.write(json.dumps({**cas, "origine": "initial"}, ensure_ascii=False) + "\n")
        for cas in conserves:
            fichier.write(json.dumps(cas, ensure_ascii=False) + "\n")

    print(f"{len(CAS)} cas initiaux ecrits dans {GOLDEN}")
    if conserves:
        print(f"{len(conserves)} cas issus de la production conserves")
    for cas in CAS:
        print(f"  {cas['id']:12} {len(cas['contrat']):>7} caracteres  {cas['description']}")


if __name__ == "__main__":
    main()
