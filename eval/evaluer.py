"""Gate d'evaluation du modele — bloquant dans la chaine LLMOps.

Rejoue l'integralite du jeu d'evaluation contre la v2 et calcule un score global. Si ce
score passe sous `Seuils.GATE_EVALUATION`, le script sort en code 1 et la chaine
s'interrompt : aucune livraison ne franchit ce point.

Ce gate est aussi le maillon de la boucle d'enrichissement : les cas captures en
production (`origine: production`) sont dans le meme fichier et sont donc rejoues ici a
la fusion suivante, exactement comme les cas initiaux.

Usage :
    uv run python eval/evaluer.py                # evalue et bloque si sous le seuil
    uv run python eval/evaluer.py --reference    # enregistre en plus le score de reference
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mardik.config import DOSSIER_EVAL, GOLDEN, Seuils, version_livree  # noqa: E402
from mardik.modele import v2  # noqa: E402
from mardik.observabilite.signaux import cout  # noqa: E402

HISTORIQUE = DOSSIER_EVAL / "historique.jsonl"
REFERENCE = DOSSIER_EVAL / "reference_gate.json"
RAPPORT = DOSSIER_EVAL / "rapports" / "dernier.md"


def charger() -> list[dict]:
    if not GOLDEN.exists():
        raise SystemExit(
            f"Jeu d'evaluation absent : {GOLDEN}\n"
            "Generez-le avec : uv run python eval/generer_golden.py"
        )
    with GOLDEN.open(encoding="utf-8") as fichier:
        return [json.loads(ligne) for ligne in fichier if ligne.strip()]


def noter(attendues: list[str], trouvees: list[str]) -> dict:
    """F1 entre clauses attendues et clauses trouvees.

    On retient le F1 plutot que le simple rappel pour que le modele ne puisse pas
    obtenir un bon score en annoncant toutes les clauses a chaque fois.
    """
    ensemble_attendu = set(attendues)
    ensemble_trouve = set(trouvees)
    justes = ensemble_attendu & ensemble_trouve

    rappel = len(justes) / len(ensemble_attendu) if ensemble_attendu else 1.0
    precision = len(justes) / len(ensemble_trouve) if ensemble_trouve else 1.0
    f1 = 2 * precision * rappel / (precision + rappel) if (precision + rappel) else 0.0

    return {
        "rappel": round(rappel, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "manquantes": sorted(ensemble_attendu - ensemble_trouve),
        "superflues": sorted(ensemble_trouve - ensemble_attendu),
    }


def evaluer() -> dict:
    cas = charger()
    resultats = []
    debut_total = time.perf_counter()

    for enregistrement in cas:
        debut = time.perf_counter()
        resultat = v2.analyser(enregistrement["contrat"])
        latence_ms = (time.perf_counter() - debut) * 1000

        note = noter(enregistrement["clauses_attendues"], sorted(resultat.clauses))
        resultats.append(
            {
                "id": enregistrement["id"],
                "origine": enregistrement.get("origine", "initial"),
                "taille": len(enregistrement["contrat"]),
                "latence_ms": round(latence_ms, 2),
                "cout_eur": cout(resultat.tokens),
                "couverture": resultat.couverture,
                "score_confiance": resultat.score_confiance,
                **note,
            }
        )

    score_global = sum(r["f1"] for r in resultats) / len(resultats)
    couverture_min = min(r["couverture"] for r in resultats)
    score_confiance_moyen = sum(r["score_confiance"] for r in resultats) / len(resultats)
    latences = sorted(r["latence_ms"] for r in resultats)
    p95 = latences[min(len(latences) - 1, int(0.95 * len(latences)))]

    couverture_ok = couverture_min >= Seuils.COUVERTURE_MIN
    seuil_atteint = score_global >= Seuils.GATE_EVALUATION

    return {
        "horodatage": datetime.now(timezone.utc).isoformat(),
        "version_livree": version_livree(),
        "cas_total": len(cas),
        "cas_production": sum(1 for c in cas if c.get("origine") == "production"),
        "score_global": round(score_global, 4),
        "seuil": Seuils.GATE_EVALUATION,
        "seuil_atteint": seuil_atteint,
        "couverture_min": round(couverture_min, 4),
        "couverture_requise": Seuils.COUVERTURE_MIN,
        "couverture_ok": couverture_ok,
        "score_moyen": round(score_confiance_moyen, 4),
        "latence_p95_ms": p95,
        "cout_total_eur": round(sum(r["cout_eur"] for r in resultats), 6),
        "duree_totale_s": round(time.perf_counter() - debut_total, 2),
        "bloquant_franchi": seuil_atteint and couverture_ok,
        "resultats": resultats,
    }


def ecrire_rapport(bilan: dict) -> None:
    RAPPORT.parent.mkdir(parents=True, exist_ok=True)
    lignes = [
        f"# Rapport d'evaluation — version `{bilan['version_livree']}`",
        "",
        f"- Horodatage : {bilan['horodatage']}",
        f"- Cas evalues : **{bilan['cas_total']}** "
        f"(dont {bilan['cas_production']} issus de la production)",
        f"- Score global : **{bilan['score_global']}** / seuil {bilan['seuil']} "
        f"→ {'FRANCHI' if bilan['seuil_atteint'] else 'ECHEC'}",
        f"- Couverture minimale : **{bilan['couverture_min']}** "
        f"/ requise {bilan['couverture_requise']} "
        f"→ {'OK' if bilan['couverture_ok'] else 'ECHEC'}",
        f"- Score de confiance moyen : {bilan['score_moyen']}",
        f"- Latence p95 : {bilan['latence_p95_ms']} ms",
        f"- Cout total : {bilan['cout_total_eur']} EUR",
        "",
        "| Cas | Origine | Taille | F1 | Confiance | Couverture | Manquantes |",
        "|---|---|---|---|---|---|---|",
    ]
    for resultat in bilan["resultats"]:
        lignes.append(
            f"| {resultat['id']} | {resultat['origine']} | {resultat['taille']} | "
            f"{resultat['f1']} | {resultat['score_confiance']} | {resultat['couverture']} | "
            f"{', '.join(resultat['manquantes']) or '—'} |"
        )
    RAPPORT.write_text("\n".join(lignes) + "\n", encoding="utf-8")


def main() -> int:
    analyseur = argparse.ArgumentParser(description="Gate d'evaluation du modele v2.")
    analyseur.add_argument(
        "--reference",
        action="store_true",
        help="Enregistre le score de confiance moyen comme reference pour la promotion canary.",
    )
    arguments = analyseur.parse_args()

    bilan = evaluer()

    HISTORIQUE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORIQUE.open("a", encoding="utf-8") as fichier:
        fichier.write(
            json.dumps({k: v for k, v in bilan.items() if k != "resultats"}, ensure_ascii=False)
            + "\n"
        )
    ecrire_rapport(bilan)

    print(f"Cas evalues        : {bilan['cas_total']} (production : {bilan['cas_production']})")
    print(f"Score global       : {bilan['score_global']}  (seuil {bilan['seuil']})")
    print(f"Couverture minimale: {bilan['couverture_min']} (requise {bilan['couverture_requise']})")
    print(f"Confiance moyenne  : {bilan['score_moyen']}")
    print(f"Latence p95        : {bilan['latence_p95_ms']} ms")
    print(f"Rapport            : {RAPPORT}")

    for resultat in bilan["resultats"]:
        if resultat["manquantes"] or resultat["superflues"]:
            print(
                f"  ! {resultat['id']} f1={resultat['f1']} "
                f"manquantes={resultat['manquantes']} superflues={resultat['superflues']}"
            )

    if not bilan["bloquant_franchi"]:
        print("\nGATE EN ECHEC — la livraison est bloquee.")
        return 1

    if arguments.reference:
        REFERENCE.write_text(
            json.dumps(
                {
                    "version_livree": bilan["version_livree"],
                    "score_moyen": bilan["score_moyen"],
                    "score_global": bilan["score_global"],
                    "horodatage": bilan["horodatage"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Reference de promotion enregistree : {REFERENCE}")

    print("\nGATE FRANCHI — la livraison peut se poursuivre.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
