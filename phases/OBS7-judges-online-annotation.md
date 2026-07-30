# OBS7 — Judges LLM-as-a-judge online + annotation queue

**Projet : Langfuse UI (projet Railway `Langfuse`)** + AgentB2C pour la config versionnée
(`observability/langfuse/**`) et l'alimentation de la queue. Branche `obs7-judges-online`.
Modèle : Sonnet · piloté. Référence : `OBS2-LANGFUSE-BRIEF.md` §5 et §6.
Décision : **D-OBS-4 — judges managés, clé LLM stockée dans notre Langfuse** (chiffrée par
`ENCRYPTION_KEY`). Ne pas rouvrir le débat « pipeline externe ».

## Prérequis bloquants (vérifier AVANT de commencer)

1. **`ENCRYPTION_KEY` posée sur l'instance** (checklist OBS0, Q3). Sans elle, aucune LLM Connection
   n'est stockable → STOP et rapport.
2. **Liste des judges managés réellement embarqués** dans le build 3.224.2 (checklist OBS0, Q1). Le
   catalogue dépend du build, pas de la doc.
3. **OBS4 mergée** : les evaluators observation-level **ne voient ni les enfants ni les sœurs** d'une
   observation. Il faut une observation racine par tour portant l'input utilisateur ET la réponse
   finale complète. Sans ça les judges notent du vide.

## Étapes

1. **LLM Connection** : provider OpenAI (ou gateway OpenAI-compatible). ⚠️ **Le tool calling est
   obligatoire** — Langfuse force un tool `extract` renvoyant `{score, reasoning}` ; un modèle sans
   structured output fait échouer le parsing. Documenter le modèle retenu et **plafonner le budget
   tokens mensuel** (Q2 du plan).
2. **Judges à activer, par ordre de valeur** (tous **observation-level** — les evaluators trace-level
   sont dépréciés, ne pas les utiliser) :
   - `User Distress`, `User Disagreement`, `Out-of-Scope Request` — BOOLEAN, conversation-level :
     littéralement nos boucles de clarification, nos villes non couvertes, la frustration utilisateur
   - `Hallucination` et `Relevance` sur l'observation racine du tour
3. **Filtres + sampling** : cibler l'observation racine par son `name` (`v3.chat` / `v3.chat_stream`),
   démarrer à **sampling bas** (5-10 %) et monter si le signal est utile. ⚠️ Le tirage est
   **indépendant par evaluator** : deux judges à 5 % ne notent pas le même sous-ensemble. Pour
   co-scorer les mêmes tours : 100 % + filtres identiques, et faire poser un **tag** par notre code
   pour décider l'échantillon côté application.
4. **Variable mapping** : chaque `{{variable}}` du prompt juge est mappée sur un champ de
   l'observation, JSONPath autorisé pour le nested. Utiliser la preview live (24 h de données) pour
   valider le mapping **avant** d'activer la règle.
5. **Exclure le synthétique** : nos tours de smoke/batterie portent le tag `synthetic`. Ne pas
   dépenser de tokens dessus, et ne pas polluer les séries → filtre d'exclusion explicite.
6. **Debug des judges** : chaque exécution crée sa propre trace, filtrable sur l'environnement
   `langfuse-llm-as-a-judge`. Statuts Completed / Error / Delayed (rate limit) / Pending — vérifier
   qu'aucune règle ne part en erreur silencieuse.
7. **Annotation queue** : créer la queue avec les score configs d'OBS3, l'alimenter automatiquement
   avec les traces `empty_shortlist=1` ou `user-feedback=0` (API annotation-queues, script dans
   `scripts/`). Objectif double : **calibrer les judges sur le jugement humain** et récolter des
   *corrected outputs* convertibles en items de dataset OBS6.
8. **Versionner la config** : `observability/langfuse/evaluators.json` + `evaluation-rules.json`
   exportés/reconstruits depuis l'API. ⚠️ Ces endpoints sont explicitement **`unstable`** : usage
   documentaire et reproductible, **jamais dans un chemin critique de CI**.

## DoD

- Une LLM Connection fonctionnelle, modèle documenté, plafond de dépense écrit.
- 3 à 5 judges actifs sur l'observation racine, sampling documenté, synthétique exclu, **zéro règle en
  erreur** sur 24 h.
- Annotation queue créée, alimentée automatiquement, **≥ 10 traces annotées à la main** par un humain
  → premier point de calibration écrit (accord judge / humain).
- Config versionnée dans `observability/langfuse/`.
- HANDOFF : bloc daté (judges retenus, sampling, coût observé sur 24 h, écart judge/humain).

## Hors périmètre

- **Aucun appel LLM ajouté dans le chemin du tour** : les judges tournent côté worker Langfuse, le
  budget ≤ 3 appels/tour est inchangé. Toute tentation de scorer en ligne dans l'agent = STOP.
- Les code evaluators managés (D-OBS-3 : refusés).
- Les evaluators trace-level (dépréciés).

## Pièges

- **Un evaluator observation-level ne lit pas les enfants.** Si l'observation ciblée ne porte pas
  elle-même le contexte nécessaire (question + réponse + éventuellement la shortlist résumée), le
  judge note à l'aveugle et produit du bruit qui décrédibilise tout le dispositif.
- **Coût** : un judge à 100 % sur toute la prod double vite la facture tokens. Commencer bas, mesurer,
  monter.
- **RGPD** : les judges lisent le contenu des messages — c'est le canal d'audit sanctionné (EU,
  self-hosted), mais la clé LLM envoie ce contenu au provider du modèle juge. **Ce point doit être
  écrit noir sur blanc dans le HANDOFF** : c'est une extension du périmètre de traitement, à valider
  par Fabien avant activation en production.
- Ne pas confondre `Contextrelevance`/`Contextcorrectness` (RAG) avec nos cas : notre contexte, c'est
  l'inventaire ES, pas un corpus documentaire.
