# OBS8 — Upgrade ClickHouse 24.10 → 25.12.11.4, en restant sur Langfuse v3

**Projet : Railway, projet `Langfuse` (`bf0d2e04-…`), env `production`, région `europe-west4-drams3a`.**
Service concerné : `clickhouse`. Aucun code AgentB2C modifié, aucune modification de
`langfuse-web`/`langfuse-worker` (restent pinnés `3.224.3`).
Modèle : Sonnet · **piloté, jamais loop** (porte à sens unique, single-node sans HA).
Décisions : brief `OBS2-LANGFUSE-BRIEF.md` §12.3 · `PLAN-OBS-LANGFUSE-2026-07-29.md` D-OBS-2
(**supersédée le 2026-08-24 : v4 est GA**).

**Statut de ce document : GO DONNÉ le 2026-08-24 — exécution volontairement différée.** Rien n'a encore
été muté sur Railway. La différence avec l'état du 07-31 : **plus rien ne bloque**. Le gate « GO écrit de
Fabien » est levé et la décision D (communication) est fermée. L'exécution du runbook ne dépend plus que
du choix d'une fenêtre par Fabien.

---

## GO — 2026-08-24

**GO donné.** Cible confirmée : `clickhouse/clickhouse-server:25.12.11.4`. Trois vérifications faites
avant de figer, dont deux qui corrigent le document de juillet.

### 1. Le numéro de patch a été revérifié (le piège en bas de fichier, honoré)

- Le tag git `v25.12.12.1-stable` **existe** dans le repo ClickHouse (postérieur à `v25.12.11.4`).
- Mais l'image Docker **`clickhouse/clickhouse-server:25.12.12.1` n'existe pas**. Le plus haut tag
  Docker publié sur la branche 25.12 reste **`25.12.11.4`** ; le tag flottant `25.12` n'a pas bougé
  depuis 2026-05-01.

**Donc la cible de juillet était déjà la bonne** — mais c'est maintenant un résultat de vérification,
pas une valeur non revue. **Nouveau piège à retenir : un tag git ClickHouse n'implique pas une image
Docker publiée.** Toujours vérifier Docker Hub, jamais le seul changelog.

### 2. Pourquoi PAS 26.x — la question reviendra, voici la réponse

- Le `docker-compose.yml` de Langfuse sur `main` pin **`clickhouse-server:25.12` aujourd'hui**, après
  la GA v4. C'est la version contre laquelle l'amont teste réellement.
