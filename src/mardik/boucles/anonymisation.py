"""Pseudonymisation des contrats capturés avant leur entrée dans le jeu d'évaluation.

Pourquoi c'est indispensable ici : un cas capturé en production est versé dans
`eval/golden.jsonl`, fichier **commité dans Git et rejoué par l'intégration continue**.
Sans traitement, des contrats clients réels se retrouveraient dans un dépôt et dans une
infrastructure tierce. Le produit analyse des contrats commerciaux — dont les clauses de
confidentialité : la contradiction serait totale.

**Ce que l'on retire et ce que l'on garde.** Le jeu d'évaluation ne sert qu'à vérifier que
le modèle retrouve les bonnes clauses. Il a besoin de la *structure juridique* et du
*vocabulaire*, jamais de l'identité des parties ni des montants réels. On peut donc
pseudonymiser agressivement sans perdre la valeur d'évaluation.

**Limite assumée.** Ce module repose sur des expressions régulières, pas sur une
reconnaissance d'entités nommées. Il traite ce qui a une forme reconnaissable (SIREN,
IBAN, montants, courriels, adresses) et laissera passer une raison sociale écrite en
toutes lettres au fil du texte. C'est pourquoi la **relecture humaine avant versement**
fait aussi office de contrôle de confidentialité : les deux rôles sont assumés par la
même étape, et c'est ce qui rend le dispositif défendable.
"""

from __future__ import annotations

import re

# Chaque motif est remplacé par un marqueur qui conserve la nature de l'information
# retirée : la phrase reste grammaticalement lisible et le vocabulaire juridique intact.
REGLES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Coordonnées bancaires — avant les autres motifs numériques.
    (re.compile(r"\b[A-Z]{2}\d{2}(?:[\s]?[A-Z0-9]{4}){2,7}\b"), "[IBAN]"),
    # Courriels et adresses web.
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"), "[COURRIEL]"),
    # Téléphones français.
    (re.compile(r"\b0[1-9](?:[\s.-]?\d{2}){4}\b"), "[TELEPHONE]"),
    # SIRET (14 chiffres) puis SIREN (9 chiffres), éventuellement espacés.
    (re.compile(r"\b\d{3}[\s.]?\d{3}[\s.]?\d{3}[\s.]?\d{5}\b"), "[SIRET]"),
    (re.compile(r"\b\d{3}[\s.]?\d{3}[\s.]?\d{3}\b"), "[SIREN]"),
    # Immatriculation au registre du commerce.
    (re.compile(r"\bRCS\s+[A-ZÀ-Ý][\w-]+", re.IGNORECASE), "RCS [VILLE]"),
    # Montants : on retire le chiffre, on garde l'unité — « euros » reste détectable.
    (re.compile(r"\b\d[\d\s.,]*\s*(?=(?:€|euros?|EUR)\b)", re.IGNORECASE), "[MONTANT] "),
    (re.compile(r"\b\d[\d\s.,]*\s*€"), "[MONTANT] €"),
    # Adresse postale : numéro + voie, puis code postal + commune.
    (
        re.compile(
            r"\b\d{1,4}(?:\s?(?:bis|ter))?\s+"
            r"(?:rue|avenue|boulevard|place|impasse|chemin|allée|quai|cours)\s+"
            r"[^,.\n]{2,40}",
            re.IGNORECASE,
        ),
        "[ADRESSE]",
    ),
    (re.compile(r"\b\d{5}\s+[A-ZÀ-Ý][\w-]+(?:[\s-][A-ZÀ-Ý][\w-]+)*"), "[CODE POSTAL] [VILLE]"),
    # Raison sociale suivant une forme juridique. Les deux graphies de « societe » sont
    # prevues : les contrats numerises perdent souvent leurs accents a la reconnaissance
    # de caracteres, et un motif accentue seul laisserait passer la raison sociale.
    (
        re.compile(
            r"\b(soci[ée]t[ée]|SAS|SASU|SARL|SA|SCI|EURL)\s+"
            r"([A-ZÀ-Ý][\w&'-]*(?:\s+[A-ZÀ-Ý][\w&'-]*){0,3})",
        ),
        r"\1 [RAISON SOCIALE]",
    ),
    # Personne physique introduite par une civilite.
    (
        re.compile(
            r"\b(Monsieur|Madame|Mme|M\.|Me|Maître|Maitre)\s+"
            r"([A-ZÀ-Ý][\w'-]*(?:\s+[A-ZÀ-Ý][\w'-]*){0,2})",
        ),
        r"\1 [NOM]",
    ),
)


def anonymiser(texte: str) -> tuple[str, dict[str, int]]:
    """Pseudonymise un contrat et rend le compte des substitutions par catégorie.

    Le compte est renvoyé pour être affiché au relecteur : il doit savoir ce qui a été
    retiré automatiquement pour juger de ce qui pourrait rester.
    """
    resultat = texte
    comptes: dict[str, int] = {}

    for motif, remplacement in REGLES:
        resultat, substitutions = motif.subn(remplacement, resultat)
        if substitutions:
            etiquette = re.sub(r"[^A-ZÀ-Ý ]", "", remplacement).strip() or remplacement
            comptes[etiquette] = comptes.get(etiquette, 0) + substitutions

    return resultat, comptes
