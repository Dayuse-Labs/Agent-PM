# OBS5 — Feedback utilisateur 👍/👎 rattaché au tour

**Projet : AgentB2C.** Zone annoncée : `facade.py` + `web/**`. Branche `obs5-user-feedback`
(worktree). Modèle : Sonnet · piloté. Référence : `OBS2-LANGFUSE-BRIEF.md` §3,
`PLAN-OBS-LANGFUSE-2026-07-29.md` (D-OBS-5, fenêtre 4). Dépend d'OBS4 (mergée, PR #66) : le
`trace_id` exposé est celui de la trace UNIQUE concierge+feuille.

## Problème traité

Le `user-feedback` BOOLEAN a été réservé en OBS3 (`scores.py` ne l'émet pas — c'est volontaire,
voir plus bas) mais rien n'existe encore : ni le `trace_id` côté SSE, ni le mécanisme de scoring, ni
l'UI. Cette session câble les trois, du tour Langfuse jusqu'au clic 👍/👎 dans le widget.

## Entrées lues (avant d'écrire ce doc)

- `HANDOFF.md` (blocs OBS4, OBS3, latence 2026-07-28/29 — notamment la confirmation que
  `WIDGET_CHAT_TRANSPORT=sse` est **actif en prod** depuis le 2026-07-29 14h55, pas seulement en
  dev : ma mémoire d'une session précédente disant l'inverse était périmée).
- `OBS2-LANGFUSE-BRIEF.md` §3 (le snippet `@langfuse/browser` cité par le prompt de lancement).
- `agents/b2c_concierge/b2c_concierge/facade.py` en entier (957 lignes) : `CONTRACT_KEYS` (frozen,
  verrouillé par `test_active_filters.py::assert CONTRACT_KEYS == frozenset(...)`), `turn_observation`
  (`observability.py`), la boucle SSE de `chat_stream`, `register_v3_routes`.
- `libs/b2c_common/b2c_common/observability.py` (`turn_observation` yield le span Langfuse — son
  attribut `.trace_id` existe nativement, confirmé en lisant `langfuse/_client/span.py`) et
  `libs/b2c_common/b2c_common/scores.py` (`GUARD_SCORE_NAMES`/`_SCORE_CONFIG_IDS` : `user-feedback`
  n'y figure pas — cohérent, ce score n'est pas émis par le même mécanisme que les 16 scores OBS3).
- `web/vendor/templates/chat_clean.html`, `web/vendor/static/js/chat/{api,stream,state,i18n}.js` et
  `handlers/{send,responses}.js`, `ui/messages.js` (dispatch `data-action`, `addMessage`).
