# OBS7 — point de calibration judge/humain, état au 2026-08-25

**Verdict : pas encore de point de calibration — mais le blocage n'est plus structurel.**
Le mécanisme qui rendait la mesure *impossible par construction* est identifié et corrigé ; il reste
3 observations à annoter à la main pour produire le premier chiffre.

Et **la cause documentée du blocage de `User Distress` était fausse.** La vraie est ci-dessous, elle est
plus large, et elle bloque bien plus que ce judge.

---

## 1. Pourquoi le point de calibration était impossible (et pas juste « en attente de trafic »)

Le HANDOFF du 2026-08-24 concluait que la surveillance OBS7 était bloquée par l'absence de trafic
(19 jours à zéro). C'était vrai mais incomplet : **même avec du trafic, le point de calibration ne
pouvait pas se produire.**

Deux échantillonnages indépendants ne se rencontrent jamais :

- Les **3 règles d'évaluation** tirent chacune **5 % des observations, indépendamment** (3 tirages
  distincts, documenté dans `observability/langfuse/evaluation-rules.json`).
- La **queue d'annotation humaine** était alimentée depuis une **source totalement différente** :
  `empty_shortlist == 1` (cf. `scripts/langfuse_feed_annotation_queue.py`).

Juges et humains notaient donc des **ensembles disjoints d'observations**. Mesuré en direct le
2026-08-25 :

| | n | observations communes |
|---|---|---|
| Annotations humaines (`human_*`, 2026-07-31) | 10 au niveau observation (14 scores au total) | — |
| Scores de juge (`obs7-*`, 08-24 → 08-25) | 3 | **0** |

**Zéro recouvrement.** Aucune corrélation calculable, à n'importe quel n. Ajouter du trafic n'y aurait
rien changé — il fallait changer le dispositif.

### Le correctif : alimenter la queue depuis la sortie des juges

`scripts/langfuse_judge_calibration.py --queue-missing` met en queue **exactement les observations qui
portent déjà un score de juge**. Dès qu'un humain les annote, la même observation porte les deux scores
et l'accord devient calculable.

**Le sens compte.** juge-noté → mis en queue pour l'humain. L'inverse (faire noter par le juge les
observations déjà annotées) **n'est pas possible** : les règles d'évaluation ne s'appliquent qu'aux
observations nouvellement ingérées, et cette instance n'a pas de backfill.

État après exécution le 2026-08-25 :

```
judge-scored observations: 3; already annotated: 0; already queued: 3; to queue: 0
  95ad5d4d2c8dcc82   (Hallucination = 0,    2026-08-24 12:24Z)
  f1f5976125d6b931   (Hallucination = 0.7,  2026-08-24 15:52Z)
  f74ac766a6c848ff   (Relevance     = 0.8,  2026-08-25 07:31Z)
```

**Action requise de Fabien** : annoter ces 3 items dans la queue `obs7-judge-calibration`, puis relancer
le script sans `--queue-missing`. Le script est idempotent — le relancer plus tard ne fera qu'ajouter les
nouveaux scores de juge apparus depuis.

⚠️ **n=3 ne sera pas un chiffre de calibration exploitable**, c'est un test de bout en bout du mécanisme.
Le n croît tout seul avec le trafic organique (à 5 % × 2 juges actifs). Pour l'accélérer, la seule
manœuvre est de monter temporairement le `sampling` des 2 règles actives — **décision de Fabien**, non
prise ici : c'est une modification de configuration de production.

### Signal qualité déjà lisible dans les 3 scores

`f1f5976125d6b931` — Hallucination **0,7**, commentaire du juge :

> *« The generation appears to provide a plausible link for hotel booking but lacks verification for
> whether it is an actual offer or not, making it suspicious as it aligns with no established knowledge
> and has fictional elements. »*

Le juge pointe un **lien de réservation non vérifiable**. C'est exactement le périmètre du 13ᵉ guard
(`hotel_link_truthfulness`, S-G12). À confronter à l'annotation humaine : si l'humain note bas, le juge
est trop sévère sur un lien légitime ; s'il note haut, le guard a laissé passer quelque chose. **C'est
précisément ce que le point de calibration doit arbitrer** — première illustration concrète de son
utilité.

---

## 2. 🔴 `User Distress` : la cause documentée était fausse

**Hypothèse au dossier depuis le 2026-07-31** : `evaluator_preflight_failed` causé par la **modération
OpenAI se déclenchant sur les exemples few-shot** du prompt (qui contient de la profanité explicite).

**Cette hypothèse est réfutée.** Preuves, obtenues le 2026-08-25 :

