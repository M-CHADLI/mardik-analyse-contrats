# Mardik — Analyse de contrats v2

Livraison de la v2 d'un modèle d'analyse de contrats **sans jamais casser la v1**, par une
chaîne LLMOps automatisée : gates bloquants → artefact étiqueté → déploiement canary
piloté par les métriques.

📄 **[Dossier de conception](docs/dossier-de-conception.md)** — à lire en premier.

---

## Démarrage

```bash
uv sync --all-groups
cp .env.example .env          # facultatif : le moteur factice fonctionne sans clé
uv run uvicorn mardik.api.app:app --reload
```

| Page | Adresse |
|---|---|
| Client d'analyse | http://localhost:8000 |
| Tableau de bord | http://localhost:8000/tableau-de-bord |
| Documentation d'API | http://localhost:8000/docs |

Avec Docker, traces Jaeger comprises :

```bash
docker compose up --build     # + interface Jaeger sur http://localhost:16686
```

### Moteur de langage

Par défaut `MARDIK_FAKE_LLM=1` : un moteur déterministe, gratuit et hors ligne. C'est ce
qui permet aux tests et aux gates de tourner **sans clé d'API et sans coût**. Pour
brancher le vrai modèle, renseignez `AZURE_AI_ENDPOINT` / `AZURE_AI_API_KEY` et passez
`MARDIK_FAKE_LLM=0`.

---

## Démonstration des boucles de rétroaction

Serveur démarré, dans un second terminal :

```bash
# 1. Le client historique fonctionne — trafic encore sur la v1
uv run python scripts/client_v1.py

# 2. Déploiement canary : 100 % du trafic vers la v2
curl -X POST http://localhost:8000/api/canary/poids \
     -H 'Content-Type: application/json' -d '{"poids":100,"auteur":"demo"}'

# 3. Le MÊME client, sans une ligne modifiée, est maintenant servi par la v2
uv run python scripts/client_v1.py

# 4. Dérive : des documents dégradés font chuter le score de confiance
uv run python scripts/traffic_sim.py --profil degrade --nombre 21
```

À l'étape 4, le rollback se déclenche **seul** : le trafic revient à la v1, la promotion
est gelée, et l'événement est tracé avec le signal qui l'a déclenché. Le tableau de bord
montre la bascule en direct, et les cas à faible confiance apparaissent dans la file de
relecture.

Pour la promotion dans l'autre sens : `--profil normal --nombre 60`.

---

## Structure

```
src/mardik/
  config.py              Tous les seuils, en un seul endroit
  modele/
    llm.py               Moteur factice déterministe ou modèle distant
    v1.py                Génération figée — tronque à 8 000 car., aucun score
    v2.py                Segmentation + score de confiance composite
  api/
    schemas.py           ReponseV2 hérite de ReponseV1 (sur-ensemble strict)
    canary.py            Répartition du trafic ; aucune bascule non tracée
    app.py               Points d'entrée HTTP
  observabilite/
    signaux.py           Les cinq signaux imposés
    journal.py           Journal de pilotage
    telemetrie.py        Traces OpenTelemetry
  boucles/
    rollback.py          ① retour arrière sur signal
    promotion.py         ② montée en trafic pilotée par les métriques
    enrichissement.py    ③ capture des cas difficiles → jeu d'évaluation

eval/evaluer.py          Gate bloquant (sortie 1 sous le seuil)
scripts/client_v1.py     Témoin de non-régression — à ne jamais modifier
scripts/traffic_sim.py   Simulateur de dérive
.github/workflows/       La chaîne LLMOps
```

---

## Gates (identiques en local et en intégration continue)

```bash
uv run ruff format --check . && uv run ruff check .
uv run mypy src
uv run pytest -q
uv run python eval/evaluer.py --reference
```

Les dix critères de performance du brief sont transcrits en tests exécutables :
`tests/test_acceptance_chaine.py` et `tests/test_acceptance_observabilite.py`.

---

## Note sur le sujet

Le brief référence `besoin_client.md`, `scripts/client_v1.py` et `traffic_sim.py` comme
étant fournis. **Ils ne l'étaient pas** — ils ont été écrits ici, et les contraintes
chiffrées sont des hypothèses assumées, documentées dans
[`besoin_client.md`](besoin_client.md) et centralisées dans `src/mardik/config.py`. Les
références `M1` / `M3` du brief ne sont définies nulle part dans le sujet.
