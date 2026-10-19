# Lessons — corrections de Fabien à réappliquer

## 2026-10-19 — sortie de gpt-4o-mini (auto-constatées)

1. **Un désaccord entre modèles n'est pas une régression avant d'avoir lu l'entrée EXACTE.** J'ai
   annoncé un « bug de contrat QA14707 » parce que luna répondait `answers_pending="no"` à « Je
   confirme » / « yes, Paris » là où mini disait « yes ». La trace montrait `LAST ASSISTANT QUESTION`
   absente (le tour 1 avait cherché sans rien demander, DQ12), et le prompt impose « no » dans ce
   cas : luna avait raison, mini violait la règle. Règle : pour chaque désaccord décisif, imprimer
   l'entrée telle que le modèle l'a reçue (message, récents, question) **avant** d'arbitrer, et
   arbitrer contre le texte du prompt, pas contre l'ancien modèle.
2. **Un garde qui refuse une baseline doit vérifier la santé de la pile, pas seulement le juge.**
   Mon garde « 0 erreur de juge, 0 test rouge » a laissé `--update-baseline` écrire un 0/32 mesuré
   sur une pile dont 112 tours sur 118 étaient `degraded` (MCP injoignable). Et l'IP de sortie avait
   changé en pleine session. Règle : avant tout run live, `curl -4 ifconfig.me` et un appel MCP ; et
   lire les `status=` des tours avant de croire un score.

## 2026-07-29 — sperf4 rebasé (auto-constatée en reprenant une branche vieille d'un jour)

1. **Une branche vérifiée n'est vérifiée que contre le `main` de l'époque.** La PR
   #45 était complète, mesurée et screenshotée — puis S-CX7/8/9 ont réécrit le
   MÊME chemin de rendu de carte. Le merge ne signalait que 4 conflits textuels,
   aucun sur le vrai défaut : le CTA de réservation (`state.hotelPicks`, rempli
   uniquement depuis le corps JSON bloquant) disparaissait de toutes les cartes en
   mode SSE, `skipCarousel` empêchant tout redessin à `done`. Règle : avant de
   merger une branche qui a dormi, lister les features livrées entre-temps qui
   touchent la même surface et se demander **d'où chacune tire sa donnée** dans le
   nouveau chemin — le diff ne le dira pas.