- ClickHouse 26.x **mal-planifie la requête `scores.all` de Langfuse** : régression introduite par
  [CH PR #104268](https://github.com/ClickHouse/ClickHouse/pull/104268) en 26.5.1.651
  (`query_plan_top_k_through_join`), corrigée par
  [CH PR #110722](https://github.com/ClickHouse/ClickHouse/pull/110722) en 26.7.1.1334 et backportée en
  26.7.2.11 / 26.6.2.108 / 26.5.6.70. Symptôme rapporté côté Langfuse :
  [langfuse#14178](https://github.com/langfuse/langfuse/issues/14178) (page Scores qui crashe sur
  26.5.1), et Langfuse garde une PR draft **ouverte** ([#16072](https://github.com/langfuse/langfuse/pull/16072),
  2026-08-13) qui reproduit encore des problèmes d'analyzer.
- **Le rayon d'impact est exactement la page Scores dont OBS3 et OBS7 dépendent.** 26.3 LTS est
  *antérieure* à la régression et serait probablement saine — mais « probablement sain et non testé par
  l'amont » n'est pas un argument suffisant sur l'instance qui porte nos scores.
- Conséquence sur la décision A : **le second saut vers 26.4 est abandonné comme cible.** 26.4 est
  non-LTS et déjà hors support. Le successeur naturel sera la version que Langfuse pinnera elle-même.

### 3. Le caveat que le document de juillet ne disait pas : 25.12 n'est pas LTS

ClickHouse ne patche que **les 3 dernières stables** (~3 mois de support) ; les LTS sortent deux fois
par an (mars/août) et sont supportées 12 mois
([doc officielle](https://clickhouse.com/docs/faq/operations/production)). **25.12 est donc hors support
de patchs depuis ~mars 2026** — ce que confirme l'arrêt des publications Docker après `25.12.11.4`.

**Il faut donc corriger la motivation affichée de ce chantier.** On n'échange pas 14 mois sans patchs
contre une version à jour : on échange une version très ancienne contre **la version que l'amont teste**,
elle-même hors fenêtre de patchs. Le gain réel n'est pas sécuritaire, il est fonctionnel :

> **La vraie raison de faire OBS8, c'est de débloquer v4. Pas de rattraper des patchs de sécurité.**

### 4. Ce qui a changé le contexte : v4 est GA

**Langfuse v4 est GA depuis le 2026-08-17** ([changelog](https://langfuse.com/changelog/2026-08-17-langfuse-v4)),
et **v3 ne reçoit des patchs de sécurité que jusqu'à fin janvier 2027**. La décision `D-OBS-2` (« pas de
v4 maintenant, dernière = `4.0.0-rc.3` ») est **supersédée**.

OBS8 n'est donc plus une préparation spéculative : c'est **l'étape 1 d'une migration à échéance**, et
l'amont dit explicitement de la faire d'abord et de pouvoir attendre ensuite aussi longtemps qu'on veut.
La migration v4 elle-même se découpe en 3 étapes indépendantes, chacune laissant le déploiement dans un
état stable (cf. OBS9).

---

## Pourquoi (ne pas re-litiger)

> ⚠️ **Mis à jour le 2026-08-24** : ce paragraphe disait « v4 n'est pas à l'ordre du jour ». **Elle l'est**
> — v4 est GA depuis le 2026-08-17 et v3 n'est patché que jusqu'à fin janvier 2027. L'upgrade ClickHouse
> reste découplable, mais elle n'est plus optionnelle à horizon 5 mois. Cf. bloc « GO — 2026-08-24 » §4.

v4 exige ClickHouse ≥ 25.12 (26.4 recommandé), et *« Langfuse v3 releases are fully compatible with
current ClickHouse versions »* — donc l'upgrade ClickHouse est **découplable** de la migration serveur
v4. C'est le **seul prérequis bloquant** pour v4, sans risque de migration serveur associé. Confirmé dans la doc Langfuse
elle-même : *« Upgrade ClickHouse before the server upgrade. Langfuse v3 releases are fully compatible
with current ClickHouse versions, so you can perform the ClickHouse upgrade on your existing v3
deployment and operate it as long as you like before continuing. »*
([langfuse.com/self-hosting/deployment/infrastructure/clickhouse](https://langfuse.com/self-hosting/deployment/infrastructure/clickhouse))

## État constaté (2026-07-31, reconnaissance en lecture seule, aucune mutation)

- **Services du projet** : `langfuse-web` (`langfuse/langfuse:3.224.3`), `langfuse-worker` (idem),
  `clickhouse` (`clickhouse/clickhouse-server:24`), `postgres` (`postgres-ssl:16`), `minio`,
  `redis:8.2.1`.
- **Version ClickHouse réelle** : le tag flottant `:24` résout vers **`v24.10.2.80-stable`** (image
  construite le 2024-11-19). Le tag est gelé depuis cette date (pas de re-push) — donc pas de dérive
  silencieuse, mais aussi plus aucun patch de sécurité reçu depuis ~14 mois.
- **Topologie** : **single-node, non clusterisé** (`numReplicas: 1`, aucun Keeper/Zookeeper) — pas de
  scénario de version mixte entre répliques, mais aussi pas de haute disponibilité : un upgrade raté =
  interruption complète jusqu'à correction ou restauration.
- **Volume ClickHouse** : id `9ca0e17e-…`, limite 50 Go, usage réel **~9,83 Go (19,7 %)** — marge très
  confortable pour un backup + l'upgrade.
- **« Autres producers Dayuse »** : **il n'y en a pas — tranché par Fabien le 2026-08-24.** Le constat de
  juillet (« invisibles depuis l'infra Railway ») restait vrai techniquement : le partage se fait au niveau
  applicatif Langfuse (clé API/projet), pas au niveau infra, donc rien dans Railway ni dans ce repo ne
  pouvait répondre. **La réponse ne pouvait venir que d'un humain, et elle est : AgentB2C est seul.**
  → décision D fermée, plus aucune communication à faire.

## Risques vérifiés (recherche 2026-07-31, sources citées)

1. **La fenêtre de compatibilité officielle de ClickHouse est d'environ un an.** Doc officielle :
   *« We never recommend running different versions […] when the release dates are more than one year
   [apart]. If the difference is more than one year: upgrade with downtime (stop all servers, upgrade
   all servers, run all servers), or upgrade through an intermediate version. »*
   ([clickhouse.com/docs/operations/update](https://clickhouse.com/docs/operations/update)). Notre
   écart réel : `v24.10.2.80` (nov. 2024) → 25.12 (déc. 2025) ≈ **13 mois**. **Au-delà de la fenêtre
   garantie**, d'où la méthode « upgrade with downtime » retenue en décision B.
   ⚠️ **Note du 2026-08-24** : ce qui compte est l'écart entre les *dates de release* des deux binaires
   (13 mois), pas le temps écoulé depuis — mais l'ancienneté du binaire installé est maintenant de
   ~21 mois, ce qui ne change pas la méthode et renforce juste l'intérêt de ne plus repousser.
2. **Le rollback devient à sens unique dès que la nouvelle version a écrit/mergé des données.**
   Preuves concrètes : un upgrade 25.3→25.8 suivi d'un retour en arrière a crash-loopé sur le nouveau
   format de marks (`DB::MarkType::MarkType`) — [GH #86837](https://github.com/ClickHouse/ClickHouse/issues/86837).
   Un cas similaire (24.6→24.7) a mis des parts en quarantaine (`detached/broken-on-start_*`), avec
   échec de `ATTACH PART` même sur l'ancien binaire — [GH #68408](https://github.com/ClickHouse/ClickHouse/issues/68408),
   [GH #68198](https://github.com/ClickHouse/ClickHouse/issues/68198). **Aucun mécanisme
   `min_compatible_version` documenté pour désactiver ce comportement.** ⚠️ **Conséquence directe** :
   contrairement à OBS0 (`langfuse-web`/`worker`, où re-pinner l'ancien tag suffisait), **re-pinner
   `clickhouse:24` après un démarrage réussi de la nouvelle version n'est PAS un rollback fiable.**
3. **Mécanique d'upgrade Docker** : confirmé par un mainteneur ClickHouse — bump du tag, restart sur le
   même volume, migration de métadonnées automatique au boot, mêmes garanties qu'en bare-metal
   ([GH #66434](https://github.com/ClickHouse/ClickHouse/issues/66434)). Échec observable (pas de
   corruption silencieuse) : crash-loop, erreur de parsing de config, ou parts mises en quarantaine —
   jamais un succès silencieux avec données corrompues
   ([Altinity — Fixing the ClickHouse Crash Loop](https://altinity.com/blog/fixing-the-dreaded-clickhouse-crash-loop-on-kubernetes)).
4. **Bug mémoire >25.5.2 — vérifié en direct, RÉSOLU avant 25.12.** Les versions ClickHouse **25.5.3
   à ~25.6.x** avaient un rapport de fuite mémoire non bornée sur les opérations de suppression
   ([Langfuse GH Discussion #10314](https://github.com/orgs/langfuse/discussions/10314) →
   [langfuse/langfuse#7764](https://github.com/langfuse/langfuse/issues/7764) →
   [ClickHouse/ClickHouse#82627](https://github.com/ClickHouse/ClickHouse/issues/82627)). Root cause
   identifiée (régression de [PR #81694](https://github.com/ClickHouse/ClickHouse/pull/81694),
   backporté), corrigée par [PR #83607](https://github.com/ClickHouse/ClickHouse/pull/83607)
   (mergée 2025-07-13, `pr-must-backport`) — soit 5 mois avant la coupure de la branche 25.12
   (25.12.1, 2025-12-18). **Ce bug spécifique ne concerne donc pas notre cible 25.12.x.**
5. **Durée d'indisponibilité attendue** : dominée par le nombre de tables/parts à réattacher, pas par
   le volume en Go — pour notre taille (~9,8 Go, peu de tables), l'upgrade lui-même devrait être de
   l'ordre de quelques secondes à moins d'une minute par saut, hors temps de validation
   ([GH #49659](https://github.com/ClickHouse/ClickHouse/issues/49659), doc officielle recommandant
   ~30 s d'attente post-démarrage).

## Décisions (statut au 2026-07-31 — GO de Fabien reçu : « applique tes recommandations »)

| # | Question | Statut | Détail |
|---|---|---|---|
| **A** | Cible immédiate | ✅ **ACTÉE — 25.12.x** | Le minimum réellement requis par v4 ; 26.4 reste « recommandé », pas bloquant. Un second saut court 25.12→26.4 (bien dans la fenêtre d'un an) se fera plus tard, proche d'OBS9. |
| **B** | Nombre de sauts | ✅ **ACTÉE — un seul saut** `v24.10.2.80-stable` → `v25.12.11.4-stable` | Méthode « upgrade with downtime » explicitement sanctionnée par ClickHouse pour un écart > 1 an, naturelle pour un single-node (pas de cohabitation de versions à gérer, pas de Keeper). |
| **C** | Fenêtre | ✅ **LIBRE (2026-08-24)** — au choix de Fabien | La contrainte était l'invisibilité du trafic des autres producers. **Il n'y a pas d'autres producers** (cf. D), donc plus rien n'impose une fenêtre nocturne : n'importe quel créneau calme convient. Seul critère restant : ne pas lancer l'upgrade juste avant de devoir s'absenter, la porte étant à sens unique (cf. risque #2). |
| **D** | Communication | ✅ **FERMÉE (2026-08-24)** — sans objet | Tranché par Fabien : **AgentB2C est le seul producer de cette instance Langfuse.** Il n'y a personne à prévenir. Les étapes 2 et 10 du runbook deviennent N/A. Ce n'était pas observable depuis Railway (le partage est applicatif, pas infra) — d'où le blocage de juillet, levé par une réponse humaine et non par une découverte technique. |
| **E** | Bug mémoire 25.5.2+ | ✅ **RÉSOLU, confirmé par preuve** | Root cause = régression mémoire introduite par [PR #81694](https://github.com/ClickHouse/ClickHouse/pull/81694) (backporté), symptôme trackée dans [ClickHouse/ClickHouse#82627](https://github.com/ClickHouse/ClickHouse/issues/82627) (référencée par [langfuse/langfuse#7764](https://github.com/langfuse/langfuse/issues/7764)) — **corrigée par [PR #83607](https://github.com/ClickHouse/ClickHouse/pull/83607), mergée le 2025-07-13, labellisée `pr-must-backport`/`pr-backports-created`**, donc bien avant la coupure de la branche 25.12 (25.12.1 publiée 2025-12-18, 5 mois plus tard) et a fortiori avant 26.4 (2026-04). **25.12.x est sûr vis-à-vis de ce bug spécifique — plus un gate bloquant.** |

**Les cinq décisions sont désormais actées.** A, B, E l'étaient depuis le 2026-07-31 ; **C et D ont été
tranchées le 2026-08-24** — C devient libre parce que D est fermée (pas d'autres producers, donc pas de
trafic tiers à ménager). **Plus aucune décision ne bloque l'exécution.**

Ce qui reste avant de lancer le runbook n'est plus une décision mais un choix d'agenda : Fabien pose une
fenêtre. Rappel de la raison pour laquelle ce n'est pas anodin malgré l'absence de tiers : le saut est une
**porte à sens unique** dès que la nouvelle version a accepté du trafic (risque #2), et la topologie est
**single-node sans HA** — un échec est une coupure complète jusqu'à correction ou restauration.

**Version cible figée** : `clickhouse/clickhouse-server:25.12.11.4` — **revérifiée le 2026-08-24** :
c'est toujours la plus haute image Docker publiée sur la branche 25.12 (le tag git `v25.12.12.1-stable`
existe mais **sans image**). Cf. bloc « GO — 2026-08-24 » §1. Revérifier quand même si l'exécution est
encore repoussée de plusieurs semaines.

## Plan — backup (avant CHAQUE saut, pas une fois pour tout le chantier)

1. `volumeInstanceBackupCreate` sur le volume ClickHouse (`9ca0e17e-…`), immédiatement avant le saut.
2. `volumeInstanceBackupLock` juste après, pour empêcher une rotation/GC avant validation complète.
3. Vérifier `referencedMB` ≈ usage live (~9,8 Go) — capture non vide confirmée, même discipline qu'OBS0.
4. **Ne jamais réutiliser un backup d'un saut précédent pour rollback un saut suivant** — chaque saut a
   son propre point de restauration.

## Plan — fenêtre (communication devenue sans objet)

- ~~Préavis / messages encadrants aux autres producers.~~ **N/A depuis le 2026-08-24 : AgentB2C est le
  seul producer (décision D).** Section conservée pour que la raison reste lisible si un second producer
  apparaît un jour — dans ce cas, tout ce qui est barré ici redevient obligatoire.
- Fenêtre réservée généreuse (30-45 min) même si l'upgrade lui-même est de l'ordre de la minute : le
  temps réel à couvrir est **détection + décision + rollback éventuel**, pas juste le redémarrage.
- Si rollback nécessaire après mise en trafic (cf. risque #2) : la fenêtre sert aussi de « période
  calme » pour minimiser les données perdues entre le backup et la restauration.

## Plan — rollback

**Critères de déclenchement** (vérifiés après CHAQUE saut, calqués sur les 5 critères OBS0, adaptés
ClickHouse) :
1. Le conteneur n'atteint pas un état sain sous N minutes (crash-loop, erreur de parsing de config).
2. Logs de démarrage montrant des parts cassées/quarantainées (`detached/broken-on-start_*`) ou des
   échecs d'attach.
3. Langfuse (UI ou `/api/public/*`) renvoie du 5xx ou des résultats vides sur une requête dont la
   donnée est connue pour exister (spot-check d'une trace connue avant l'upgrade).
4. Un tour synthétique (même pattern qu'OBS0 : `X-Dayuse-Synthetic: 1`, `X-Client-Session-Id` dédié)
   n'apparaît pas dans Traces sous la latence attendue.
5. Signe de rupture rapporté par un autre producer Dayuse sur l'instance partagée.

**Procédure, explicitement en deux paliers** (le point critique de ce plan, absent d'OBS0) :

- **Le nouveau binaire n'a jamais atteint un état sain** (échec immédiat, aucun trafic accepté) :
  re-pinner le tag exact précédent (`clickhouse/clickhouse-server:24` résolu = `v24.10.2.80-stable`,
  à figer en tag exact plutôt que la référence flottante `:24`) et redéployer via
  `serviceInstanceDeployV2` (**pas** `redeploy`/`serviceInstanceRedeploy`, qui rejoue le digest déjà
  déployé — piège déjà découvert en OBS0). **Rollback fiable.**
- **Le nouveau binaire a démarré sain et a accepté du trafic**, même brièvement : re-pinner l'ancien
  tag **n'est pas considéré fiable** (format de parts/marks à sens unique, cf. risque #2 sourcé) —
  restaurer depuis le backup verrouillé pris juste avant ce saut (`volumeInstanceBackupRestore`).
  **Conséquence explicite acceptée à l'avance, pas découverte en incident** : toute donnée ingérée
  entre le backup et la restauration est perdue.
- Aucun chemin de rollback « gratuit » n'existe une fois un saut allé en trafic un moment — c'est une
  porte à sens unique par saut, atténuée uniquement par un backup juste avant et une validation rapide
  après.

## Étapes (runbook — à exécuter une fois le GO donné, PAS fait dans cette session)

Par saut (répété une fois pour 25.12.x, une seconde fois plus tard pour 26.4 si retenu) :

1. Reconfirmer la version cible exacte contre **Docker Hub** (pas seulement le changelog — cf. §1 du
   bloc GO), la doc Langfuse ClickHouse, et le statut du bug mémoire >25.5.2 (§E). **Fait le 2026-08-24 :
   `25.12.11.4` confirmée.** À refaire seulement si l'exécution glisse de plusieurs semaines.
2. ~~Message « ça démarre » aux producers identifiés.~~ **N/A — pas d'autres producers (décision D).**
3. `volumeInstanceBackupCreate` + `volumeInstanceBackupLock` sur le volume ClickHouse, vérifier capture
   non vide.
4. Re-pinner le tag exact du service `clickhouse` (jamais un tag flottant `:24`/`:25`) via
   `serviceInstanceUpdate`.
5. Déployer via `serviceInstanceDeployV2`.
6. Surveiller `deploymentLogs`/`environmentLogs` : démarrage propre vs. signatures de crash-loop/parts
   cassées.
7. Health check : ClickHouse joignable, `/api/public/health` Langfuse OK, une requête sur une trace
   connue renvoie la donnée attendue.
8. Tour synthétique de bout en bout (pattern OBS0), confirmer son apparition dans Traces.
9. Go/no-go : si tout est vert, passer au saut suivant (ou clore) ; sinon exécuter le palier de
   rollback correspondant ci-dessus.
10. ~~Message « terminé, tout est vert » (ou « rollback effectué, voici l'impact ») aux producers.~~
    **N/A — pas d'autres producers (décision D).**
11. Mettre à jour le tableau de suivi `PLAN-OBS-LANGFUSE-2026-07-29.md` (ligne OBS8) et le bloc
    HANDOFF daté — seulement une fois tous les sauts validés.

## DoD

- ClickHouse à la version cible convenue (≥ 25.12, confirmée par digest/label comme dans la
  reconnaissance de ce document), tag épinglé en exact (pas de tag flottant).
- Aucune part en quarantaine (`detached/broken-on-start_*`) après upgrade.
- Tour synthétique de bout en bout retrouvé dans Langfuse, zéro erreur d'export sur les 3 services
  AgentB2C.
- Scores OBS3, trace distribuée OBS4, judges OBS7 toujours fonctionnels (spot-check, ils dépendent tous
  de requêtes ClickHouse).
- ~~Communication faite avant/après aux producers.~~ **N/A (décision D : aucun autre producer).**
- Tableau de suivi + HANDOFF mis à jour.

## Hors périmètre

- **Toute migration serveur v4** — c'est OBS9. ⚠️ La raison a changé : ce n'est plus « pas de GA
  stable » (v4 est GA depuis le 2026-08-17) mais un simple découpage de chantier. L'amont autorise
  explicitement à rester en v3 aussi longtemps qu'on veut après l'upgrade ClickHouse ; échéance réelle
  = fin janvier 2027 (fin des patchs v3).
- Tout changement de version `langfuse-web`/`langfuse-worker` (restent `3.224.3`).
- Tout changement de code AgentB2C.
- **26.4 est abandonné comme cible de suivi** (révision du 2026-08-24) : non-LTS et déjà hors support,
  et 26.x casse la page Scores de Langfuse (cf. bloc GO §2). Le prochain saut se décidera en suivant le
  pin de Langfuse lui-même, pas le mot « recommended » de sa doc.

## Pièges / à revérifier à l'exécution (ne pas figer depuis cette recherche)

- Le tag flottant `:24` est gelé depuis 2024-11-19 (aucune dérive), mais **ne jamais laisser un tag
  flottant après l'upgrade** — même piège que `latest` sur `langfuse-web`/`worker` en OBS0.
- **Revérifié le 2026-08-24** : `25.12.11.4` est toujours la plus haute **image Docker** de la branche,
  et le bug mémoire >25.5.2 reste sans objet pour 25.12. À refaire seulement si l'exécution glisse encore
  de plusieurs semaines.
- ⚠️ **Piège découvert le 2026-08-24 : un tag git ClickHouse ≠ une image Docker publiée.** `v25.12.12.1-stable`
  existe côté git sans image correspondante sur Docker Hub. Vérifier la cible sur **Docker Hub**, jamais
  sur le seul changelog ou la seule liste de tags GitHub — sinon le `serviceInstanceUpdate` pin une image
  inexistante et le déploiement échoue au pull.
- ⚠️ **Ne pas « moderniser » la cible vers 26.x** sans relire le bloc GO §2 : la régression d'analyzer
  ClickHouse 26.x casse la requête `scores.all` de Langfuse, soit exactement OBS3/OBS7.
- Les migrations ClickHouse propres à Langfuse (`CLICKHOUSE_MIGRATION_URL`,
  `LANGFUSE_AUTO_CLICKHOUSE_MIGRATION_DISABLED`) sont une couche distincte de la migration
  binaire/on-disk de ClickHouse lui-même — comme `langfuse-web`/`worker` ne bougent pas dans ce
  chantier, aucune nouvelle migration applicative Langfuse ne doit se déclencher ; à confirmer dans les
  logs `langfuse-web` au redémarrage malgré tout.
- Topologie single-node confirmée (pas de Keeper) : pas de scénario de cohabitation de répliques à
  gérer, mais aussi **aucune haute disponibilité** — un upgrade raté est une coupure complète jusqu'à
  correction ou restauration, pas un failover transparent.