- `web/Dockerfile` + `scripts/run_widget_proxy.py` (lu, **pas modifié** — hors zone) : c'est le
  service Railway `widget` qui sert RÉELLEMENT le front en prod (pas seulement un outil de dev,
  malgré son commentaire d'en-tête) — seule origine que le navigateur voit, tout `/v3/*` est
  reverse-proxyé génériquement vers le concierge privé.
- Recherche externe (docs Langfuse + code source `@langfuse/browser` + une discussion GitHub
  self-hosted) — détail dans la section Décision ci-dessous.

## Décision à trancher AVANT le code — le prompt de lancement suppose une architecture qui ne tient
pas telle quelle sur NOTRE instance self-hosted

Le prompt cite le pattern officiel Langfuse : le navigateur appelle Langfuse **directement** avec la
clé publique (`@langfuse/browser`, `LangfuseBrowserClient({publicKey})`, `POST
.../api/public/ingestion`, `Authorization: Bearer <publicKey>` — vérifié dans le code source du
package). C'est le pattern documenté et celui de `langfuse-examples/applications/user-feedback`.

**Ça ne marche pas tel quel ici, pour une raison concrète, pas une préférence de style :**

1. **CORS.** Le navigateur du widget tourne sur l'origine `widget` (Railway), Langfuse sur une AUTRE
   origine (`langfuse-web-production-272b.up.railway.app`). Un appel `fetch()` cross-origin direct
   exige que le serveur Langfuse réponde avec des en-têtes CORS permissifs sur
   `/api/public/ingestion`. Une discussion GitHub self-hosted (« CORS issue when reporting scores
   client-side in self-hosted setup ») confirme : **aucun support CORS officiel ou intégré côté
   self-hosted à ce jour** — la réponse suggère de patcher le handler ou de gérer ça au niveau proxy.
   Le pattern `@langfuse/browser` marche nativement sur **Langfuse Cloud** (qui doit poser ces
   en-têtes pour ses propres clients) ; rien ne garantit la même chose sur notre instance self-hosted
   3.224.3. Non re-vérifié en live par une requête réelle (ça demanderait de patcher le serveur
   Langfuse partagé pour tester — décision à ne pas prendre seul), mais le risque est documenté
   ailleurs qu'une simple intuition.
2. **Notre widget a DÉJÀ un principe architectural inverse, écrit noir sur blanc.** Le docstring de
   `scripts/run_widget_proxy.py` (le service Railway `widget`, celui qui sert vraiment le prod) :
   *« The browser only ever talks to ONE origin (this proxy): no CORS, no CSP connect-src issue, no
   cross-origin cookie problem »* — poussé jusqu'à proxier `/api/track` (Amplitude) plutôt que de
   laisser le navigateur l'appeler en direct. Un appel navigateur→Langfuse direct romprait cet
   invariant pour la première fois dans ce repo.

**Proposition (à valider par toi avant que j'écrive une ligne de JS) : router le score via une
NOUVELLE route sur le concierge, dans le même fichier que le reste (`facade.py`), pas un appel
direct.**

- `register_v3_routes` (facade.py:951-957) appelle déjà `app.add_route("/v3/chat", ...)` etc. J'y
  ajoute `POST /v3/feedback`. **Zéro fichier touché hors zone** : `run_widget_proxy.py` proxie déjà
  *tout* `/v3/*` génériquement (`if path.startswith("/v3/"): self._proxy("POST")`, pas une liste
  d'URLs codées en dur) — donc la nouvelle route est automatiquement joignable depuis le navigateur
  sans toucher au proxy.
- Le handler réutilise le client Langfuse déjà configuré côté concierge (celui que
  `turn_observation`/`scores.py` utilisent avec la SECRET key) pour poser le score serveur → serveur.
  Le navigateur, lui, ne voit ni clé publique ni clé secrète : il envoie `{trace_id, value,
  comment?}` à notre PROPRE API, protégée par le MÊME `X-Internal-Api-Key` que `/v3/chat` déjà.
- L'invariant réel du prompt (*« jamais de secret key dans le navigateur »*) est satisfait — en fait
  renforcé : le navigateur ne voit plus aucune clé Langfuse du tout, publique ou secrète. Ce que je
  m'écarte, c'est la MÉCANIQUE suggérée (poster directement avec la clé publique), pas l'invariant
  de sécurité lui-même.
- Bénéfice induit : la création du score passe par `client.create_score(...)` (API Python déjà
  éprouvée par les 16 scores OBS3), donc **zéro nouveau mécanisme d'auth à valider en prod** — pas de
  pari sur le support serveur du Bearer-clé-publique-seule ni sur un patch CORS. Et le endpoint hérite
  du contrôle d'accès existant (`X-Internal-Api-Key`), alors qu'un appel direct navigateur→Langfuse
  avec la clé publique serait un endpoint d'écriture ouvert à quiconque lit cette clé (elle est
  destinée à être publique par design, donc lisible par tout visiteur du site).
- Coût du changement de plan : ça touche à l'esprit du prompt de lancement (« posté par le front »),
  pas seulement à l'exécution. D'où cette section, à valider avant d'écrire du code.

**Si tu préfères qu'on tienne au pattern officiel (navigateur→Langfuse direct)**, la voie existe mais
demande d'abord un test en direct contre l'instance réelle (CORS + support du Bearer clé-publique
côté self-hosted 3.224.3 — aucun des deux n'est garanti par la doc), et probablement un
`OPTIONS`/CORS à poser côté serveur Langfuse — hors zone `facade.py`+`web/**`, coordination Railway
requise comme OBS0/OBS8. Je recommande la route proxée ci-dessus, plus simple et sans pari
d'infrastructure partagée.

## Étapes

1. **Obtenir le GO sur la décision ci-dessus** avant tout code.
2. **`trace_id` sur le frame `progress`, pas `done`** (contrainte structurelle, pas un choix de
   goût) : `done` porte le payload `_finalize()` qui EST `CONTRACT_KEYS`, verrouillé par un test
   d'égalité stricte (`test_active_filters.py`) — y ajouter une clé casse ce test iso-contrat avec
   agent-usa. `progress` est un dict libre (`_sse("progress", {})`), déjà utilisé pour le TTFT — on y
   ajoute `"trace_id": lf_span.trace_id if lf_span is not None else None`. Deux points d'émission
   dans `chat_stream._body()` (le chemin vide et le chemin `kind == "progress"` de `_drive`) + le
   frame `progress` de `_crash_body()` (toujours `None` là : le setup a échoué avant l'ouverture de
   `turn_observation`, honnête). `/v3/chat` (JSON, non-stream) : **inchangé**, hors périmètre exprès
   par le prompt de lancement.
3. **Ne pas confondre `trace_id` (Langfuse) et `turn_id` (contrat iso-agent-usa, `uuid4().hex`
   d'idempotence)** — deux identifiants par tour, deux origines, ne servent pas à la même chose.
4. **Nouvelle route `POST /v3/feedback`** dans `facade.py` (+ `register_v3_routes`) : body
   `{trace_id, value, comment?}`, même garde `_api_key_error` que `/v3/chat`. Score posé avec un `id`
   déterministe `f"user-feedback-{trace_id}"` (idempotence Langfuse documentée : un re-post avec le
   même `id`+`name` le même jour calendaire ÉCRASE plutôt que duplique — permet à un clic
   👍 puis 👎 de corriger sans laisser deux scores). `dataType="BOOLEAN"`, `value=1.0`/`0.0` (jamais
   `True`/`False`, même convention que `scores.py`). No-op silencieux si Langfuse désactivé (même
   contrat que tout le reste : ne jamais lever, ne jamais bloquer l'UI).
5. **Choix d'implémentation à trancher en codant** : petite fonction inline dans `facade.py`
   utilisant `get_langfuse()` (déjà importé/exposé par `observability.py`), plutôt qu'ajouter une
   fonction dans `scores.py` (hors zone stricte `facade.py`+`web/**`) — sauf si tu préfères la
   cohérence avec les 4 autres fonctions `score_*` et acceptes que ça déborde légèrement sur
   `libs/b2c_common/**`.
6. **Front — capter le `trace_id` par tour, pas globalement** : `runStreamedTurn` (send.js) doit
   retourner le `trace_id` lu sur le frame `progress`, `sendMessage()` le propage jusqu'au rendu du
   message assistant (`addMessage(data.response || data.context)`, send.js ~L752) et le pose en
   `data-trace-id` sur CE bloc `.message` précis — plusieurs réponses peuvent être visibles à la fois
   dans le fil, chacune doit noter sa propre trace, pas la dernière connue globalement.
7. **UI 👍/👎** : deux boutons sous chaque bulle assistant qui porte un `trace_id` non nul (absent →
   pas de bouton, jamais un bouton mort). Suivre le pattern `data-action` déjà en place
   (`ui/messages.js::setupActionHandlers`), `getFeedbackEndpoint()` dans `api.js` sur le même modèle
   que `getWelcomeEndpoint`/`getStreamEndpoint` (dérivé de `/v3/chat`). État après clic : accusé
   visuel (« merci »), pas de désactivation dure — un second clic doit rester possible et corriger
   (cf. idempotence ci-dessus).
8. **i18n** : libellés (`feedback_helpful`/`feedback_not_helpful`/`feedback_thanks`) dans `i18n.js`,
   au moins fr/en (les autres langues déjà présentes dans le fichier, à compléter si le temps le
   permet — dégradation propre si absent : vérifier ce que fait `t()` sur une clé manquante avant de
   décider si un fallback explicite est nécessaire).
9. **CSS** : nouveau module `feedback.css` + import dans `index.css`, à la suite de `hotels.css`.
10. **(optionnel, à discuter)** Créer le score config Langfuse `user-feedback` (BOOLEAN) via le
    serveur MCP `langfuse`, comme les 16 configs d'OBS3 — pas obligatoire pour que le score s'ingère
    (`scores.py` documente déjà ce cas), mais utile pour la validation UI et l'annotation queue
    d'OBS7. Si fait, ne PAS toucher `observability/langfuse/score-configs.json` (zone OBS7) : soit on
    laisse ce fichier se resynchroniser lors d'une prochaine session OBS7, soit tu me dis d'ajouter
    juste l'entrée.
11. **Vérification réelle** : `bash scripts/run_local.sh` + un tour réel (clés Langfuse réelles) →
    `trace_id` présent sur le frame `progress` (inspection réseau), clic 👍 → `listScores` (MCP
    `langfuse`) retrouve le score `user-feedback` sur la bonne trace avec le bon `configId` (si créé),
    un second clic 👎 sur la MÊME trace écrase (pas de doublon — à vérifier en vrai, pas supposé).
    Vérification navigateur (CDP headless, cf. mémoire des sessions précédentes) pour prouver le
    rendu réel des boutons, pas seulement les tests offline.

## DoD

- Gates verts : `pytest -q`, `ruff check .`, `mypy agents libs`, `dayuse_guardrails.sh`.
- `trace_id` présent sur `progress` (SSE), absent de `CONTRACT_KEYS`/`done` (test qui verrouille
  l'un ET l'autre).
- `POST /v3/feedback` : offline (client Langfuse enregistreur, comme `test_facade_langfuse.py`) +
  vérifié en vrai contre l'instance réelle (score visible, `configId` si config créée, idempotence du
  second clic).
- Suite offline reste inerte sans clés `LANGFUSE_*` (même invariant que tout OBS2-OBS4).
- UI : boutons visibles seulement quand un `trace_id` existe pour ce message, testés dans un
  navigateur réel (CDP), pas seulement lus dans le code.
- HANDOFF à jour (mécanisme retenu, écart par rapport au prompt de lancement et pourquoi, ce qui
  reste pour OBS7).

## Hors périmètre

- Le score config Langfuse (item 10) reste optionnel — à confirmer avec toi, pas un blocant du DoD.
- L'annotation queue alimentée par `user-feedback=0` : OBS7, pas ici (juste s'assurer que le score
  émis est filtrable/consommable par ce futur chantier — même nom, même convention 0.0/1.0).
- `observability/langfuse/**` et le reste de `scripts/**` (annotation queue, seed, etc.) : zone OBS7,
  fenêtre 4, en parallèle.
- Feedback implicite (retry, copier-coller, etc.) : hors scope, explicite uniquement (👍/👎).
- Un commentaire libre associé au score (`comment`) : le prompt ne demande qu'un BOOLEAN — je pose le
  paramètre `comment` optionnel côté route (gratuit, RGPD-safe puisqu'il resterait dans Langfuse, le
  canal sanctionné) mais **pas d'UI de saisie de texte** sauf demande explicite : ça change beaucoup
  la maquette pour un besoin non exprimé.

## Pièges

- **`CONTRACT_KEYS` est verrouillé par un test d'égalité stricte** (`test_active_filters.py`) — toute
  tentation de glisser `trace_id` dans le payload `done`/`chat` JSON casse ce test et l'iso-contrat
  agent-usa. Piège déjà découvert en lisant le code, pas à re-découvrir en CI.
- **`run_widget_proxy.py` est le service de PROD `widget` sur Railway**, pas juste un outil de dev
  malgré son commentaire d'en-tête — vérifié via `web/Dockerfile` (`CMD [... "run_widget_proxy.py" ...]`).
  Toute solution qui suppose un serveur front différent en prod serait fausse.
- **`WIDGET_CHAT_TRANSPORT=sse` est actif en prod depuis le 2026-07-29** (HANDOFF, addendum 14h55) :
  le chemin `progress` existe donc réellement en prod aujourd'hui, la feature n'est pas conditionnée
  à un futur rollout.
- **La clé publique Langfuse est UNIQUE pour tout le projet** (une seule instance partagée
  dev/prod, déjà noté en OBS3) — si jamais la voie « navigateur direct » était retenue malgré tout,
  la clé serait un littéral statique dans `chat_clean.html`, pas une variable d'env à faire
  transiter par `run_widget_proxy.py` (qui ne fait QUE la substitution Jinja regex de 9 tags connus).
- **Idempotence des scores Langfuse** : un re-post écrase seulement si `id` ET `name` ET la date
  (granularité jour) correspondent TOUS — sinon c'est un doublon, pas une mise à jour. À vérifier en
  vrai avec un double-clic dans le même test de vérification, pas supposé depuis la doc seule.
- **Un message assistant affiché AVANT que `trace_id` soit connu (fallback JSON, échec d'ouverture du
  SSE)** doit dégrader proprement : pas de bouton de feedback plutôt qu'un bouton qui échouerait
  silencieusement. Le prompt ne demande le câblage que côté SSE — le confirmer explicitement dans le
  rendu (`data-trace-id` absent ⇒ pas de bouton), pas une supposition implicite.