2. **Deux chemins qui doivent produire la même chose doivent appeler la MÊME
   fonction, pas deux copies d'accord.** `build_hotel_picks` a déménagé de
   `facade.py` vers `profile.py` pour que la frame et le payload l'appellent tous
   les deux sur le même profil : égalité par construction, pas par revue. Corollaire
   d'ordonnancement : la frame doit être émise APRÈS `apply_profile_delta` +
   `record_search_shortlist`, sinon les picks décrivent le tour PRÉCÉDENT (vérifié
   en remettant le `yield` à sa place d'origine → le test tombe).

## 2026-07-28 — sperf4 (auto-constatées, attrapées par la capture navigateur)

1. **Rendre une donnée PLUS TÔT casse tout ce que le rendu tardif tenait pour
   acquis.** En affichant le carrousel dès la frame `hotels`, j'ai rendu les
   cartes AVANT `setLanguage(response_language)` (qui ne tournait qu'à `done`) :
   cartes en anglais, texte en français juste dessous. Aucun test ne le voit,
   seule la capture l'a montré. Règle : quand on avance un rendu dans le temps,
   lister ce que le chemin nominal exécute AVANT lui (langue, marché, state) et
   se demander pour CHAQUE élément d'où il viendra maintenant — souvent la
   réponse est « il faut que le serveur me l'envoie plus tôt aussi ».
2. **Un événement intermédiaire doit porter TOUS les flags qui décident du
   rendu, pas seulement la donnée.** La frame SSE `hotels` ne portait que
   `hotels` : impossible de savoir si le tour était une clarification (que le
   POST bloquant rend SANS carrousel) ni dans quelle langue peindre. 3 lignes
   côté spine + facade suppriment la divergence entre les deux transports —
   beaucoup moins cher que de la documenter comme un « cas rare ».
3. **Piloter le vrai widget vaut mieux qu'une page statique.** Le driver CDP
   (`websockets` + `Page.captureScreenshot`, deep-link `?q=` qui auto-envoie,
   clics par `Runtime.evaluate`) permet des captures MULTI-TOURS et des états
   mi-stream (cartes visibles pendant la synthèse), impossibles avec
   `--screenshot`. Compter les éléments en DELTA DOM par tour (pas en absolu) :
   sinon le carrousel du tour précédent fait passer un test « pas de doublon ».

## 2026-07-29 — diagnostic « 0 résultat sur Paris » (deux causes dans une seule capture)

1. **Un « 0 résultat » n'est jamais auto-diagnostiquable depuis le code** : le 2026-07-29,
   la même capture d'écran contenait DEUX causes distinctes (année 2023 hallucinée par
   le modèle, et cutoff du jour dépassé) qui produisent le même écran vide. Les deux ont
   été séparées en lisant les ARGUMENTS RÉELS de `search_offers` dans Langfuse
   (`traces/{id}` → observations), pas en relisant le code. Réflexe : trace d'abord,
   `date` envoyée d'abord — le multi-turn était sain.
2. **Un test qui code en dur une date proche pourrit en silence.** Deux tests de
   carryover asseraient `"2026-07-28"` : ils sont devenus des tests de date PASSÉE le
   2026-07-29 et ont cassé sur un guard légitime. Toute date de test comparée à
   `date.today()` doit être calculée (`date.today() + timedelta(...)`), jamais littérale.

## 2026-07-29 — S-CX9 (auto-constatée, attrapée par la capture navigateur post-deploy)

1. **Un test de rendu qui appelle le renderer EN DIRECT ne teste pas ce que
   l'utilisateur voit.** Mes 25 assertions jsdom passaient en donnant le dict hôtel
   à `createHotelCard`. Mais le widget fait passer le payload par
   `normalizeV3Response`, **qui whiteliste les champs** : `rating` y était,
   `rating_count` non. Résultat en prod : la carte affichait « 5,0/5 » pour un
   hôtel noté par UNE personne — l'unique façon dont cette ligne peut tromper — et
   toutes mes assertions étaient vertes. Règle : **tout champ nouvellement lu par
   un renderer doit être asserté À TRAVERS le mapping de payload réel**, pas à
   côté. Corollaire : quand on ajoute la lecture d'un champ backend côté widget,
   vérifier d'abord qu'il traverse `normalizeV3Response` (whitelist explicite).
2. **La capture navigateur sur le déployé n'est pas une formalité de fin.** C'est
   elle, et rien d'autre, qui a montré le compte d'avis manquant : jsdom vert,
   payload prod correct (`rating_count: 1` bien présent dans la réponse HTTP), et
   pourtant faux à l'écran. Le trou était entre les deux.
3. **Chercher la règle de design déjà ÉCRITE dans le CSS avant d'en proposer une.**
   L'artefact proposait un CTA jaune ; `hotels.css` avait déjà consigné en S-CX5
   que le dégradé chaud est réservé au CTA qui part vers le tunnel. La bonne
   réponse était de faire respecter la règle existante (bleu nuit pour le CTA
   conversationnel), pas d'en inventer une nouvelle.

## 2026-07-28 — sperf (auto-constatée, attrapée en live post-deploy)

1. **Un probe pré-rollout doit envoyer le SHAPE D'APPEL EXACT du code, pas juste
   le paramètre nouveau.** J'ai probé `reasoning_effort=low` sur gpt-5.2 sans
   `temperature` — 200. Le code, lui, envoie `temperature=0.2` : litellm rejette
   la COMBINAISON (`UnsupportedParamsError`, chaque param seul passe), et en
   prod **chaque synthèse tombait en fallback leaf-verbatim silencieux**.
   Règle : construire le probe à partir des kwargs du call site (copier le
   dict), pas de mémoire — ou mieux, probe à travers la vraie fonction
   (`_generate_once`), comme l'a fait la contre-preuve du fix.
2. **Après tout rollout de modèle/params : lire les logs du service AVANT de
   déclarer les chiffres.** Le tour à 3,4 s « rapide » était en partie de la
   fausse vitesse (synthèse absente). Le signal existait déjà :
   `concierge_metric=turn … status=synthesis_fallback` — greper `status=` sur
   quelques tours réels fait partie de la vérification de déploiement, au même
   titre que le smoke.

1. **Une carte/CSS livrée sans capture navigateur n'est pas livrée.** J'ai écrit
   la CSS de `booking-card` en S-CX5, vérifié `node --check` + les tests, et
   expédié un CTA **rogné de 44 px**. Aucun test Python ni typecheck ne voit un
   pixel. Le harnais qui l'a prouvé coûte 5 minutes : page statique + la vraie
   CSS + `Chrome --headless --screenshot`, et `--dump-dom` pour lire des
   mesures calculées (`getBoundingClientRect`, `getComputedStyle`). Le faire
   AVANT de dire « fait » sur tout ce qui se voit.
2. **Cette feuille de style n'a PAS de reset `box-sizing`.** Les `<button>` s'en
   sortent (feuille UA), les `<a>` et les `<div>` non : `width: 100%` + padding
   en content-box déborde, et un parent `overflow: hidden` **coupe en silence**.
   Tout nouvel élément full-width dans `web/vendor/**` : `box-sizing:
   border-box` explicite.
3. **Un chemin client-side qui `return` tôt saute la fin du rendu.** Le filtre
   par créneau ne fait aucun tour serveur et sortait avant `addFollowUpMessage()`
   → les pick buttons disparaissaient. Quand une branche court-circuite le
   chemin nominal, lister ce que le chemin nominal dessine APRÈS le point de
   sortie, et le redessiner (ici en le restreignant à ce qui reste à l'écran).
4. **Le label d'un bouton doit décrire sa destination réelle.** « Réserver » sur
   un `href` qui ouvre la fiche hôtel promet un tunnel qu'il n'atteint pas.
   Vérifier label ↔ `href` à chaque fois que l'un des deux change.

## 2026-07-27 — erreurs de PROCESS (auto-constatées, merge + deploy)

1. **Ne jamais supprimer une branche de base tant qu'une PR pointe dessus.**
   `gh pr merge #36 --delete-branch` a supprimé `scx3-research`, qui était la
   base de #37 → GitHub a **fermé #37 automatiquement**, et refuse de rouvrir
   une PR dont la base n'existe plus. Ordre correct pour une stack :
   retargeter la PR dépendante sur `main` **d'abord**, la merger, **puis**
   supprimer. (Précise la note « merge stacked PRs top-down » du #28/#29.)
2. **Ne jamais rediriger la sortie d'une commande d'écriture vers /dev/null.**
   J'ai fait `gh pr edit 37 --base main >/dev/null` : le retarget a échoué et
   je ne l'ai pas vu, ce qui a masqué la cause pendant deux commandes.
3. **`git add -A` ramasse le WIP des autres.** Mon 1er commit a embarqué 5
   fichiers untracked d'une session S-B (dont le test llm-meter cassé connu),
   rendant la suite ROUGE sur `main` pour tout le monde. Avant le 1er commit
   d'une session : lire `git status` et **ajouter explicitement** les fichiers
   du scope, ou vérifier que chaque untracked ramassé est bien à moi.

## 2026-07-27 — scx5 (RÉCIDIVE de la leçon du 2026-07-20)

1. **Compréhension du langage = LLM en place ; décision = code. Je l'ai encore
   raté.** Pour « le moins cher » j'avais écrit une regex de détection
   d'intention (`_PRICE_SUPERLATIVE_RE`) — exactement ce que la leçon
   s10-amenity-filters interdit, et je l'avais lue en début de session. Le bon
   découpage : le triage (1 appel LLM DÉJÀ fait chaque tour, donc coût nul)
   émet un champ `pick` en **liste fermée validée en code**, et le code décide
   quel hôtel c'est (`select_cheapest_hotel`, qui ne lit jamais le message).
   La regex ne survit que comme `fallback_pick`, au même statut que
   `fallback_family` (chemin LLM-down, documenté comme tel).
   **Preuve mesurée** : sur 8 formulations probées en live (gpt-4o-mini),
   le LLM 8/8 ; la regex se serait trompée sur 4 (« je prends celui qui coûte
   le moins », « vas-y pour le plus abordable », « whichever costs the least »,
   « celui à 54 euros, le plus bas »).
   **Test anti-récidive** : `test_it_never_reads_the_message` verrouille la
   signature du resolver (`last_results` seul) — une regex réintroduite casse.
   Règle générale : avant d'écrire une regex, demander « est-ce que je détecte
   une INTENTION ou est-ce que j'applique une DÉCISION ? ». Intention → prompt
   système + enum fermée. Décision → code.
2. **Un test qui passe avant ET après le fix ne prouve rien.** Systématiquement
   désactiver le fix et vérifier que le test échoue (fait ici pour le seam
   test carte↔lien et pour le routing du pick).

## 2026-07-27 — scx3a/scx3c (auto-correction, design 3c réfuté en live)

1. **Un test offline ne peut pas valider un changement d'ARGUMENT envoyé à MCP.**
   J'avais élargi `priceRangeMax` (budget × 1,15) et écrit un test « ne pousse jamais
   un hôtel in-budget hors de la page » — il PASSAIT, parce qu'il partitionnait une
   page FIXE. Le serveur renvoie une page *différente* quand le cap change (le pool
   de candidats change, pas seulement le découpage) : en live, 10 hôtels in-budget
   → 7, et aucune taille de page atteignable ne les récupère. Règle : tout changement
   d'un argument envoyé à un service externe se vérifie par un probe live comparant
   ANCIEN vs NOUVEAU sur le même marché, avant de croire le moindre test vert.
2. **Vérifier les commentaires « live-probed » avant de les traiter comme un contrat.**
   `inject_pagination_offset` documentait « size max 50 » (probe 2026-07-23) ; en
   2026-07-27, `size` ≥ 16 renvoie un structuredContent VIDE sans `isError`. J'ai
   construit un design sur ce commentaire. Les probes vieillissent — re-probe quand
   une décision en dépend, et corrige le commentaire dans le même commit.
3. **Un référentiel de repo sœur répond souvent à la question « ce champ existe-t-il ? »**
   sans probe : `MCP_B2C/src/application/dtos/hotel-summary.dto.ts` donnait `totalReview`
   (et `search-offers.use-case.ts` le `score` + sa pondération) en 2 lectures. Le probe
   live sert ensuite à savoir si le champ est POPULÉ — les deux étapes, dans cet ordre.

## 2026-07-24 — scx1-facade-shield (review PR #34)

1. **Langue des templates : une locale déclarée non supportée → ANGLAIS, jamais le guess.**
   Les clients Dayuse couvrent de nombreux pays/langues ; le spine ne traduit que fr/en.
   J'avais chaîné `locale supportée → sinon guess_language(message)` — or les hints
   français du guess se déclenchent sur d'autres langues romanes (es/it/pt), donc un
   client espagnol pouvait recevoir du FRANÇAIS. Règle : locale déclarée mais non
   traduite → "en" directement ; le guess sur le message ne sert QUE quand aucune
   locale n'est fournie. À réappliquer à tout nouveau point de sélection de langue
   de template (le `response_language` des textes LLM, lui, reflète le texte généré).
2. **Un push forcé refusé deux fois = changer d'approche, pas insister** : reconstruire
   l'historique compatible origin (merge de la base + cherry-pick) et pousser en
   fast-forward normal.

## 2026-07-20 — s10-amenity-filters (rejet du 1er plan)

1. **Référentiels : le code des repos sœurs prime sur le probing live.** J'ai reconstruit
   le référentiel équipements en probant `get_hotel_details` sur staging alors que
   `MCP_B2C/src/shared/reference/hotel-equipment.json` + `pool-equipment-ids.ts` sont
   la source officielle (et contenaient le OR-group piscine complet que mon probe avait
   raté). L'interdit CLAUDE.md « ne pas relire le code MCP_B2C » vise la logique, pas
   les fichiers de référence — demander/regarder d'abord si un référentiel existe en local.
2. **Extraction d'intention : Fabien préfère le LLM déjà en place à une regex déterministe,**
   tant que le code garde la propriété du filtre (validation liste fermée + mapping IDs
   côté code). Ne pas sur-appliquer « déterministe partout » aux étapes de compréhension
   du langage ; l'invariant spine porte sur les DÉCISIONS (routing, valeurs de filtre),
   pas sur l'extraction.
3. **Localisation : le traitement d'un concern de recherche vit dans la feuille search,**
   pas dans le concierge — même si le concierge semblait le chemin « minimal ». Le
   concierge re-apprend via `profile_delta` (chemin déjà testé), zéro code concierge.
4. **Piège gpt-4o-mini vérifié live** : une consigne de négation (« sans piscine ») peut
   être INVERSÉE par le modèle (il a émis les 8 autres clés → AND → 0 résultat). Toujours
   tester la formulation négative en live après un changement de prompt d'extraction.
## 2026-07-27 — s-cx6 (cutoff same-day) — auto-attrapé avant commit

1. **« Aucun résultat » peut être une VÉRITÉ de donnée : vérifier la couche amont
   avant de toucher au code.** Le symptôme de Fabien ressemblait à un bug de
   plomberie ; un probe MCP direct (11 pages du pool, puis la même requête dans 3
   fuseaux) a montré que le backend n'avait réellement rien pour aujourd'hui. Le
   bug était dans la RÉPONSE (cause non nommée, remèdes hors-sujet), pas dans le
   transport. Contre-épreuve la moins chère pour un soupçon « c'est cassé » :
   rejouer la même requête dans un fuseau horaire différent.
2. **Ne jamais affirmer une cause que la donnée n'établit pas.** J'ai d'abord
   déduit « les réservations du jour sont closes » de `same_day` seul — faux pour
   un marché sans inventaire (`total=0`). Un flag de cause doit être posé par le
   composant qui OBSERVE la cause (ici la feuille, qui voit `total>0` +
   `results=[]`), jamais reconstitué en aval à partir d'un proxy.
3. **Un test unitaire qui partitionne une page ne prouve rien sur le serveur**
   (rappel S-CX3c, revérifié utile ici) : la signature `total=518 / results=[]`
   n'était visible qu'en live, et c'est elle qui distingue les deux causes.

## 2026-07-30 — OBS4 (trace distribuée A2A) — auto-attrapé en vérifiant live

1. **« Une seule trace » ne veut pas dire « un seul arbre ».** Le premier tour réel donnait bien
   1 trace, et j'aurais pu m'arrêter là : elle contenait 3 observations RACINES côte à côte, donc
   aucune arête concierge→feuille. Le trou venait de spans d'une lib tierce (`@trace_class` du
   `a2a-sdk`) que notre filtre d'export jetait, exactement AU MILIEU du saut. Vérifier un objectif de
   trace, c'est vérifier `parent_observation_id` de chaque observation, pas compter les traces.
2. **Un filtre d'export doit échouer OUVERT.** Pour reconnecter l'arbre, une liste blanche des noms de
   méthodes du chemin aurait été plus propre (6 spans au lieu de 13) mais échouerait FERMÉ : un
   renommage dans la lib rouvre silencieusement le trou. Préférer l'exclusion par préfixe de module :
   le pire cas devient « quelques spans bruyants », visible, jamais un trou invisible.
3. **Élargir un filtre d'export se mesure avant de se garder.** Exporter tout le scope tiers = 76
   observations/tour (une boucle d'events tirait des dizaines de fois) ; avec l'exclusion, 31. Le
   chiffre était à un tour réel de distance — ne pas raisonner sur « ça doit être quelques spans ».
4. **Ne pas conclure à une régression depuis un endpoint de lecture incomplet.** `configId` des scores
   remontait `null` partout : le champ n'existe simplement pas dans le modèle de réponse de
   `scores_v3.get_many_v3`. Le bon endpoint (`listScores`) le montrait non nul. Avant d'accuser son
   propre diff : vérifier que le champ lu existe dans la réponse (et `git diff` du fichier soupçonné).
5. **Chercher le hook avant de l'écrire.** ADK 2.4.0 injectait DÉJÀ le traceparent W3C dans `_meta`
   des appels MCP (`mcp_tool.py`) : le « contrat à définir » pour l'autre repo était déjà sur le fil.
   Lire le code de la lib installée AVANT d'inventer un format.
