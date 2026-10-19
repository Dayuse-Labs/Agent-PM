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

## 3. Ce qui reste (écritures sur l'instance, après OK de Fabien)

1. Pour chacun des 3 évaluateurs, dans l'UI : modèle `gpt-6-luna` ; `max_tokens` désactivé ;
   provider options `{"reasoning_effort":"none"}`. Il faut peut-être d'abord ajouter `gpt-6-luna`
   comme nom de modèle sur la connexion LLM OpenAI.
2. Relire `listEvaluationRules` : les 3 règles doivent pointer la nouvelle version, l'id de
   l'évaluateur change à chaque version.
3. Contrôle live : une règle temporaire à `sampling 1.0` sur un filtre étroit, 1 ou 2 tours, lecture
   des scores et des erreurs d'exécution, puis suppression de la règle.
4. Mettre à jour `observability/langfuse/evaluators.json`, avec la date de changement de juge.

**Repli** si la v3.224.3 n'envoie pas ces paramètres : couper les 3 règles jusqu'à la v4 (O4, fin
janvier 2027). Elles ont produit 3 scores depuis le 09/09, la perte est faible.

## Reproduire

- Les scripts sont jetables (scratchpad de session) : `judge_drift.py` et
  `probe_langfuse_judge_shape.py`.
- Lignes brutes : `evals/reports/judge_drift_2026-10-19.jsonl`, gitignoré.
- Entrées : les prompts live, les scores `human_*` et les sessions `obs6-h3p-2026-10-19-plan-r1-*`.