| Test | Contenu | Résultat |
|---|---|---|
| A — `upsertEvaluator` « User Distress » (profanité littérale, sans `conversation_history`) | prompt complet | **timeout 120 s** |
| B — `upsertEvaluator` nom neuf, profanité **censurée** (`f***`) | prompt complet | **timeout 120 s** |
| C — `upsertEvaluator` nom neuf, prompt **anodin de 37 caractères** (`Return true if {{x}} is the word yes.`) | trivial | **timeout 120 s** |
| D — `updateEvaluationRule` `enabled:true` (aucune écriture d'evaluator) | — | **timeout 120 s** |

Message d'erreur réel, identique dans les 4 cas :

```
Model configuration not valid for evaluator "<nom>". The operation was aborted due to timeout
```

**Le test C est décisif** : un prompt de 37 caractères sans un mot problématique échoue exactement
pareil, à la même durée. **L'échec est indépendant du contenu.** Ce n'est pas de la modération.

### La vraie cause

Le chemin d'écriture d'un evaluator (et l'activation d'une règle) **valide la configuration du modèle**
en appelant le provider, et **cet appel de validation part en timeout à 120 s**.

Le point troublant, et l'indice le plus utile : **les juges eux-mêmes fonctionnent.** `Hallucination` a
produit un score le 08-24, `Relevance` le 08-25. La connexion LLM sert donc l'**exécution** sans problème,
mais la **validation** pend. Hypothèse à tester (non vérifiée ici, faute d'accès aux logs des conteneurs
Langfuse) : la validation tourne dans **`langfuse-web`** et l'exécution des juges dans
**`langfuse-worker`** — un seul des deux aurait l'egress nécessaire vers OpenAI. À confirmer dans les logs
de `langfuse-web` au moment d'une tentative.

### Conséquences, plus larges que ce seul judge

1. **`User Distress` est inactivable** tant que ce n'est pas réglé, et **le retenter depuis l'UI ne
   marchera pas** : l'UI tape la même validation côté serveur. L'item « retenter depuis l'UI » de la
   todo est donc à remplacer par « réparer la validation ».
2. **Aucun evaluator ne peut être créé ni modifié** sur cette instance aujourd'hui. Ça bloque aussi les
   judges qui restaient à ajouter (`User Disagreement`, `Out-of-Scope Request`).
3. **Aucune écriture n'a fui** malgré les 4 échecs : 25 evaluators avant, 25 après (la validation échoue
   avant l'écriture). Rien à nettoyer.

### Défaut réel trouvé au passage, à corriger quoi qu'il arrive

La règle `obs7-user-distress-v3chat` mappe sa variable `conversation_history` sur
`metadata.$.conversation_history`. **Ce champ n'existe pas.** Vérifié sur les observations racines
`v3.chat` / `v3.chat_stream` réelles : la metadata ne contient que `resourceAttributes` et `scope`, et
l'`input` est une **chaîne simple** (le dernier message utilisateur), sans historique.

C'est la même raison qui avait fait renoncer à `User Disagreement` et `Out-of-Scope Request` (variables
`conversation_history` / `system_prompt` absentes). Donc, quand la validation sera réparée, il faudra
**aussi** créer une version du prompt sans `conversation_history` — sinon le judge tournera avec une
variable vide. Le prompt v1 dégrade proprement (« If there is no prior assistant message in
conversation_history, still judge based solely on last_user_message »), mais autant être explicite.

---

## 3. Coût OpenAI des juges : mesuré, négligeable

Pris sur la trace d'exécution réelle du juge (`environment=langfuse-llm-as-a-judge`), pas estimé :

| | |
|---|---|
| Modèle | `gpt-4o-mini` |
| Tokens | 400 in + 37 out = **437** |
| Coût unitaire | **$8,22 × 10⁻⁵ / appel** |
| Dépense totale à ce jour | **$0,000082** |

`mensuel ≈ tours_organiques × sampling × n_juges × 8,22e-5`

| Scénario | Coût/mois |
|---|---|
| 10 000 tours, 5 %, 3 juges | **~$0,12** |
| 10 000 tours, 100 %, 3 juges | **~$2,47** |
| 100 000 tours, 100 %, 3 juges | **~$24,70** |

**Le plafond de ~20 $/mois est du pur coussin** (≈243 000 appels de juge). Il reste à poser sur la
console OpenAI — action Fabien, hors CLI. `User Distress` a un prompt plus long, donc un coût unitaire
un peu supérieur, sans changer l'ordre de grandeur.

**DoD « coût réel observé » : atteint.** Pas sur 24 h de trafic dense, mais le coût unitaire est mesuré
et l'extrapolation est arithmétique, pas spéculative.

---

## 4. DoD OBS7 — où on en est vraiment

| Item de DoD | État | Note |
|---|---|---|
| Zéro règle en erreur | ✅ | Vérifié non déclarativement : 3 règles, `pausedReason` et `pausedMessage` à `null` sur les 3, y compris la désactivée. Elle n'a jamais été mise en pause par le serveur — elle est `enabled:false` depuis sa création. |
| Coût réel OpenAI observé | ✅ | Mesuré : $8,22e-5/appel (§3). |
| 3 à 5 judges actifs | ❌ **2/3** | Bloqué par la validation de model config, **pas** par la modération (§2). |
| Surveillance sur 24 h | ⚠️ | Une fenêtre de 24 h à trafic dense n'a jamais existé. Trafic organique réel : 12 tours le 08-25. Les règles tirent à 5 % → ~0,6 appel attendu par règle. **1 observé. Statistiquement normal, pas un bug.** |
| Premier point de calibration | ❌ | Mécanisme en place, **3 items en attente d'annotation humaine** (§1). |
| Plafond de dépense écrit | ❌ | Action Fabien sur la console OpenAI (§3). |

---

## 5. Ce qui reste, par propriétaire

**Fabien :**
1. Annoter les 3 items de `obs7-judge-calibration` → débloque le premier chiffre.
2. Poser le plafond OpenAI (~20 $/mois suffit largement).
3. Trancher : monter temporairement le `sampling` des 2 règles actives pour accélérer le n ? (modif de
   config de production, non prise ici)

**À instruire (chantier technique) :**
4. Réparer la validation de model config côté Langfuse — commencer par les logs `langfuse-web` pendant
   une tentative d'activation, et vérifier l'egress OpenAI de `langfuse-web` vs `langfuse-worker`.
5. Une fois réparé : créer une version de `User Distress` sans `conversation_history`, puis activer.

---

## Reproduire

```bash
set -a; . ./.env; set +a
.venv/bin/python scripts/langfuse_judge_calibration.py                      # l'accord (ou son absence)
.venv/bin/python scripts/langfuse_judge_calibration.py --queue-missing --dry-run
```
