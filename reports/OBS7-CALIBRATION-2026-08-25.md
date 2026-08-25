# OBS7 — point de calibration judge/humain, état au 2026-08-25

> **MISE À JOUR 2026-08-25 (après annotation par Fabien) — le premier point de calibration existe.
> Il a trouvé un faux positif du juge dès le premier tir.** Résultats en §0 ; le reste du document
> décrit le blocage structurel qui a été levé pour y arriver.

**Verdict : le mécanisme fonctionne, le premier chiffre est tombé, et il est déjà instructif** — mais
n=3, donc c'est un test de bout en bout, pas une mesure de qualité.

---

## 0. Le premier point de calibration (2026-08-25)

Les 3 observations mises en queue ont été annotées. Appariement obtenu :

| Observation | Dimension | Juge | Humain | Verdict |
|---|---|---|---|---|
| `95ad5d4d2c8dcc82` | Hallucination | **0,0** | **0,0** | ✅ accord exact |
| `f1f5976125d6b931` | Hallucination | **0,7** | **0,0** | ❌ **désaccord — juge trop sévère** |
| `f74ac766a6c848ff` | Relevance | **0,8** | **0,5** | ✅ accord (même côté de 0,5), écart 0,30 |

| Dimension | appariées | accord | erreur absolue moyenne |
|---|---|---|---|
| Hallucination | 2 | **1/2 (50 %)** | **0,350** |
| Relevance | 1 | **1/1 (100 %)** | **0,300** |
| User Distress | 0 | — | — (juge désactivé) |

### Le désaccord est un faux positif structurel, pas du bruit

`f1f5976125d6b931` — le juge met **0,7** en expliquant :

> *« provides a plausible link for hotel booking but lacks verification for whether it is an actual
> offer or not, making it suspicious »*

Fabien met **0,0** : pas d'hallucination. **C'est l'humain qui a raison**, et l'erreur du juge est
structurelle : **un juge LLM ne peut pas vérifier une URL.** Il pénalise donc systématiquement tout
lien de réservation, simplement parce qu'il ne peut pas le contrôler.

Or **cette vérification est déjà faite, de façon déterministe, par le 13ᵉ guard**
(`hotel_link_truthfulness`, S-G12 — aucun lien hôtel non vérifié contre le ground-truth du tour). Le
juge duplique donc le travail d'un guard, et le fait moins bien.

**Correctif identifié** : amender le prompt du juge Hallucination pour qu'il **ne note pas la
vérifiabilité des liens** — ce périmètre appartient à un guard déterministe. Sans ça, chaque tour qui
produit un lien de réservation générera un faux positif d'hallucination, et le score se dégradera
d'autant plus que le produit marche bien (plus de liens = plus de faux positifs).

### 🔴 Et ce correctif est bloqué par le bug de validation (§2)

Amender un prompt de juge = une écriture d'evaluator = **le chemin qui part en timeout**. Donc :

> **Le bug de validation ne bloque plus seulement `User Distress` : il bloque désormais l'itération de
> prompt pilotée par la calibration.** C'est la boucle d'amélioration elle-même qui est gelée. Sa
> priorité monte en conséquence.

### Un signal que nous sommes aveugles à capter

`f74ac766a6c848ff` porte `human_user_distress = 1` — **Fabien a détecté de la détresse utilisateur sur
ce tour**. C'est la seule dimension où l'humain a relevé un positif dans l'échantillon… et c'est
exactement celle dont le juge est **désactivé**. À n=3 ce n'est pas une statistique, mais c'est un
argument concret de plus pour réparer la validation : la dimension aveugle est celle qui a produit le
seul signal positif.

### Ce que n=3 permet de conclure

- ✅ **Le mécanisme d'appariement fonctionne** de bout en bout — c'était l'objectif.
- ✅ **Un défaut réel et actionnable a été trouvé** au premier tir (faux positif sur les liens).
- ❌ **Aucun chiffre d'accord n'est exploitable** : 50 % sur 2 observations n'a aucune valeur
  statistique. Ne pas reporter « 50 % d'accord » comme un indicateur.
- Le n croît seul avec le trafic organique (5 % × 2 juges actifs). Relancer le script
  périodiquement ; il est idempotent.

---

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
| Premier point de calibration | ✅ **atteint** | 3 observations appariées le 2026-08-25 (§0). Accord Hallucination 1/2, Relevance 1/1 — **n trop petit pour un chiffre**, mais un faux positif structurel du juge est identifié. |
| Plafond de dépense écrit | ❌ | Action Fabien sur la console OpenAI (§3). |

---

## 5. Ce qui reste, par propriétaire

**Fait le 2026-08-25 :** ~~annoter les 3 items~~ ✅ → premier point de calibration produit (§0).

**Fabien :**
1. Poser le plafond OpenAI. ⚠️ **Le viser au niveau PROJET, pas organisation** : le concierge et la
   synthèse consomment OpenAI eux aussi, donc un plafond dur au niveau org couperait le produit et pas
   seulement les juges. Et un « Monthly spend limit » **seul n'est qu'une alerte** — il faut activer
   « Enforce a hard limit » pour qu'il bloque.
2. Trancher : monter temporairement le `sampling` des 2 règles actives pour accélérer le n ? (modif de
   config de production, non prise ici)

**À instruire (chantier technique) — priorité relevée :**
3. **Réparer la validation de model config côté Langfuse.** Ce n'est plus seulement `User Distress` qui
   est bloqué : le correctif du faux positif sur les liens (§0) est lui aussi une écriture d'evaluator,
   donc **la boucle d'amélioration pilotée par la calibration est gelée**. Commencer par les logs
   `langfuse-web` pendant une tentative d'activation, et comparer l'egress OpenAI de `langfuse-web` vs
   `langfuse-worker`.
4. Une fois réparé, deux écritures à faire : (a) amender le prompt Hallucination pour qu'il **cesse de
   noter la vérifiabilité des liens** (périmètre du guard `hotel_link_truthfulness`), (b) créer une
   version de `User Distress` sans `conversation_history`, puis l'activer.

---

## Reproduire

```bash
set -a; . ./.env; set +a
.venv/bin/python scripts/langfuse_judge_calibration.py                      # l'accord (ou son absence)
.venv/bin/python scripts/langfuse_judge_calibration.py --queue-missing --dry-run
```
