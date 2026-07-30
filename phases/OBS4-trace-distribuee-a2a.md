# OBS4 — Une trace par tour, de bout en bout à travers l'A2A

**Projet : AgentB2C.** Zone : `libs/b2c_common/**` + `agents/**`. Branche `obs4-trace-distribuee-a2a`.
Modèle : **Opus** · piloté (touche le contrat A2A et supprime du code existant).
Référence : `OBS2-LANGFUSE-BRIEF.md` §1.2 et §12.4. Décision : **D-OBS-5**.
⚠️ Cette session tourne **en parallèle d'OBS10**, qui vit dans **un autre repo (MCP_B2C)** : aucune
contention de fichiers, pas de worktree nécessaire, mais **cette session doit produire le contrat
d'injection du traceparent** (où et sous quelle forme il part dans le champ `_meta` de l'appel de
tool) qu'OBS10 consomme. La MR d'OBS4 passe avant celle d'OBS10.

## Problème traité

Aujourd'hui le concierge et les deux feuilles produisent **trois traces séparées**, réconciliées à la
main par `dayuse_trace_id` → `langfuse.session.id`. Debugger un tour = ouvrir trois traces et les
recoller. En prime, `stamp_langfuse_session` pose `langfuse.trace.input` / `langfuse.trace.name`, qui
sont **dépréciés en v4** (l'input/output remonte sur la root observation) : c'est la seule surface
dépréciée de notre code. Cette session règle les deux d'un coup.

## Entrées à lire

`OBS2-LANGFUSE-BRIEF.md` §1.2 et §12.4 · `libs/b2c_common/b2c_common/observability.py`
(`turn_observation`, `stamp_langfuse_session`, `stamp_langfuse_turn_session`) ·
`agents/b2c_concierge/b2c_concierge/leg.py` (`_get_leg`, `a2a_request_meta_provider`) ·
`agents/*/serve.py` (ordre d'init : **init AVANT l'import agent** dans les feuilles) ·
`agents/b2c_concierge/tests/test_leaf_timeout_budgets.py` (cas leg).

## Étapes

1. **Décider et écrire le mécanisme de propagation AVANT de coder.** Deux voies possibles, à
   trancher avec une preuve, pas une intuition :
   - **baggage OTel** : `propagate_attributes(..., as_baggage=True)` côté concierge → le contexte part
     dans les headers sortants ; la feuille l'extrait automatiquement si elle est instrumentée.
   - **explicite** : le concierge envoie `trace_id` + `span_id` dans le `DataPart`/metadata A2A (on
     envoie **déjà** `dayuse_trace_id` via `a2a_request_meta_provider`), la feuille ouvre son
     observation avec `trace_context={"trace_id": ..., "parent_span_id": ...}`.
   Recommandation : **les deux ne sont pas exclusives** — le chemin explicite est déterministe et
   testable offline, le baggage couvre les attributs (session/user/version). Documenter le choix.
2. ⚠️ **Contrainte sécurité du baggage** : il part dans **tous** les headers HTTP sortants, y compris
   vers des tiers (Mapbox, MCP). N'y mettre que des **identifiants opaques** — jamais de PII, jamais
   de secret. Réseau privé Railway + bearer (D7) : acceptable, à documenter comme tel.
3. **Côté feuilles** : ouvrir une observation racine `as_type="agent"` rattachée au contexte amont,
   portant **son propre input et son propre output**. C'est ce qui remplace les stamps
   `langfuse.trace.*`.
4. **Retirer `stamp_langfuse_session`** (et son test) une fois la racine de feuille en place. Garder
   un chemin de repli honnête : **appelée en direct sans contexte amont** (peer A2A, smoke isolé), la
   feuille doit démarrer sa propre trace et rester lisible — pas de trace anonyme sans input.
5. **`stamp_langfuse_turn_session`** : réévaluer. Si le spine porte désormais une observation racine
   avec session/user propagés, il devient redondant. Ne le retirer que si un test prouve que le
   chemin A2A (batterie, smoke) reste groupé dans la vue Sessions.
6. **Vérifier qu'on ne casse ni le budget ni le TTFT** : la propagation est un attribut, pas un appel
   réseau. L'export reste un batch en arrière-plan. Le frame `progress` doit toujours partir avant
   tout travail LLM (verrou existant).
7. **Tests** : rattachement au contexte amont (trace_id identique concierge/feuille), repli sans
   contexte amont, no-op sans clés, et le cas leg de `test_leaf_timeout_budgets.py` maintenu vert.
8. **Vérification réelle** : `bash scripts/run_local.sh` + `python scripts/smoke_e2e.py` (A2A) puis
   `--contract` (/v3), session `obs4-check-01`. Dans l'UI : **une seule trace par tour**, contenant
   le concierge et la feuille, Agent Graph complet, usage toujours compté **1×**, vue Sessions
   toujours peuplée.

## DoD

- Gates verts : `pytest -q`, `ruff check .`, `mypy agents libs`, `dayuse_guardrails.sh`.
- Smoke : **une trace = un tour**, concierge + feuille dans le même arbre, sur les deux chemins
  (façade `/v3` **et** pilotage A2A).
- `langfuse.trace.input` / `langfuse.trace.name` : **plus aucune occurrence** dans le code (le grep
  est la preuve) → dette v4 soldée.
- Vue Sessions toujours fonctionnelle (regroupement par conversation).
- HANDOFF : bloc daté (mécanisme retenu et pourquoi, ce qui a été supprimé, comportement en appel
  direct de feuille).

## Hors périmètre

- Les requêtes ES de MCP_B2C dans la trace : c'est **OBS10**, dans le repo MCP_B2C (traceparent W3C
  dans le champ `_meta` de l'appel de tool).
- Datasets, judges, feedback front.
- Toute modification de `evals/**`, `scripts/**`, `.github/**` (zone OBS6, worktree parallèle).

## Pièges

- **Ne pas créer de trace géante par conversation.** La reco Langfuse et la nôtre : 1 trace = 1 tour,
  1 session = 1 conversation. Une trace par conversation rend l'UI et les judges inutilisables.
- **Ordre d'init dans les feuilles** : `setup_langfuse` AVANT l'import du module agent — ADK
  `lite_llm` binde `acompletion` à l'import. Piège déjà payé en OBS1, ne pas le rejouer.
- **`instrument_litellm=False` dans les feuilles** reste vrai : `generate_content` d'ADK EST la
  generation. Une seconde instrumentation double tokens et coût.
- `session_id` : US-ASCII, **< 200 caractères**, sinon silencieusement droppé.
- **`flush()` jamais `shutdown()`** dans les lifespans (le client a son atexit ; un shutdown depuis
  un lifespan gèle le cycle suivant — c'est ce qui avait figé la suite serve-auth).
