# Juges Langfuse : gpt-4o-mini contre gpt-6-luna (2026-10-19)

> gpt-4o-mini s'arrête le 2027-01-14. Les 3 évaluateurs Langfuse actifs (Hallucination v2, Relevance v1,
> User Distress (no history) v1) tournent dessus. Ce rapport mesure la dérive **avant** toute écriture
> sur l'instance. Rien n'a été modifié sur Langfuse.

## 1. Ce que gpt-6-luna accepte (sonde L1, OpenAI direct)

Forme de requête du juge Langfuse (doc LLM Connections) : `temperature 0`, `top_p 1`, `n 1`, outil
`extract` forcé, `max_tokens 256`.

| Variante | gpt-6-luna | gpt-4o-mini |
|---|---|---|
| telle que documentée (`max_tokens`, pas d'effort) | **400** `max_tokens` non supporté | 200 |
| `max_tokens` + `reasoning_effort: none` | **400** `max_tokens` non supporté | 400 (effort inconnu) |
| `max_completion_tokens`, pas d'effort | **400** « Function tools with reasoning_effort are not supported » | 200 |
| `max_completion_tokens` + `reasoning_effort: none` | **200** | 400 |
| pas de plafond, pas d'effort | **400** (outils + effort par défaut) | 200 |
| pas de plafond + `reasoning_effort: none` | **200** | — |

**Conséquence : basculer seulement le modèle dans Langfuse casserait les 3 juges** (400 à chaque
exécution, visibles seulement comme erreurs de règle). Il faut, dans la configuration de modèle de
chaque évaluateur :

- `max_tokens` désactivé, ou remplacé par `max_completion_tokens` ;
- `{"reasoning_effort": "none"}` en « provider options ».

Le MCP `upsertEvaluator` ne pose que `{provider, model}`. Ces deux réglages passent donc par l'UI.

## 2. Dérive hors ligne (L2)

Le montage :

- **Prompts** : ceux de l'instance live (export `listEvaluators`).
- **Variables** : le mapping des règles (`query` ← input, `generation` ← output,
  `last_user_message` ← input).
- **Requête** : la forme ci-dessus, chaque modèle dans la variante qu'il accepte.
- **Corpus, 53 observations `v3.chat`** :
  - 13 portent une annotation humaine `human_*` (2026-07-31). C'est le seul ancrage humain : la
    calibration OBS7 n'a que 3 paires.
  - 40 viennent des runs H3' `h3p-2026-10-19-plan-r1`.
- **Coût** : 318 appels, 0 erreur, ~0,03 $.

| Juge | accord juge/juge (même côté de 0,5) | MAE juge/juge | contre l'humain, n=13 : mini / luna | score moyen mini → luna |
|---|---|---|---|---|
| Hallucination | **52/53 (98 %)** | 0,067 | 13/13 (MAE 0,000) / 13/13 (MAE 0,038) | 0,00 → 0,07 |
| Relevance | **48/53 (91 %)** | 0,189 | 12/13 (MAE 0,169) / 12/13 (MAE 0,181) | 0,78 → **0,69** |
| User Distress | **53/53 (100 %)** | 0,000 | 12/13 / 12/13 | 0 → 0 |

**Barre fixée avant la mesure** : luna au moins aussi proche de l'humain que mini, et au moins 80 %
d'accord juge/juge. **Elle est tenue sur les 3 juges.**

### Ce qui bouge

- **Relevance baisse d'environ 0,09 en moyenne.** Les 5 désaccords sont tous des relances courtes
  (« Je confirme », « Lyon », « oui », un ZIP seul).
  - La règle ne passe au juge que le message courant, pas la conversation.
  - luna le lit à la lettre : « the query only says "Lyon", so the date, budget, time slot… are not
    established ». mini, lui, est indulgent.
  - Ni l'un ni l'autre n'a tort sur ce qu'on lui montre. Le défaut est dans le mapping, connu
    depuis OBS7.
  - À la bascule, **la série Relevance changera de niveau sans que le produit ait changé** : il faut
    noter la date dans le dashboard.
- **Hallucination** : un seul désaccord, sur `qa14707-near-11580-en`. luna note 0,65 parce que la
  réponse suppose que 11580 est à Mexico. C'est justement le cas réel de #145 (un ZIP américain nu,
  sans marché, part au Mexique).
- **Contrôle du montage** : sur `f1f5976125d6b931`, le faux positif d'OBS7 (0,7 en ligne avec le
  prompt v1), les deux modèles donnent 0,0 avec le prompt v2. Le montage reproduit bien le correctif
  v2.

## 3. Bascule faite le 2026-10-27

**Écritures sur l'instance (Fabien, UI, 14:08-14:15Z)** :
- `gpt-6-luna` est ajouté en modèle personnalisé sur la connexion OpenAI.
- Chaque évaluateur a une nouvelle version : Hallucination v4, Relevance v2, User Distress
  (no history) v2. Chacune porte `gpt-6-luna`, avec « Output token limit » (`max_tokens`) coupé et
  « Additional options » = `{"reasoning_effort": "none"}`.
- Ces réglages se trouvent derrière l'icône à droite de « Custom model configuration ». Un réglage
  grisé est un réglage coupé, donc non envoyé.
- Prompt, variables et définition du score sont identiques à la version d'avant (API, ancien id
  contre nouvel id). Les 3 règles pointent les nouvelles versions.

**Contrôle live** : pas de règle temporaire. Les 3 règles à 5 % ont tourné sur du trafic réel entre
14:16 et 14:33Z. Résultat : 4 exécutions sur `gpt-6-luna`, 0 erreur, et chaque score écrit.

| Heure | Règle | Score | Jetons de sortie |
|---|---|---|---|
| 14:16:57Z | `obs7-relevance-v3chat` | 1.0 | 44 |
| 14:29:18Z | `obs7-hallucination-v3chat` | 0.0 | 53 |
| 14:29:44Z | `obs7-relevance-v3chat` | 0.95 | 43 |
| 14:32:39Z | `obs7-user-distress-v3chat` | 0.0 | 27 |

Aucune génération gpt-4o-mini, tous environnements, de 14:15:28Z à 14:36Z.

**Ce que le §1 prévoyait mal.** Une version intermédiaire (Hallucination v3, 14:06Z) sur
`gpt-6-luna` a tourné **sans** 400 : la v3.224.3 demande un JSON structuré en texte, sans forcer
d'outil.
- La réponse a coûté 279 jetons de sortie pour environ 60 jetons utiles, donc le modèle
  raisonnait.
- `reasoning_effort: "none"` n'est donc pas une condition de fonctionnement sur cette version : il
  divise les jetons de sortie par 5 à 10 (27-53 contre 279).
- `max_tokens`, lui, n'a pas été testé allumé : le laisser coupé.

Référence de la configuration : `observability/langfuse/evaluators.json` (`judge_model_change`).

## Reproduire

- Les scripts sont jetables (scratchpad de session) : `judge_drift.py` et
  `probe_langfuse_judge_shape.py`.
- Lignes brutes : `evals/reports/judge_drift_2026-10-19.jsonl`, gitignoré.
- Entrées : les prompts live, les scores `human_*` et les sessions `obs6-h3p-2026-10-19-plan-r1-*`.
