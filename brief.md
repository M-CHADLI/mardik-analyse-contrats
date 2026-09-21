# Mardik — Déploiement v2 de l'analyse de contrats

## Contexte du projet

Mardik édite un outil d'analyse de contrats. La v1 du modèle **tronque les longs documents** et **ne donne aucun indice de fiabilité** — le client principal réclame une v2 depuis des mois.

Mais la semaine dernière, un déploiement manuel raté a mis la production à terre une demi-journée : copie de fichiers à la main, aucune version identifiable, aucun retour arrière possible.

Le CTO a publié une note interne intitulée **« Plus jamais ça »** : la v2 sera livrée, mais plus aucune livraison artisanale.

### Ses exigences

1. **La v2 répond au besoin** — documents longs, score de confiance, dans les contraintes de latence.
2. **La v1 ne casse jamais** — les clients existants continuent de fonctionner pendant toute la transition.
3. **Chaque livraison est automatique, testée et réversible** — une fusion produit une version étiquetée, un échec bloque, un rollback est toujours possible.

---

## Modalités pédagogiques

### Travail préliminaire de conception

La conception se mène en deux chantiers. Le CTO impose les exigences suivantes ; à vous d'en déduire l'architecture.

#### Exigences imposées (note du CTO)

- La v2 répond au besoin (documents longs, score de confiance, contraintes de `besoin_client.md`) et est livrée par la chaîne — **jamais à la main**.
- Toute fusion produit une **version étiquetée** (code + modèle + config), testée par des **gates bloquants** ; un gate en échec bloque la livraison.
- Le client v1 **ne casse jamais** ; la bascule v2 est progressive et pilotée par les métriques.
- La production est **observée** : latence, coût, taux d'erreur, distribution du score de confiance, part de trafic v1/v2 — visibles sur un tableau de bord.
- **Au moins deux boucles de rétroaction** fonctionnent et sont démontrées en live : rollback sur signal, promotion canary pilotée, enrichissement du jeu d'évaluation.
- Tout ajustement de la chaîne (changement de seuil, promotion, rollback) est **tracé** : quel signal l'a déclenché, quand, par qui ou par quoi.

---

### Chantier 1 — La chaîne LLMOps

**Questions pour guider votre réflexion**

> Questions posées par les apprenants (avec, pour certaines, la réponse apportée) :

