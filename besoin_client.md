# Besoin client — Analyse de contrats Mardik v2

> **Statut de ce document.** Le brief renvoie à un `besoin_client.md` pour les contraintes
> chiffrées, mais ce fichier n'a pas été livré avec le sujet. Les valeurs ci-dessous sont
> donc des **hypothèses de travail assumées**, figées ici pour que toute la chaîne
> (gates, seuils, rollback, promotion) puisse s'y référer de façon vérifiable.
> Si le fichier d'origine est fourni plus tard, seules ces constantes sont à corriger :
> elles sont centralisées dans `src/mardik/config.py`.

## 1. Le besoin fonctionnel

Les juristes de notre client principal analysent des contrats commerciaux. Ils attendent
de l'outil qu'il extraie les clauses structurantes d'un contrat et leur dise **à quel point
ils peuvent faire confiance au résultat**.

Clauses à extraire :

| Clause | Description |
|---|---|
| `duree` | Durée d'engagement et date d'échéance |
| `resiliation` | Conditions et préavis de résiliation |
| `paiement` | Montants, échéances, pénalités de retard |
| `responsabilite` | Limitations et plafonds de responsabilité |
| `confidentialite` | Obligations de confidentialité |

## 2. Les deux défauts de la v1 à corriger

1. **Troncature silencieuse.** La v1 coupe le document à 8 000 caractères et analyse
   uniquement ce début, sans le signaler. Sur un contrat de 60 000 caractères, elle ignore
   87 % du texte tout en présentant son résultat comme complet.
2. **Aucun indice de fiabilité.** Rien ne distingue une analyse solide d'une analyse
   hasardeuse. Le juriste ne sait pas quand revérifier.

## 3. Contraintes chiffrées (le contrat de service)

| Paramètre | Valeur | Rôle dans la chaîne |
|---|---|---|
| Taille maximale d'un contrat | 150 000 caractères | Au-delà : erreur explicite `413` |
| Troncature v1 (défaut historique) | 8 000 caractères | Référence de non-régression |
| Latence p95, document long | ≤ 20 s | Signal du tableau de bord |
| Coût maximal par analyse | ≤ 0,05 € | Signal du tableau de bord |
| Seuil « analyse peu fiable » | score < 0,60 | Déclenche la capture pour enrichissement |
| Gate d'évaluation bloquant | score global ≥ 0,70 | Bloque la livraison si non atteint |
| Couverture minimale du document | ≥ 95 % | Critère d'acceptation de la v2 |

## 4. Règles de pilotage de la production

**Déclenchement du rollback** — dès qu'une des conditions est vraie sur une fenêtre
glissante de 20 requêtes servies par la v2 :

- latence p95 > 30 s
- taux d'erreur > 5 %
- part d'analyses peu fiables (score < 0,60) > 25 %

**Promotion canary** — paliers `10 % → 50 % → 100 %`, avec une fenêtre d'observation de
50 requêtes par palier. La promotion n'a lieu que si, sur la fenêtre écoulée, aucune
condition de rollback n'est remplie **et** que le score de confiance moyen de la v2 est
supérieur ou égal à celui mesuré sur le jeu d'évaluation à la sortie de la chaîne.

## 5. Hors périmètre

- La modification du contrat d'API `/v1` : il est figé, `scripts/client_v1.py` en est le
  témoin exécutable.
- La signature électronique, le stockage durable des contrats, la gestion des droits par
  utilisateur.
- Le ré-entraînement d'un modèle : on opère un modèle de langage par API, on ne l'entraîne pas.