- **Canary split** — le canary sépare-t-il deux releases d'un même service (ancienne image vs nouvelle image), ou s'agit-il de la migration progressive des clients du modèle v1 vers le modèle v2 ?
- **Deux boucles ou trois** — le brief dit « au moins deux » boucles de rétroaction démontrées en live, mais les livrables listent « les trois boucles ». Faut-il les trois à la livraison, ou deux suffisent ?
- **M1 / M3** — référencées dans les étapes du Chantier 1 mais non définies dans le texte disponible. *(À signaler une fois, sans s'y attarder.)*
- Comment les métiers (juristes, service client) décrivent-ils, dans leurs propres mots, un contrat « mal traité » par la v1 ? Ce vocabulaire doit-il devenir le langage partagé du domaine (ex. *« contrat tronqué »*, *« analyse non fiable »*) ?
- Que signifie « score de confiance » pour un juriste qui doit décider de valider ou revérifier une analyse ? Quel terme métier (ex. *« indice de fiabilité »*, *« niveau de certitude »*) doit remonter dans un modèle de domaine partagé entre dev et métier ?
- Est-ce que la V1 est figée de chez figée (peut-on mettre un peu d'observabilité sur la V1) ?
  → **Réponse : on peut toucher l'infra pour ajouter de l'observabilité.**
- Qu'est-ce qu'on met en place pour évaluer le build ? Qu'est-ce qui permettra de dire que le build est correct ?
- Il existe quelques contrats ; donner ce qu'on en attend.
- Quel découpage (Steeve) ?
- Comment se passe le rollback (Steeve) → le plus facile possible (genre un bouton).
- API et contrat : quelle entrée et quelle sortie ?

---

### Chantier 2 — L'observabilité qui pilote la chaîne

**Questions pour guider votre réflexion**

> Questions posées par les apprenants :

- Quels signaux faut-il instrumenter pour l'observabilité ?
- Quel est l'état de l'observabilité actuel et vers quoi veut-on aller (v1 et v2) ?
- Comment rendre une requête traçable de bout en bout ? Quels points instrumenter et quelles informations conserver pour relier une requête aux différentes étapes, à la version du modèle et à la configuration utilisée (span) ?
- Comment remonter et stocker les traces sans tout casser ?
- Quels signaux en amont d'un rollback ?
- Quelles informations doivent être présentées sur un dashboard ?
- Quels seuils doivent déclencher une décision ?
- **Qu'est-ce qui pilote la migration ?** Quelles métriques décident que la v2 avance (10 → 50 → 100 %) ou recule — uniquement les cinq signaux du dashboard, ou aussi des critères métier (types de contrats où la v2 doit battre la v1) ? Pour la dérive du score de confiance en particulier : dérive par rapport à quoi — la distribution mesurée sur le jeu d'évaluation (golden dataset) à la sortie de la chaîne, ou une fenêtre glissante de production — et sur combien de requêtes minimum avant de parler de dérive ?

---

### Livrable de conception

**Architecture / schéma attendus :**

- La synthèse du besoin (fonctionnel vs contraintes, hors périmètre) en une demi-page.
- Le contrat d'API v2 (entrées/sorties, score de confiance, codes d'erreur, versionnage).
- Le schéma de la chaîne LLMOps : **gates bloquants → build → artefact étiqueté → déploiement canary**.
- Le schéma de la boucle d'observabilité : **signaux → seuils → les trois rétroactions vers la chaîne**.
- Le tableau de pilotage : **signal × seuil × rétroaction déclenchée × trace**.

---

## Développement

### Chantier 1

- Analyser le besoin et figer le périmètre de la v2 dans une courte spec (exigences, contraintes, critères d'acceptation).
- Exposer le modèle v2 via l'API conforme au contrat (documents longs, score de confiance, erreurs explicites), **sans toucher au contrat de `/v1`** (M1, M3).
- Monter la chaîne (`llmops.yml`) : gates bloquants (tests + gate d'évaluation du modèle avec seuils initiaux) → build → artefact étiqueté → déploiement (canary/blue-green).

### Chantier 2

- Instrumenter les signaux (latence, coût, erreurs, distribution du score, part v1/v2) et construire le tableau de bord.
- Implémenter la boucle **rollback sur signal** : dérive détectée → retour arrière exécuté via la chaîne, événement tracé.
- Implémenter le **déploiement piloté par métriques**.
- Implémenter l'**enrichissement du jeu d'évaluation** : capture des cas réels à faible confiance → versement dans le jeu d'éval → rejoués par le gate à la fusion suivante.
- Ajuster les seuils des gates à partir des distributions observées, chaque ajustement tracé au journal de pilotage.

---

## Modalités d'évaluation

- Validation du dossier de conception (porte d'entrée du brief) : le contrat d'API, les gates et les trois boucles sont questionnés.
- Le travail réalisé est fonctionnel et remplit le CdC.

---

## Livrables

- **Dossier de conception** (besoin + contrat d'API + schéma de chaîne + schéma de boucle + tableau de pilotage).
- **L'API v2** du modèle (documents longs + score de confiance + erreurs explicites), v1 intacte.
- **La chaîne LLMOps** (fichier `.yml`) : gates bloquants, artefacts étiquetés, déploiement canary.
- **L'observabilité** : tableau de bord + les trois boucles de rétroaction + le journal de pilotage.
- **Un client** via un frontend accessible via un lien.

---

## Critères de performance

*Tests d'acceptance fournis (la réalisation doit les faire passer)*

### La chaîne LLMOps

| # | Étant donné | Quand | Alors |
|---|---|---|---|
| 1 | Une requête valide avec un document long | elle est envoyée à `/v2` | la réponse respecte le contrat et contient un score de confiance |
| 2 | Une requête invalide | elle est envoyée | l'API renvoie une erreur explicite (code + message) sans planter |
| 3 | Le client v1 (`scripts/client_v1.py`) | la v2 est déployée en canary | il continue de fonctionner sans modification |
| 4 | Une fusion sur la branche principale | elle a lieu | la chaîne teste, build et publie automatiquement une version étiquetée, et l'on peut identifier quelle version sert quel trafic |
| 5 | Un gate en échec (note d'évaluation sous le seuil) | la chaîne s'exécute | la livraison est bloquée |

### L'observabilité qui pilote

| # | Étant donné | Quand | Alors |
|---|---|---|---|
| 1 | Une dérive simulée du score de confiance (`traffic_sim.py`) | le seuil est franchi | le rollback s'exécute via la chaîne et l'événement est tracé au journal |
| 2 | Des métriques canary conformes aux critères | la fenêtre d'observation s'achève | la v2 est promue ; si non conformes, la promotion n'a pas lieu |
| 3 | Un cas de production à faible confiance | il est capturé | il apparaît dans le jeu d'évaluation et la chaîne le rejoue à la fusion suivante |
| 4 | Le tableau de bord | on l'ouvre | latence, coût, erreurs, distribution du score et part de trafic v1/v2 y sont visibles |
| 5 | Le journal de pilotage | on le consulte | tout ajustement (seuil, promotion, rollback) y figure avec le signal qui l'a déclenché |
