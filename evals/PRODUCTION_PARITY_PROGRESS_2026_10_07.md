## 2026-10-08 — v36 : tentatives locales et lectures MCP bornées

**Pas de GO remplacement.** Une recherche lancée avant le géocodage est rejetée
localement, mais consommait le quota nécessaire à la seconde page budgétaire.
Le correctif distingue les tentatives modèle des lectures réseau : chaque
compteur garde la même limite opérateur. Pour une recherche ordinaire,
une tentative locale refusée ne consomme aucune lecture MCP ; la première
lecture et la page supplémentaire sont réservées après les guards. Une fois
les lectures épuisées, un nouvel appel modèle est aussi bloqué. Aucun relèvement
de limite, boucle libre, nouvelle phase LLM ou regex. Les batches multi-zone
existants conservent leur traitement séparé.

Un test causal reproduisait `geocode_required` → géocodage → première page trop
chère, avec seconde page empêchée. Il passe après correction. Trois nouveaux
tests protègent ce cas et les limites cumulées ; le test de réservation couvre
le changement de tour. **2 451 tests passés, un ignoré**, ruff, mypy (66 fichiers),
guardrails. Le code final ne change pas le triage ni les modèles.

**12 réponses comparatives** sur un nouveau parcours de production de quatre
tours : restaurant nommé → question sur un code pays → même lieu → correction
explicite vers Marietta, GA. Legacy, B2C déployé et candidat v35 sont tous **D**.
Legacy part au Vietnam, B2C conserve un pays erroné après correction ; le candidat
propose Manhattan malgré un GPS en Géorgie, puis récupère Marietta. Les traces
montrent une municipalité inventée par le triage qui efface le GPS, puis une
correspondance partielle du nom de restaurant acceptée par le géocodeur.

**Neuf réponses sur le code final** : cinq tours Dubai et quatre du nouveau
parcours. Les deux parcours complets restent **D**. À Dubai, les tours 3 et 4
retrouvent une offre à **135,25 AED**, frais compris, couvrant 09:00. Le tour 3
montre bien un rejet local puis deux lectures MCP (`from=0`, `from=5`) avec les
mêmes critères. Le blocage Marina/JLT/Al Barsha et les questions redondantes
restent ouverts. Sur le restaurant, Manhattan est encore proposé ; Marietta
est récupéré au dernier tour. **22 cartes tarifées** du code final vérifiées
contre les reçus MCP, zéro écart prix/jointure/expiration : ce contrôle ne prouve
pas la pertinence du lieu.

Deux expériences GPS intermédiaires, **18 réponses**, ont été retirées avant
le dernier rejeu et ne sont pas dans ce commit. Un champ sémantique optionnel
était omis par 4o-mini ; rendu obligatoire, il classait parfois un lieu nommé
comme « près de moi ». Ne pas réintroduire ce raccourci comme correctif GPS.
Leurs sources/revues sont archivées hors Git ; elles comptent dans le coût,
pas dans la validation du code final.

Export revérifié : 33 414 lignes / 2 000 récentes. Les quatre nouveaux messages
sont retrouvés dans quatre traces Langfuse ; quatre GPS arrondis sont adaptés
au contrat de chaque agent. Permission du fixture B2C synthétique, payload
original complet et provenance organique non certifiés. Inventaire legacy
export/Qdrant vs MCP préproduction live, dates inchangées ; comparaisons
séquentielles et variabilité modèle. `main` refetché, toujours `cbe88b9`.

**Reste prioritaire :** identité des POIs (correspondance partielle insuffisante),
GPS comme biais distinct d'une destination explicite, quartiers vs municipalités,
rayon et créneau sur multi-zone. Puis les familles déjà ouvertes : occupation,
lit bébé, besoins libres/pagination, âge durable, FAQ/caution/annulation,
provinces/corridors et langues. Les 32 familles restent incomplètes.

Étape, expériences incluses : **0,36406993 USD**, dont dernier rejeu **0,08748670**.
Cumul **91,12013914/110 USD**, provisions 11,10 incluses, réserve 10 conservée.
Tous les lots réglés, aucun runner payant actif. Pas de merge, déploiement ou
réglage Railway. Rapports privés v36-summary/v36-review et reads-v36c-diagnostic.
CI du nouveau commit à observer séparément ; étapes live ignorées ≠ évaluation.

## 2026-10-08 — v35 : budget natif et première page trop chère

**Pas de GO remplacement.** Une recherche proche peut renvoyer cinq hôtels tous
au-dessus du plafond local, malgré des offres compatibles dans les pages
suivantes. Le MCP filtre les prix en EUR ; le contrôle du plafond natif doit
rester lié à chaque offre et inclure les frais obligatoires.

La feuille lit désormais au plus une seconde page de cinq hôtels lorsque le
premier échantillon n'a aucun résultat vérifiable dans le budget. Elle reprend
exactement les arguments déjà contrôlés, avec seulement un nouvel offset MCP.
La lecture est débitée du quota existant du même outil, sans phase LLM ajoutée,
sans élargissement de critères ni nouvelle regex. Les recherches multi-zone
gardent leur propriétaire de batch existant. Les cartes restent limitées à cinq.
Une seconde page en erreur n'est pas transformée en preuve d'absence d'offres.
Ce mécanisme reste un échantillon borné, pas une recherche exhaustive.

Onze nouveaux tests couvrent récupération, quota, offset incohérent, absence de
page, panne et date divergente. Le test causal échoue quand le nouveau callback
est retiré et passe lorsqu'il est activé (fixture corrigée pour inclure la devise
au niveau offre, conformément au MCP). Test de câblage adapté. **2 448 tests
passés, un ignoré**, ruff, mypy (66 fichiers), guardrails.

**26 réponses / dix revues :** trois conversations de production, sept messages
SQL retrouvés dans Langfuse, comparés sur legacy, B2C déployé et candidat v34 ;
puis cinq tours Dubai rejoués sur v35. Grille historique A/B/C/D/F conservée.

| Parcours | Legacy | B2C déployé | Candidat v34 | Candidat v35 |
|---|---|---|---|---|
| Dubai, budget/horaires/proximité sur cinq tours | D | D | D | D |
| Chaîne près de moi, nom mal orthographié | B | C | C | non rejoué |
| Quatre adultes et deux enfants après croisière | D | C | C | non rejoué |

Le B2C déployé transforme un plafond local en EUR. Le candidat conserve AED.
Avec v35, le quatrième tour retrouve une offre à **135,25 AED**, frais compris,
qui couvre 09:00. Mais au troisième tour, une tentative de recherche avant le
geocoding a déjà consommé une unité du quota : pas de seconde page disponible.
Le premier tour redemande le lieu malgré GPS et le cinquième bloque sur les
quartiers autour de Marina, avec perte du créneau. Ces nouveaux tirages incluent
la variabilité modèle : ne pas attribuer ces écarts au callback sans preuve.

**16 cartes tarifées** vérifiées contre les reçus MCP, zéro écart prix/jointure/
expiration. Six des sept messages ont un GPS observé dans la même trace,
arrondi à quatre décimales ; il est adapté au contrat de chaque agent. Le flag
permission du fixture B2C est synthétique, la permission originale et le payload
complet sont inconnus. Ce n'est pas une fidélité native complète. Legacy utilise
export/Qdrant, les nouveaux agents le MCP préproduction live ; dates inchangées.

Une anomalie amont est documentée pour Carlton Downtown : le point MCP diffère
d'environ 22 km du centre de carte de sa page officielle contact/location.
La distance calculée par l'agent est cohérente avec le point reçu ; aucune
correction spéciale par hôtel n'a été ajoutée. À investiguer côté inventaire.

Export réactualisé : 33 414 lignes / 2 000 récentes. Sept lignes de nos propres
évaluations exclues ; quatre nouveaux messages d'une autre session récupérés
avec quatre traces Langfuse (lieu nommé, pays erroné, correction explicite).
Ils ne sont pas encore rejoués, contexte/provenance encore à vérifier.

**Reste :** GPS et ordre des outils, quartiers/rayon multi-zone et maintien
horaire, chaîne vs lieu, capacité famille, lit bébé, besoins libres/pagination,
FAQ/caution/annulation, âge durable, géographies historiques et langues. Les
32 familles prioritaires restent incomplètes et non exhaustives. Aucun modèle
par défaut changé. Étape **0,34623881 USD**, dont rejeu correctif **0,04350375** ;
cumul **90,75606921/110 USD**, provisions 11,10 incluses, réserve 10 conservée.
Tous les lots réglés, aucun runner payant actif. Sources et reçus privés hors Git.
Pas de merge, déploiement ou changement Railway. CI du nouveau commit à observer.

## 2026-10-08 — v34 : source FAQ et recherche par nom sans identité

**Pas de GO remplacement.** Le triage indique la source nécessaire à une question
(règles Dayuse, faits hôtel ou offre), avec citation du message courant. Une
question générale classée `details` rejoint la FAQ lorsque cette source est
validée et qu’aucun hôtel n’est explicitement choisi/nommé. Elle ne retire pas
les contraintes de recherche. Les règles d’arrivée concernent aussi les
utilisateurs qui n’ont pas encore réservé : le prompt ne limite plus ces règles
aux réservations existantes.

Après un triage réussi sans nom reconnu, le chemin détails ne transforme plus
la phrase entière en nom MCP. Les choix de carte, correspondances fortes de la
shortlist et noms extraits restent utilisables. Les autres appels (booking,
compare, fallback sans triage) gardent leur contrat existant : pas de migration
globale revendiquée. Aucune nouvelle regex, phase modèle ni dépendance.

Un test de routage/mémoire échouait avant correction. Huit nouveaux cas couvrent
ce routage, la conservation du créneau, absence de requête par nom sans identité,
shortlist, nom extrait, et validation du label/citation. **2 437 tests passés,
un ignoré**, ruff, mypy (65 fichiers), guardrails.

**14 réponses / quatre revues**, deux contrôles exposés comparant seulement le
triage 4o-mini et 4.1-mini, mêmes sources et autres rôles conservés. Orange County
→ FAQ → California → Anaheim : **4o C, 4.1 B**. Les deux répondent à la FAQ et
conservent samedi/15 h ; 4o redemande encore la date et propose une arrivée plus
tôt. Le county qualifié nécessite encore une ville. Hôtel nommé → âge/caution
→ annulation : **C pour les deux** ; offre datée et caution 250 USD conservées,
mais traitement de la caution avant arrivée encore inféré sans preuve.

**12 cartes tarifées** reliées aux reçus MCP : zéro écart prix/jointure/expiration.
Les deux modèles choisissent directement `faq` en live : le test forcé établit
le correctif de routage, ce tirage ne l’exerce pas causalement. La citation de
4o reformule « when ever » en « whenever » et est donc rejetée ; la famille FAQ
suffit ici. Les différences de synthèse incluent de la variabilité de génération.
Sept appels triage par modèle : **0,00515550 USD** (4o) et **0,01400640 USD** (4.1).
Échantillon trop petit pour changer le modèle par défaut ; aucun réglage Railway.

Export actualisé : 33 403 lignes / 2 000 récentes. Sept nouveaux messages, trois
sessions, retrouvés exactement dans Langfuse et préparés pour le prochain rejeu :
Dubai (cinq tours, horaires/budget/rayon autour de Marina, changement de langue),
Miami après croisière (quatre adultes/deux enfants), recherche de chaîne près de
moi. Ces sept messages **ne sont pas encore rejoués**. Les manques de contexte
natif/fuseau sont consignés par tour ; aucune donnée GPS inventée, provenance
organique non certifiée par l’API SQL.

**Reste :** lit bébé vs capacité, besoins libres/pagination, caution/annulation,
questions déjà résolues dans la synthèse, géographies historiques, âge durable,
langues et fidélité native. Les 32 familles restent incomplètes et non exhaustives.
Étape **0,17779475 USD** ; cumul **90,40983040/110 USD**, provisions 11,10 incluses,
réserve 10 conservée. Challenger arrêté, aucun runner payant actif. Rapports privés
v34-summary/v34-review, information-v34-diagnostic, new-prod-v34-inputs. Aucun
merge ni déploiement. CI du nouveau commit à observer séparément ; les anciens
jobs live/Langfuse ignorés ne prouvent aucun rejeu.

## 2026-10-08 — v33 : conserver le jour de semaine avant clarification

**Pas de GO remplacement.** Le triage existant extrait un jour de semaine demandé
pour la recherche et une citation du message courant. Le code valide le label
fermé et la citation, puis calcule la date avant l’appel A2A, même si la feuille
ne fait que demander une précision géographique. La règle de calendrier de la
feuille est déplacée sans changement dans `b2c_common.date_labels` : prochaine
occurrence strictement après aujourd’hui. Pas de nouvelle regex, phase LLM,
dépendance ni changement de modèle. Une date calendaire explicite garde priorité ;
les questions de politique ne modifient pas le jour recherché.

Deux tests multi-tours échouaient avant correction (date absente) et passent :
jour anglais/français, date de référence un jour identique, question FAQ portant
sur un autre jour, deux clarifications sans répéter date/heure. Validation du
label, citation absente/hors message et priorité de la date explicite couvertes.
**2 429 tests passés, un ignoré**, ruff, mypy (65 fichiers), guardrails.

**12 nouvelles réponses / trois revues manuelles**, même parcours de quatre tours
rejoué sur legacy/B2C/candidat. Deux messages réels corroborés SQL/Langfuse puis
deux suivis synthétiques, déjà exposés v32. Aucun nouveau holdout revendiqué.
Le candidat conserve **10 octobre et 15 h sur les quatre tours** ; le reçu MCP
final porte bien cette date et l’arrivée15h. **Cinq cartes** correspondent aux
reçus, couvrent15h et ne présentent aucun écart prix/jointure/expiration.

Notes : **legacy C, B2C D, candidat C**. Le B2C déployé sert encore le mercredi
7 octobre et redemande les horaires. Legacy maintient samedi en prose mais le
prix Staybridge99USD appartient au créneau08–14, celui couvrant15h coûte110USD ;
la disponibilité future sur export n’est pas vérifiée. Le candidat corrige le
jour, mais le triage classe la FAQ d’arrivée comme `details` et envoie la question
entière à `find_hotel_by_name` : réponse hors sujet. La clarification du county
qualifié reste répétée et les villes proches ne valident pas la pertinence Anaheim.

Export actualisé : 33 392 lignes, 2 000 récentes ; MCP direct huit outils joignables.
Aucun incident réseau pendant ce lot ; un ancien502 au compteur du proxy. Les
différences export/Qdrant et MCP préproduction restent explicites. La nouvelle
extraction sémantique reste faillible ; dates ambiguës, plages et semaines plus
lointaines ne sont pas validées par ce contrôle ciblé.

**Reste prioritaire :** ne pas traiter une question générale comme un nom d’hôtel,
séparer lit bébé et capacité enfants, mémoriser les besoins libres pour pagination,
préserver âge et politiques sourcées. Les32familles historiques, géographies,
corridors/provinces, équipements privés/inclus, langues et contexte natif restent
incomplètes. Aucun nouveau challenger4.1mini sur cette étape.

Étape **0,17236440USD** ; cumul **90,23203565/110USD**, provisions11,10 incluses,
réserve10 conservée. Aucun runner payant actif, merge, déploiement ou écriture
Railway. Sources figées65hashes, reçus et revues privés v33-summary/v33-review.
CI v32 `39354f2` réussie (37722834006), étapes live/Langfuse ignorées ; CI du
nouveau commit à vérifier séparément des tests et rejeux locaux.

## 2026-10-08 — v32 : disponibilité réelle des hôtels nommés et suivis historiques

**Pas de GO remplacement.** Une recherche par nom transmet maintenant une identité
explicite par DataPart A2A. Le concierge vérifie l’offre via son outil MCP existant
`get_hotel_details`, avant synthèse : date, UUID de formule, créneau, prix fini,
expiration et contraintes déjà présentes dans le profil (budget frais compris,
capacité et plage horaire). La formule la moins chère qui convient est retenue.
Une nouvelle recherche ne reste pas bloquée sur l’ancienne formule sélectionnée.
Sans offre vérifiée, une réponse déterministe distingue absence et erreur de
vérification ; l’identité reste utilisable pour les questions de politique hôtel.
Aucune nouvelle regex, phase LLM ou dépendance ; feuilles stateless conservées.
Les routes ordinaires de détails/compare ne sont pas globalement migrées.

Quatre tests causaux échouaient avant correction. Huit nouveaux cas couvrent le
pont A2A, le chemin concierge, absence/erreur, sélection date/créneau/budget/capacité,
expiration, formule moins chère et mauvaise identité. **2 419 tests passés, un
ignoré**, ruff, mypy (64 fichiers), guardrails. Sources figées avant rejeu : 64 hashes.

**45 nouvelles réponses / 18 revues manuelles A/B/C/D/F**, dont **15 réponses du
candidat** sur cette source. Contrôle nommé/âge/caution/annulation : neuf réponses ;
trois sessions SQL de dix messages : trente réponses ; deux suivis synthétiques
Orange County puis Anaheim : six réponses, dans les mêmes sessions. Les premiers
messages Prague étaient déjà exposés ; aucun holdout inédit global revendiqué.
**22 cartes tarifées** reliées aux reçus MCP, zéro écart prix/jointure/expiration.
Cela ne vérifie pas que la date de l’offre répond à la demande utilisateur.

Le contrôle nommé récupère une vraie offre pour le lendemain et reste à trois
phases LLM. Le parcours garde C : le moment du prélèvement de caution est encore
inféré sans preuve. Melbourne reste C pour pertinence et pagination après un
nouveau besoin non structuré. Prague : legacy D, B2C D, candidat C ; le candidat
conserve le congélateur mais transforme le besoin de lit bébé en `children=1`,
faisant passer les résultats MCP de 15 à zéro. Cela ne prouve pas l’absence de
lit bébé dans les hôtels. Le legacy confond Prague et Präg dans ce rejeu incomplet.

Orange County : la clarification California puis Anaheim garde l’heure de 15 h
mais perd samedi. Le candidat sert une offre du mercredi 7 octobre au lieu du
samedi 10 octobre : D, malgré une jointure MCP exacte. B2C annonce que tous les
hôtels ont été vus sans en avoir montré : D. Legacy conserve samedi en prose mais
une carte présente le prix d’une formule finissant avant l’arrivée : C ; sa
disponibilité future sur export reste non vérifiée.

Export actualisé : 33 368 lignes, 2 000 récentes ; dix messages des trois sessions
retrouvés dans Langfuse. GPS original Prague non disponible, un fuseau non attesté
omis ; aucune donnée native inventée. Provenance organique non certifiée. Les
écarts export/Qdrant et MCP préproduction restent distincts des défauts agent.

**Priorité suivante :** persister la date sémantique avant clarification du lieu,
sans regex ni appel modèle supplémentaire. Restent aussi occupation/équipements,
pagination sur besoins libres, géographies/provinces/corridors, âge durable,
caution/annulation, langue et couverture historique. Aucun challenger modèle
sur cette étape ni changement du modèle par défaut.

Étape **0,52444842 USD** ; cumul **90,05967125/110 USD**, provisions 11,10 incluses,
réserve 10 conservée. Aucun runner payant actif, merge, déploiement ou écriture
Railway. Rapports privés v32-summary/v32-review et diagnostics : nommé, lit bébé,
date. CI du nouveau commit à observer séparément des tests et rejeux locaux.

## 2026-10-08 — v31 : pagination après critères et cinq conversations fraîches

**Pas de GO remplacement.** La pagination est maintenant décidée après les mises
à jour de date, créneau et budget. Elle exige des résultats précédents et des
critères identiques ; sinon le curseur revient à zéro. L'instantané des critères
exclut la langue, les métadonnées de provenance et l'ordre des équipements.
Aucune nouvelle regex, phase modèle, dépendance ou modification Railway.

Quatre régressions échouaient avant le correctif et passent ensuite : nouvelle
date avec/sans résultats précédents, « plus » après zéro résultat, nouveau budget
avec intention « plus ». Les tests de pagination ordinaire restent verts.
**2 411 tests passés, un ignoré**, ruff, mypy (64 fichiers), guardrails.

**37 réponses / 16 revues manuelles**, dont 15 réponses du candidat sur la source
v31 : quatre tours Brooklyn (deux messages réels puis deux extensions synthétiques)
et cinq nouvelles sessions SQL, 11 messages, comparées legacy/B2C/candidat.
**25 cartes tarifées** reliées aux reçus MCP, aucun écart prix/jointure/expiration.
Le rejeu Brooklyn retrouve Tillary en première page. Limite causale : ce tirage
live ne répète pas le flag erroné de triage ; les quatre tests forcés prouvent
le correctif. Le parcours reste C pour l'âge redemandé et le faux filtrage d'âge.

Les cinq sessions couvrent près de moi, six tours château/Ezanville/créneaux/nuit,
chinois romantique, Morrisville sous 80 USD, congélateur puis Prague. Les échecs
sont conservés : descriptions prises pour des noms d'hôtel, style peu pertinent,
langue chinoise perdue. Le candidat conserve le besoin de congélateur au suivi,
le B2C déployé l'oublie. La FAQ brute corrige aussi un défaut de la prod historique :
la page officielle https://support.dayuse.com/hc/en-us/articles/360020362900-Can-I-book-a-night-on-Dayuse-com
confirme des offres nuit marquées d'une lune ; le refus global de la prod est
incorrect. Cela ne prouve aucune offre de nuit dans la zone demandée ni la
capacité du MCP à la chercher. Le candidat ajoute une question restaurant non demandée.

Export préflight : 33 349 lignes, 2 000 récentes ; cinq sessions nouvelles
corroborées par Langfuse. GPS original absent sur trois sessions ; Morrisville
avait aussi un historique de réservations/horaires non reconstruit. Les A de
clarification sans GPS ou sur l'homonyme Morrisville ne valident ni la recherche
ni le plafond après clarification. Provenance organique non certifiée.
Les écarts export/Qdrant et MCP préproduction restent séparés des défauts agent.

**Reste prioritaire :** identité d'hôtel présentée comme offre disponible ;
style descriptif confondu avec nom ; mémoire d'âge durable ; dates qui effacent
un créneau (triage `clear` observé sur une acceptation de demain, sans ancien
créneau dans ce rejeu) ; pertinence, chinois, géographies/provinces/corridors,
occupation et équipements privés/inclus ; conditions d'annulation/caution.
Les 32 familles historiques restent incomplètes. Aucun nouveau challenger modèle.

Étape **0,38134428 USD**, cumul comptabilisé **89,53522283/110 USD**,
provisions 11,10 incluses et réserve 10 conservée. Aucun runner payant restant.
Preuves privées : `production_parity_v18/v31-summary.private.json`,
`v31-review.private.html`, `pagination-v31-diagnostic.private.json`,
`v31-fidelity-addendum.private.json`. Aucune donnée brute dans Git.

## 2026-10-08 — v30 : conditions sourcées et suivis âge/FAQ

**Pas de GO remplacement ; modèle par défaut inchangé.** Le rejeu adaptatif
part des deux vrais messages Brooklyn/19 ans, répond aux clarifications, accepte
le lendemain et demande les conditions d’un hôtel réellement affiché. Les
extensions sont synthétiques et identifiées. Une nouvelle session arrivée de vol
→ Anaheim est extraite de SQL et retrouvée dans Langfuse (deux messages).

Corrections sans nouvelle regex, appel LLM ni outil supplémentaire :
- Détails/compare reçoivent le contexte récent et la dernière question de l’agent.
- Les champs MCP `conditions` et `commonConditions` survivent à la normalisation,
  avec portée propriété/générale distincte et extraits bornés signalés si tronqués.
- La FAQ transporte ses résultats MCP originaux en DataPart A2A, via état `temp:`
  limité au tour. Le résumé intermédiaire est supprimé : une génération de moins
  sur ce chemin, aucun changement du routage ou de l’allowlist. Les preuves FAQ
  ne deviennent pas des cartes hôtel ; aucune dépendance au Redis de la feuille.
- La synthèse distingue les recommandations nationales des règles d’une propriété.
  La note interne ne fuit pas lors d’un échec de synthèse. Une ancienne recherche
  vide ne contamine plus les preuves d’une réponse FAQ.

**64 réponses / 16 revues A/B/C/D/F, dont 6 réponses sur la source finale.**
Sources v30/v30b/v30c/v30d explicites ; les précédentes ne constituent pas une
validation intégrale du dernier code. **47 cartes tarifées** reliées aux reçus,
zéro écart prix/jointure/expiration, et quatre cartes d’identité séparées sans
preuve de disponibilité. Les retours comportent encore des C/D, conservés.

Langfuse montre l’erreur de portée : « généralement 21 ans aux USA » devenait
« Tillary exige généralement 21 ». Les conditions propres à l’hôtel indiquent
250 $ de caution, aucun âge. La première correction de prompt seule échoue encore ;
le passage des sources brutes permet enfin de distinguer ces faits dans les
rejeux FAQ, avec 4o-mini et 4.1-mini au triage.

**Échecs ouverts :** 4o-mini transforme « demain me va » en pagination, écartant
Brooklyn au profit de cinq hôtels ailleurs. La mémoire récente ne couvre que
trois messages et peut oublier l’âge. Une identité hôtel est encore décrite
comme une offre disponible demain. Certaines réponses supposent le moment du
prélèvement de caution sans preuve. North Brisbane/East London, corridors,
provinces, occupation, équipements inclus et les autres familles restent ouverts.
4.1-mini améliore certaines décisions, pas la totalité du parcours. Aucun choix
modèle global déduit de ces contrôles exposés.

**2 407 tests passés, un ignoré**, ruff, mypy (64 fichiers), guardrails.
Douze nouveaux tests depuis v29, incluant transport FAQ, scopes, erreurs, contexte
inline et dégradation. Un nom de module de test FAQ entrait en collision avec
celui de la recherche : renommé ; le run incomplet à 2 205 tests est invalidé,
les suites finales à 2 407 ont bien récupéré les tests de recherche.

Export : 33 331 lignes / 2 000 récentes. Brooklyn a un GPS natif signalé mais
payload exact absent, aucune parité complète de personnalisation revendiquée.
Anaheim n’a pas de contexte natif signalé ; devise/locale/fuseau sont attestés.
Provenance organique non certifiée. Cinq comportements de tests historiques ont
été lus et liés aux limites des rejeux ; mineurs et familles restent non validés.
Les 32 familles prioritaires et l’inventaire de 256 commits restent incomplets.

Étape **0.67701 USD** ; cumul comptabilisé **89.15388/110 USD**, provisions11,10
incluses, réserve10 conservée. Rapports privés v30-summary/v30-review et
historical-policy-mapping-v30 ; aucun message brut dans Git. Aucun merge,
déploiement ou changement Railway. CI du commit à observer séparément.


## 2026-10-08 — v27 : challenge triage et preuves d’extraction

**Pas de GO remplacement ; aucun changement de modèle par défaut.**
65 nouvelles réponses / 33 revues manuelles A/B/C/D/F : comparaison de triage
4o-mini / 4.1-mini sur le même code (32 réponses), quatre ouvertures SQL rejouées
sur ancien prod / B2C déployé / candidat (12), puis corrections/rejeux (21).
13 réponses utilisent la source finale. Les cas de modèles sont exposés, un
passage par configuration : aucun taux populationnel ni supériorité générale.

Deux corrections sans regex ni appel LLM supplémentaire : un code administratif
optionnel `null` ne supprime plus toute la zone nommée ; les chiffres des heures
et minutes extraites doivent avoir une preuve dans leur citation. Une date seule
créait 00:00–23:59 et éliminait les offres. Le dernier rejeu capture la MÊME
extraction erronée de 4o-mini, désormais rejetée ; la province retourne une offre.
Ce contrôle numérique est nécessaire, pas un oracle sémantique date/heure.

**2 370 tests passés, un ignoré**, ruff, mypy (63 fichiers) et guardrails verts. 12 nouveaux
cas ; quatre échecs reproduits avant correction (code null + trois horaires
sans preuve). La fixture du test de conservation horaire a été alignée : une
réponse 17:30 cite maintenant 17h30, et une suppression cite une suppression ;
les assertions de conservation/échec feuille restent inchangées.

4.1-mini préserve la province dans le parcours réel, mais échoue aussi à appliquer
la restriction explicite à la ville. Les deux modèles peuvent transformer Paris
en périmètre municipal strict et ne rien afficher. Le parcours de restriction
reste D, la ville simple C, le contrôle de cinq suivis final B. La frontière
explicite, les corridors, équipements privatifs/inclus, synthèse des créneaux,
conditions/âge, occupation, FAQ/annulations et matrice historique restent ouverts.

**72 cartes** jointes aux reçus MCP, zéro écart prix/jointure/expiration ;
**43 plafonds frais compris** vérifiés. Sur source finale :17 cartes / 11 plafonds.
Ces chiffres ne valident pas la pertinence : des cartes hors ville explicitement
requise sont conservées comme échecs. L’audit administratif initial comprend
quatre cartes sans reçu inverse : absence de preuve, pas preuve hors province.

Export SQL : 33 301 lignes / 2 000 récents, quatre nouvelles sessions hors IDs campagne et
quatre traces Langfuse retrouvées. Deux sessions mobiles ont un payload natif
original manquant ; leur rejeu est explicitement partiel, sans note de parité
GPS/favoris/habitudes. Bloc rendu Langfuse conservé en privé, pas réinjecté comme
requête exacte. Provenance organique non certifiée par l’API SQL.

Étape **0,58934 USD** ; cumul **86,92876 / 110 USD**, provisions 11,10 incluses,
réserve 10. Seize appels de triage par modèle coûtent respectivement 0,01034 USD
et 0,02815 USD : économie insuffisante pour justifier une baisse de qualité,
mais ce petit échantillon ne valide aucun remplacement global. Aucun runner
payant actif. Rapports privés v27-summary/v27-review et source avec 63 empreintes.
Aucun merge, déploiement ou écriture Railway.

## 2026-10-08 — v26 : périmètres administratifs et suivis

**Pas de GO remplacement.** Le concierge conserve maintenant les demandes de
périmètres administratifs / municipalités alternatives, extraites par le triage
existant. La feuille résout leurs identités typées avec Mapbox ; un disque MCP
par zone récupère cinq candidats, puis le géocodage inverse vérifie chaque hôtel
par identifiant administratif avant affichage. Trois zones / quinze candidats
au maximum, sans nouvel appel LLM ni regex. L’échantillon reste non exhaustif :
une page vide ne prouve pas une absence dans tout le département. Les périmètres
nécessitant un rayon supérieur à 200 km sont refusés sans réduction silencieuse.

Le profil et les champs de périmètre survivent aux suivis, retraits d’équipements
et erreurs. Le schéma d’outil est fermé ; les codes numériques cités sont
vérifiés contre le fournisseur. Les noms administratifs localisés sont normalisés
sans perdre les qualificatifs directionnels. Les géocodages redondants du même
tour réutilisent le résultat vérifié : un appel ensuite bloqué par le quota ne
peut plus effacer cette ancre. Une répétition du nom / pays ne doit pas réduire
une province à la ville ; une citation de changement de limites lève ce maintien.

Les logs ont montré des JSON de triage coupés à **200 tokens**, perdant budget,
horaires et équipements. Le défaut de sortie passe à **768 tokens** ; les
surcharges opérateur restent respectées. Un seul appel, mêmes modèles et aucune
écriture Railway. Le lot final ne comporte aucune troncature de triage.

**2 358 tests passés, un ignoré** ; 110 ciblés, ruff, mypy (63 fichiers) et
guardrails verts. 32 tests ajoutés ; quatre erreurs d’interface reproduites en
rouge avant correction (code numérique omis, citation reformulée, schéma libre,
repli vers une ville après échec de résolution d’une zone). Le test de câblage
compte le nouveau callback après validation du schéma MCP. Le test de plafond
attend maintenant 768 ; le contrôle des surcharges et de la désactivation demeure.

**60 réponses correctives / 20 revues A/B/C/D/F**, sur cinq versions exposées ;
**12 réponses sur la source finale**. 78/92 aboutit à un hôtel vérifié à Clichy.
Le contrôle synthétique conserve 150 EUR total, 10:30–17, le 10 octobre, puis
retire le jacuzzi, limite au 92 et passe à Lyon. Sur la source finale :
**15 cartes** jointes aux reçus MCP, **11 plafonds frais compris vérifiés**,
zéro écart de prix, expiration ou jointure. Neuf cartes sont dans les zones
attendues selon les réponses brutes Mapbox ; cela ne prouve pas la portée de la
recherche : **trois écarts de portée du profil à Brescia persistent**.

**Échec conservé :** 4o-mini choisit encore parfois la municipalité pour une
province explicitement demandée. Des versions intermédiaires résolvent la province,
mais le dernier tirage ne valide pas cette extraction. Le corridor londonien
reste en clarification. Les demandes de chambre avec jacuzzi n’ont toujours pas
la preuve d’un accès privatif/inclus. Note finale : C pour les deux parcours réels
jacuzzi et le corridor ; B pour le contrôle de suivi (question horaire inutile).
Aucun taux global ni nouvelle comparaison de population ; holdout v19 sur autre code.

Les municipalités seules peuvent également être extraites malgré la consigne de
réserver ce chemin aux alternatives / limites explicites : vérifier ce changement
de portée par rapport au rayon de ville avant lancement. Pagination multi-zone,
provinces larges, quartiers, contraintes chambre, âge/conditions, synthèse et
matrice historique complète restent ouverts. Prochaine investigation utile :
challenge E2E du modèle de triage, à source et paramètres identiques, plutôt que
conclure à partir d’une seule extraction ou changer globalement le modèle.

Nouvel export SQL : **33 298 lignes**, 2 000 récentes ; une nouvelle ouverture
hors IDs de campagne conservée, pas encore enrichie Langfuse/rejouée. Provenance
organique non certifiée. Traces et conversations hors Git. Étape **0,54902 USD**,
cumul **86,33942 / 110 USD**, provisions 11,10 incluses et réserve 10. Aucun runner
payant actif. Rapports privés `area-v26-summary` / `area-v26-review` et empreintes
`area-candidate-v26e-source` (63 fichiers). Aucun merge ou déploiement.


**Pas de GO remplacement.** Le triage existant extrait maintenant les ajouts et
retraits d’équipements du message actuel, avec enum fermé et citation littérale.
Le concierge applique cette opération avant l’appel A2A et la persiste même si
la recherche est vide. Un indicateur du tour rend ce profil prioritaire dans la
feuille : une recopie de « jacuzzi » ne peut plus écraser la piscine nouvellement
demandée. Aucun nouveau regex ni appel LLM. Les équipements inconnus/privatifs
ne sont pas assimilés à un équipement hôtel ; la couverture chambre reste à faire.

Le retrait conserve le score filter_relaxation_honored et informe la synthèse :
retirer l’exigence ne signifie pas exclure les hôtels possédant cet équipement.
Une nouvelle contrainte invalide une sélection antérieure et remet la recherche
à jour. Les valeurs contradictoires, inconnues ou non citées sont rejetées.
La présence littérale de la citation ne garantit pas la sémantique universelle.

**2 326 tests passés, un ignoré** sur la source finale ; 123 ciblés, ruff,
mypy (61 fichiers), guardrails verts. Quatre nouveaux tests de transmission
échouaient avant correction ; 19 autres couvrent validation, langues, types,
FAQ/détails et maintien des critères non modifiés.

Rejeu correctif : **16 réponses**, 11 avant la précision de formulation du retrait
puis 5 sur la source finale. NYC jacuzzi → piscine atteint désormais le MCP avec
les deux filtres sur 4o-mini. Contrôle français : ajout piscine, retrait jacuzzi,
Paris → Lyon puis retrait piscine ; date 10 octobre, 10:30–17 et plafond total
150 EUR conservés. Sur le dernier lot, **20 cartes** jointes aux reçus MCP et
**20 plafonds frais compris vérifiés**, sans écart ni expiration. L’offre piscine
du tour 2 mentionne explicitement Indoor pool dans includedAmenities ; le filtre
jacuzzi hôtel ne démontre pas l’accès inclus ou une installation privative.

Reste un défaut de synthèse : à Lyon, le texte dit que seul Novotel Gerland
couvre 10:30–17 alors que les quatre autres cartes 10–17 le couvrent aussi.
Le dernier retrait est correctement formulé. Les valeurs adultes 1 puis 2 dans
le parcours NYC ne sont pas explicitement données : provenance d’occupation à
auditer. La correction des filtres ne vaut pas réussite générale de ces parcours.

**Modèle : 11 réponses supplémentaires** sur le même code f61d9db, seul le modèle
de recherche remplacé localement par 4.1-mini. La piscine atteint le MCP et
Socastee/Myrtle Beach est résolu, mais le parcours âge finit sur une affirmation
sans preuve que deux hôtels acceptent 20 ans. Les conditions reçues ne contiennent
pas ce seuil. La feuille FAQ 4o-mini propose les hôtels de façon ambiguë, puis la
synthèse 5.2 affirme explicitement 20 ans : ne pas imputer cela directement au
modèle de recherche. Trois revues manuelles, dix cartes tarifées vérifiées ; un
seul tirage par cas et inventaire live. Aucun changement global de modèle justifié.
Les trois services isolés de ce challenge ont été arrêtés.

Nouvel export : **33 293 lignes**, 2 000 récentes. Quatre nouveaux messages dans
trois sessions hors IDs de campagne, associés exactement à Langfuse ; **12 réponses
comparatives et 9 revues**. 78/92 reste non traité : legacy propose Paris75,
B2C/candidate redemandent une ville. Turin 20:30 + trois heures : candidate porte
23:30, B2C23:00, legacy perd la durée ; formulation candidate confond encore la
borne demandée et la borne arrondie du matching. Cinq cartes candidates vérifiées.
Ne pas changer la règle de matching du site pour masquer ce défaut de formulation.

Étape complète : **39 réponses, 15 revues manuelles, 0,38861 USD**. Cumul
**85,79040 / 110 USD**, provisions 11,10 incluses, réserve 10. Aucun runner payant
actif. Comparaison fraîche effectuée avant la dernière précision du retrait ;
son protocole conserve cette version, sans prétendre que tout tournait sur la
source finale. Rapports privés amenity-v25-summary, model-v25-review et
new-prod-v25-review. Suite : géographie typée/multi-zone, FAQ et preuves par offre,
fidélité de synthèse, contraintes chambre/occupation, couverture historique/widget.
Aucun merge, déploiement ou changement Railway.

## 2026-10-08 — v24 : cohérence géographique et nouveaux suivis réels

**Pas de GO remplacement.** Le contrôle de distance s’applique désormais aussi
aux résultats Mapbox v6 avant leur acceptation. Quand la requête ville + quartier
ne fournit aucune ancre crédible de la ville, la résolution indépendante de la
ville intervient avant cette acceptation, au plus une fois. Une municipalité
exacte sélectionnée sans ambiguïté peut servir d’ancre même sans inventaire ; un
quartier homonyme de ville conserve le seuil de crédibilité par inventaire.
Aucun regex ni appel LLM ajouté. Les requêtes déjà ancrées évitent cet appel.

Six tests ajoutés : cinq échouaient avant le correctif. **2 303 tests passés,
un ignoré**, ruff, mypy (60 fichiers), guardrails. L’attente d’un ancien test
Hollywood/Miami intègre désormais la vérification indépendante de Miami ; son
assertion de succès reste inchangée.

**13 réponses correctives, 4 revues manuelles**, dont London Ontario → London UK
→ Waterloo → moins cher. L’appel MCP du premier tour est maintenant près de
42.987/-81.223, au lieu de 45.447/-63.558 en Nouvelle-Écosse. Mapbox renvoie
le bureau Old East Village BIA : point dans la bonne ville, pas preuve d’une
frontière exhaustive du quartier. Date, 10:30–17:00 et CAD sont conservés.
23 cartes jointes aux reçus MCP, zéro erreur de prix/expiration/jointure.
Aucune carte plafonnée : pas de nouvelle preuve sur les budgets.

Les autres parcours restent imparfaits : East London résout encore le centre
London ; Bromley est correctement envoyé au MCP mais distance_origin peut rester
ancien dans la réponse vide ; Brescia et province réduit la zone à un rayon de
ville, avec jacuzzi hôtel ne prouvant pas une baignoire privative en chambre.
Le corridor Waterloo/New Malden/Wimbledon n’est pas représenté correctement.

Export SQL rafraîchi : 33 278 lignes, 2 000 récentes. Sept nouveaux messages hors
IDs de nos campagnes ; deux sessions déjà vues prolongées et une nouvelle.
Rejeu complet de leurs contextes : 11 messages × 3 bras = **33 réponses et
9 revues manuelles**. Dix messages associés exactement aux extractions Langfuse ;
le dernier utilise un autre chemin, associé par Latest message dans la génération
du contrat géographique. Fuseau de ce dernier tour absent : champ omis et limite
signalée, sans inventer sa requête originale. Provenance organique non certifiée.

Résultats : contexte South Carolina perdu puis zone « somewhere special »
conservée ; ambiguïté Conway/Floride inutile. À NYC, la candidate répond à la FAQ
et résout la ville, mais **ignore la piscine après jacuzzi** : tours 4–6 avec
hotelEquipmentIds=[41] uniquement, profil amenities=[jacuzzi]. Paiement à la
réception et anniversaire prolongent le même résultat vide. Ce défaut est
avéré dans les reçus, pas déduit d’une simple différence d’inventaire.
Cinq cartes candidates supplémentaires vérifiées ; aucun plafond à contrôler.
Les notes A des trois bras concernent uniquement la clarification initiale
rooftop en portugais, pas une recherche réussie. Pas de taux global extrapolé.

Coût de l’étape : **0,44492 USD**, cumul **85,40179 / 110 USD**, provisions
11,10 USD incluses, réserve 10 USD. Aucun runner payant restant. Source distante
main revérifiée : cbe88b9. Rapport privé new-prod-v24-review.private.html et
geo-v24-summary.private.json. Prochain travail : état géographique typé et
multi-zone, mise à jour effective des équipements au suivi, conditions par offre,
puis couverture historique/FAQ/widget restante. Aucun merge ni déploiement.

# Audit historique et correctifs v18 — 7 octobre 2026

## 2026-10-08 — v23 : dates client et nouvelle comparaison de production

**Toujours pas de GO remplacement.** Le modèle et le résolveur partagent désormais
le jour du client. Une date fraîche doit citer le message client actuel : un
« today » inventé sans présence dans le message ne peut plus remplacer la date
portée ni provoquer un report à 2027. Cela vérifie la présence littérale de la
citation, pas toute sa sémantique. Aucun regex ni appel LLM supplémentaire.

Onze nouveaux tests : 8 échecs / 3 succès avant correction ; tests de changement
de date explicite, de maintien et de frontière UTC/Londres/Toronto. Les fixtures
antérieures déclarant une date contiennent désormais le texte client correspondant ;
les assertions de report d’année, de persistance et de fuseau restent inchangées.
**2 297 tests passés, 1 ignoré** sur la source finale ; 87 ciblés ; ruff,
mypy (60 fichiers), guardrails et diff propres.

Rejeu correctif : **15 réponses, 0,11324 USD**. Bromley/Brescia recherchent le jour
local attendu ; date explicite du 10 octobre et 10:30–17:00 conservés pendant les
changements de pays/quartier/prix. **32 cartes** jointes aux reçus MCP, zéro écart
prix/expiration/non-jointure. Pas de migration des dates déjà erronées en session.

Les sept nouvelles conversations SQL (23 messages, devises/locales/fuseaux issus
des diagnostics et extractions Langfuse) sont maintenant rejouées sur les trois
bras : **69 réponses / 21 revues manuelles**. Messages répétés associés par ordre
d’occurrence ; fichiers de réponse hashés ; critères de sélection exclus lorsque
les références historiques ne désignent plus de cartes réellement proposées.
**37 cartes tarifées** jointes aux reçus search/details, zéro écart de prix,
expiration ou carte non jointe ; une carte d’identité Libertel séparée, identité
vérifiée mais aucune disponibilité attestée. Aucune carte plafonnée : pas de
preuve supplémentaire sur les budgets frais compris.

Résultats contrastés : candidat conserve l’accès piscine à Luxembourg, confirmé
par includedAmenities des deux offres ; les trois bras échouent sur plusieurs
aspects des départements/États et des arrondissements multiples. Dans le 78,
legacy dérive vers Bordeaux/Marmande tandis que B2C/candidat bouclent sur la ville.
Paris 9/17/18 avec baignoire produit des cartes hors zone, puis des critères
redemandés bien qu’explicites. Le candidat vérifie les fiches sans garantir la
baignoire et retrouve un nom mal orthographié ; cela ne remplit pas toute la demande.

**Nouveau défaut géographique avéré** : le contrôle London Ontario / Old East
Village cherche aux coordonnées de « East Village, Nova Scotia, Canada ».
Le pays CA et le profil London ne prouvent donc pas la bonne localisation.
La réussite des contrôles d’état v22 ne vaut pas validation des coordonnées.
East London et le corridor Waterloo/Wimbledon restent aussi ouverts.
Le texte « no offers » arrondit les heures suivant la règle de matching du site
existante : traiter la formulation comme une question UX séparée, ne pas changer
cette règle produit pour faire passer un test de minutes.

Comparaison fraîche : **0,67989 USD** ; étape date + comparaison : **0,79313 USD** ;
cumul **84,95688 / 110 USD**, provisions 11,10 USD incluses, réserve 10 USD.
Aucun runner payant actif. Rapports privés date-v23-summary.private.json et
new-prod-v23-review.private.html ; données brutes hors Git. Aucun changement
Railway, merge ou déploiement. Prochain travail : représentation explicite des
zones administratives/multiples, vérification province/coordonnées, équipements
propres aux chambres, puis couverture FAQ/annulation/widget et historique restante.

## 2026-10-08 — v22 : changements de destination et maintien des horaires

**Pas de GO remplacement.** Trois conversations SQL récentes, neuf messages
associés exactement aux extractions Langfuse, ont été rejouées sur les trois bras
(27 réponses). Les neuf conversations ont une revue manuelle sourcée avec
empreinte des fichiers. Devise/locale/fuseau restaurés ; GPS/favoris exacts
manquants dans un parcours. Provenance organique non certifiée par cette API.

Le rejeu reproduit le quartier East London conservé à Bromley. Le pont vers le
 géocodeur ne recopie désormais zone/metro/pays que si la destination reste la
même. Au changement de destination, un quartier identique à l'ancien recopié par
le modèle exige sa présence dans le message client réel ; le raw_user_message du
modèle ne sert pas de preuve. Les nouvelles zones distinctes restent admises.
Le reducer invalide aussi l'ancien contexte au changement de pays d'une ville
homonyme. Aucun regex ni appel LLM ajouté.

Le contrôle London Canada → London Royaume-Uni a révélé une seconde cause : une
extraction rejetée de « mêmes horaires » supprimait les bornes. Seule une opération
`replace` explicite et citée peut désormais confier une nouvelle préférence
horaire au spécialiste. Deux attentes de tests ont été corrigées : une extraction
numérique sans preuve numérique ne vaut plus implicitement remplacement ; le cas
`replace=true` conserve sa validation de changement vers le matin.

Deux lots correctifs : **28 réponses**, dont **15 sur le dernier code**. Neuf
contrôles d'état ciblés passent : changement de pays, suppression ancien quartier,
maintien date/10:30–17:00/deviseCAD, Waterloo conservé au suivi moins cher, Bromley
sans East London (parcours réel et contrôle explicite). **30 cartes** jointes aux
reçus MCP par hôtel/formule/date/minutes, zéro écart prix/expiration/non-jointure.
Aucun plafond vérifiable parmi elles ; aucun taux global de réussite revendiqué.

**Restent bloquants** : multi-lieux Waterloo/Wimbledon ; East London ancré au
centre de Londres ; date inventée par le modèle sans demande, puis reportée à
2027 autour de minuit (TODAY serveurUTC différent du jour client) ; phrase
« no offers » arrondissant10:30 à11:00 ; synthèse confondant parfois couverture
horaire et arrivée exacte ; jacuzzi privé/inclus et couverture provinciale non
prouvés ; réponse walk-in indirecte. Les nouveaux échecs sont conservés, pas
reclassés en succès. Rejeux exposés et variabilité modèle, pas validation aveugle.

Validation : **2 286 tests passés, 1 ignoré**, 301 ciblés ; ruff, mypy60,
guardrails et diff propres. main refetch inchangé cbe88b9 ; CI190d39a réussie.
Étape comparative+correctifs : **0,4647USD**, cumul **84,1637USD** provisions incluses
(plafond110, réserve 10). Aucun merge/déploiement/changement Railway.
Rapports privés locaux geo-v22-summary.private.json et geo-v22-review.private.html ;
messages et reçus ne sont pas versionnés. Nouveau contrôle SQL :33248lignes,
2000exportées ; hors nos IDs connus,23nouveaux messages dans7sessions à vérifier
avec Langfuse avant le prochain lot (départements, arrondissements, équipements).


## 2026-10-08 — v21 : revue des 108 notes terminée, nombres et contexte corrigés

**Toujours pas de GO remplacement.** Les 108 annotations du lot historique v19
ont été revues séparément des suggestions du juge ; les 216 empreintes des
rejeux/notations ont été vérifiées. 70 notes ont changé. C'est une classification
sémantique limitée aux preuves disponibles, pas une validation exhaustive des
sources, de l'inventaire ou des 6 mois de comportement. Le lot reste sur d1eb29e.

Le triage ne crée plus un budget à partir d'un nombre seul sans contexte : une
réponse budgétaire doit citer la question précédente réelle. Les codes postaux ne
sont pas distingués des montants par un seuil arbitraire. Le modèle interprète le
rôle, le code vérifie la présence de la preuve ; cela ne certifie pas la sémantique
de toute question. Aucun regex ni appel LLM supplémentaire. Les nombres seuls
conservent la langue établie ; les contraintes de recherche restent transmises à
la synthèse même lorsque l'inventaire est vide.

**Quatre itérations, 54 réponses ; dernière version 17 réponses.** Le premier
correctif rejetait aussi une réponse budgétaire valide faute de citation par le
modèle. Ce défaut a été conservé dans les rapports, puis corrigé avec un rappel
ciblé dans le même appel de triage. Dernier lot : 6 contrôles d'état ciblés passent
(codes postaux sans budget, précision ville/État/pays, montant USD, deux plafonds
JPY successifs avec langue stable). **20 cartes** jointes aux reçus MCP par
hôtel/formule/date/minute : zéro écart de prix, expiration ou carte non jointe.
Aucune carte avec plafond vérifiable dans ce lot : ne pas en déduire une preuve
supplémentaire sur les budgets frais compris.

**Défauts encore présents** : une synthèse traite parfois un nombre non validé
comme un plafond ; des clarifications ville/devise tournent en boucle. Géographie
pays/comté/POI, preuves par borne horaire, accès aux équipements, FAQ et widget
restent à valider/corriger. Aucun taux global ni supériorité sur prod démontré.

Comparatif de triage isolé : 12 cas × 2 tirages × 2 modèles. Rôle des nombres :
4o-mini 24/24, 4.1-mini 23/24. Le prompt de ce test précède le dernier rappel
numérique ; le test ne mesure ni le prompt final ni le parcours complet. Le rejeu
complet a précisément révélé un défaut absent du test isolé. Aucune configuration
Railway changée et aucun changement de modèle préconisé sur cette seule preuve.

Nouveau contrôle SQL : 33 216 lignes, 2 000 dernières exportées. Les 9 nouvelles
lignes forment 3 sessions hors identifiants de nos rejeux connus ; l'API n'expose
pas is_synthetic, donc provenance organique non certifiée. 9/9 messages associés
exactement aux extractions Langfuse. Devises/locales attestées dans les diagnostics,
fuseaux appareil retrouvés. Entrées préparées pour Waterloo/Wimbledon,
Brescia/province et East London/Bromley, **pas encore rejouées**. GPS/favoris présents
dans une session mais valeurs exactes non retrouvées : aucune donnée inventée.

Validation code final : **2 276 tests passés, 1 ignoré** ; 206 tests ciblés ;
ruff, mypy (60 fichiers), guardrails et diff propres. Deux anciens tests traitaient
un nombre initial comme budget sans contexte : leurs scénarios ont été précisés
(question budgétaire préalable ou devise explicite), sans retirer les assertions
sur le caractère explicite et l'absence d'élargissement du plafond. Les nouveaux
tests ont échoué avant correction (8 échecs, 5 succès).

CI92dd1d5 précédente réussie (étapes live ignorées). Main re-fetché, toujours cbe88b9.
Coût de cette étape **0,3037 USD**, dont 0,0202 de comparatif modèles ; cumul
**83,6990/110 USD**, dont 11,10 de provisions, réserve 10. Aucun runner payant actif.
Données, conversations et rapports détaillés privés hors Git. PR134 reste brouillon,
sans merge ni déploiement. Suite : reprendre les nouveaux parcours géographiques
avec leur contexte attesté, puis contrôles horaires, FAQ/annulation informative et
widget ; préserver les échecs et rejouer après chaque correction.


**Pas de GO remplacement production.** Le VPN fonctionne et les comparaisons live
ont repris. Des gains ciblés sont établis, mais plusieurs défauts importants
restent ouverts. Aucun merge, déploiement ou changement des modèles Railway.

## 2026-10-08 — v20 : créneau conservé entre les tours, rejeux correctifs terminés

**Toujours pas de GO remplacement.** Le concierge conserve maintenant les bornes
horaires validées dans un champ persistant distinct des déclarations de la feuille.
La feuille ne peut ni le réécrire ni le supprimer, y compris via une opération
`clear`. Le même champ contrôle les arguments horaires MCP et le profil après
une recherche ou une interruption FAQ. Aucun nouveau regex ni appel LLM ajouté.

Les changements explicites restent possibles : retrait du filtre, nouvelle durée,
ou préférence non numérique interprétée par la feuille. Quand le triage transforme
« le matin » en heures sans preuve numérique, les heures sont rejetées et la
nouvelle préférence est déléguée, plutôt que de conserver l'ancien soir. Les heures
marquées explicites uniquement par une ancienne feuille ne sont pas promues en
preuve du concierge. La règle produit d'arrondi des offres reste inchangée.

Trois lots correctifs : **33 réponses au total, coût 0,2620 USD**. Premier lot :
Manhattan garde 18:30–21 après précision géographique ; Philadelphia garde 09:30
après « moins cher ». Il révèle une durée d'une heure omise par le triage. Deuxième
lot : durée corrigée, mais changement au matin ignoré après rejet de 6–12 inventé.
Après correction de ce chemin, dernier lot **2 parcours / 9 tours : tous les 9
contrôles d'état horaire passent**, avec mode overlap pour matin et aucun filtre
horaire après retrait. **26 cartes** jointes par hôtel/formule/date/minute au MCP,
0 écart de prix/expiration/non jointe. Aucun budget plafonné testé dans ce lot.
Les 33 réponses ne sont pas toutes issues du code final ; chaque version est figée.

La qualité conversationnelle n'est pas entièrement corrigée : la synthèse redemande
parfois une durée/fenêtre connue. Le cas combinant matin + heure de départ nécessite
encore un meilleur contrôle de preuve par borne. Ces résultats ne prouvent ni le
rappel de l'inventaire, ni une supériorité globale, ni la stabilité du modèle.

Validation code final : **2 261 tests passés, 1 ignoré** ; 191 tests ciblés,
ruff, mypy (60 fichiers), guardrails et diff propres. Les tests ont reproduit les
pertes de minutes avant correction. La nouvelle CI reste à vérifier après push.

Revue manuelle historique : **57/108 annotations**, dont les 36 du candidat ;
51 restent à revoir côté legacy/B2C. Notes originales conservées séparément.
Contrôle récent SQL : 33 207 lignes incluant nos tests, 2 000 dernières exportées ; ce chiffre ne compte pas des conversations organiques distinctes.
Coût cumulé comptabilisé **83,3954/110 USD**, dont 11,10 de provisions ; réserve 10.
Aucun runner payant actif à ce checkpoint. Traces et messages bruts hors Git.

Suite : compléter les 51 revues ; corriger les rôles des nombres, la granularité
et le suivi géographiques, le grounding horaire restant et les répétitions ;
challenger les modèles par composant sur ces défauts ; compléter les rejeux avec
contexte natif retrouvé/dates futures, FAQ/annulation informative et widget.
PR134 reste brouillon, sans merge, déploiement ni modification Railway.

## 2026-10-07 — validation historique v19 collectée, revue des notes incomplète

**Pas de GO.** La version runtime `d1eb29e` est restée identique pendant les
36 conversations historiques réservées : **104 messages originaux par bras,
312 réponses** legacy production / B2C déployé / candidat. Inventaire MCP frais,
aucune action de réservation ou annulation. Le lot coûte **3,1526 USD**.

Les 47 cartes du candidat sont jointes aux reçus MCP par hôtel, UUID de formule,
date et créneau à la minute : **0 écart de prix, 0 offre expirée, 0 non jointe**.
Seulement 3 cartes ont un budget total vérifiable ; toutes respectent ce plafond,
frais de réservation inclus. Cela ne prouve ni le rappel ni les droits d'accès
aux équipements. Les heures/dates historiques rejouées aujourd'hui limitent la
comparaison de disponibilité, particulièrement après fermeture des créneaux.

Langfuse historique retrouvé pour 23 sessions ; 22 couvrent les messages SQL
via leurs appels d'extraction, une n'est attestée que partiellement. Une trace
supplémentaire répète le premier message d'une session, sans message client
manquant identifié. Un fuseau de l'appareil apparaît dans 22 sessions, absent
de l'export SQL ; il n'a pas été ajouté rétroactivement aux entrées figées.

**108 notes assistées reçues, mais pas de taux de réussite utilisable.** Le juge
commet notamment des faux A (pays explicite ignoré), des reproches fondés sur un
budget fourni plus tard et des erreurs de containment horaire. 14 annotations
ont été revues manuellement, avec corrections séparées et notes originales
conservées. La revue complète doit précéder toute affirmation de supériorité.
Notation : A parfait / B mineur / C significatif / D majeur / F critique.

Défauts observés à traiter : rôle des nombres (code postal devenu budget),
matin transformé en minuit, minutes perdues au tour suivant une clarification
géographique, pays/homonymes et comté confondu avec quartier, critères d'accès
ascenseur/baignoire mal interprétés. Le contrôle du delta v19 protège seulement
les minutes du message courant, pas encore celles des tours antérieurs.

Coût notation **1,3107 USD** ; cumul comptabilisé **83,1334 USD / 110 USD**, dont
11,10 USD de provisions, réserve 10 USD. Aucun runner payant actif à ce point.
Code inchangé : **2 232 tests passés, 1 ignoré**, CI37687522548 réussie, étapes
live ignorées par configuration. Les fichiers privés restent hors Git.

Suite : terminer la revue des 108 parcours notés, corriger les causes sans
nouveau regex, comparer les modèles étape par étape, rejouer les défauts avec
contexte natif retrouvé et dates futures dans un lot distinct. Les 36 sessions
sont désormais exposées : leurs rejeux futurs ne sont plus un holdout inédit.
FAQ/annulation informative, widget et preuve complète des correctifs restent
à terminer. Ni merge, ni déploiement, ni changement Railway.

> Les sections suivantes sont des checkpoints historiques ; le dernier état ci-dessus prévaut.

## Rejeu adaptatif terminé et corrections v19

9 objectifs synthétiques historiques × 3 agents = **135 réponses**, coût
supplémentaire **2,0701 USD**. Exclusions manuelles des objectifs non respectés
par le client simulé ; pas de moyenne de succès. Les annotations A/B/C/D/F sont
limitées aux critères réellement exercés. Pescara reste sur l'Adriatique dans
le préfixe candidat ; legacy dérive vers Vérone et B2C vers Pérouse. Heathrow
est résolu côté candidat alors que B2C redemande Londres sur cinq tours.
Ces gains ne compensent pas les autres parcours majeurs en échec.

Le code v19 transmet maintenant à la synthèse les **créneaux et la date de la
carte**, recherche avant de sélectionner « le moins cher » lorsque les heures
changent, complète les bornes explicitement demandées et protège les minutes
du tour contre un delta feuille arrondi. Aucun regex/appel LLM supplémentaire.
**2 232 tests passés, 1 ignoré**, ruff/mypy/guardrails verts. Un test préexistant
avait détecté un report abusif d'horaire implicite : corrigé dans le code,
assertion conservée.

Rejeu `live-followup-v19` : **5 parcours / 15 réponses**, candidat seul, inventaire
frais. Brooklyn cite la formule11–15:30 et conserve15:30 au tour suivant ; Orlando
recherche11–16 avant le choix. **9 cartes sous plafond frais inclus,0dépassement,
0non vérifiée**. Audit brut général :25cartes de recherche jointes,0écart de prix,
0expiration ;6cartes de détails non jointes par cet audit limité aux recherches.
Ces contrôles ne prouvent pas le rappel ou l'ensemble des conversations.

Défauts encore constatés dans cette version : questions de quartier après
indifférence (Orlando), début10h ajouté sans demande (SanDiego), échec Birmingham,
quote at11am modifiée par le modèle et rejetée ; la variante avec espace conserve
11–17 mais échoue aussi sur la recherche. La note du dernier parcours est B
pour Brooklyn, C pour Orlando/SanDiego, D pour les deux variantes cinéma.
Pas de score global ni de GO. Les montants en lettres, FAQ/conditions exactes,
adults-only/bains privés/spa inclus, exhausted-list et validation36 restent
incomplets. Coût cumulé **78,6701 USD**, dont11,10 de provisions, plafond110.

## Mise à jour v17 : total avec frais et limites conversationnelles

Les mentions « sous plafond » ci-dessous dans v15 décrivent le **prix affiché**.
L'audit indépendant ultérieur du lot `live-budget-answers-v15` trouve une offre
Arlington45USD +6USD de booking fees, soit51USD pour un plafond50USD.
`live-context-v16` confirme4cartes en dépassement frais inclus. Ces lots ne sont
pas une preuve de respect des budgets totaux, malgré leurs prix affichés valides.

Le correctif local v17 vérifie `*WithBookingFees` sur la même offre ; pas de
repli sur un prix hors frais manquants. `live-context-v17`,9séquences27tours,
présente18cartes plafonnées toutes vérifiées par hôtel/UUID/date/créneau :
**0dépassement frais inclus,0non vérifiée**. Aucun appel ni regex ajouté.
2 226 tests passent,1ignoré. Ces corrections sont incluses dans le checkpoint v19 de PR134.

La synthèse ne doit plus prendre une carte pour tout l'inventaire, une distance
au POI pour une distance au centre ou une grosse remise pour le prix le plus bas.
La FAQ utilise désormais payment pour les cartes cadeaux. Reste un défaut
significatif : malgré ce meilleur contexte,4o-mini extrapole les règles Dayuse
aux cartes cadeaux propres aux hôtels. Les articles eux-mêmes divergent sur
les pays éligibles (France seule versus5pays) : pas de règle universelle établie.

Le lot adaptatif historique v17 est en cours. Premiers résultats : Pescara
reste sur l'Adriatique côté candidat, mais des demandes de nouveaux créneaux avec
« cheapest » sont détournées vers details ; la synthèse n'a pas les horaires des
cartes et demande des dates déjà connues. Des disponibilités sont mal triées en
booking. Les montants en lettres ne sont pas conservés. Ce sont des défauts
bloquants pour le remplacement. Certains clients simulés changent leur objectif :
ces segments sont exclus de la notation des exigences concernées, sans effacer
les traces ni les coûts. Aucun taux de succès global n'est calculé à ce stade.

## Correction du protocole de devise — candidat v15 rejoué

La revue du code effectivement déployé (`a08a7792`) et du champ historique
`detected_market` a révélé une omission du banc : les 14 séquences fraîches
précédentes ne transmettaient pas la devise enregistrée. **Les lots v3 à v6 ne
prouvent donc pas une parité avec le contexte natif du widget.** Ils restent des
diagnostics avec contexte de devise retiré ; leurs coûts et contre-exemples sont
conservés. Les constats ci-dessous décrivent les entrées de ces lots, pas tous les
parcours de production.

Le nouveau lot `fresh-native-v15` compare les trois bras. Pour 11 séquences / 32
tours, une devise explicite est attestée dans les diagnostics URL historiques et
restaurée. Pour 3 séquences / 12 tours (Arlington, San Diego, Paris tardif), seule
la devise du marché résolu est attestée : elle **n'est pas transformée en choix
explicite**. Le domaine et la locale initiaux sont conservés ; ces cas restent
limités par l'absence de la requête widget brute. Le legacy peut remplacer un
faible défaut USD par la devise du pays de l'hôtel, contrairement à un choix
explicite. Cette distinction est nécessaire pour interpréter les résultats.

Le candidat v15 ajoute un budget montant/devise/unité, persistant et validé sur
une citation du message courant. La devise native fournit l'unité d'un montant
nu sans changer le mode d'affichage du nouveau B2C. Le filtre MCP en EUR est
réservé aux budgets EUR ; les autres unités sont vérifiées sur le prix de la
même offre. Aucune conversion de change inventée, aucun appel LLM ni regex ajouté.
Une réponse composée uniquement d'une devise peut compléter un budget en attente.
Les limites de rappel sur la page récupérée et les suppléments restent explicites.

**Limite supplémentaire vérifiée pendant le lot :** le cache MCP journalier peut
contenir des offres dont la limite de réservation est passée. Une lecture directe
sans cache le 7 octobre à 20:00 UTC à Arlington a renvoyé des offres différentes.
Les résultats de `fresh-native-v15` restent donc des diagnostics de contraintes
sur instantanés ; ils ne valident pas la disponibilité actuelle. Le contrôle
suivant utilise un transport MCP lecture seule sans cache d'inventaire ni décalage
de date. Les anciennes sorties restent conservées et facturées.

Validation locale v15 : **2 224 tests passés, 1 ignoré**. Ruff, mypy et guardrails
passent. La comparaison live et le rejeu des réponses courtes sont terminés ;
aucun succès global n'est déduit des tests locaux. Les résultats v11/v12/v13 sont
des diagnostics intermédiaires, pas des résultats rétroactifs du candidat v15.

## Résultats v15 avec inventaire frais

`live-native-v15` : **14 séquences / 132 réponses**, trois bras terminés avec
sessions séparées. MCP candidat sans cache d'inventaire ni décalage de date,
Mapbox en cache statique. **27 cartes** jointes par hôtel + UUID de formule +
date à la réponse MCP brute : aucun écart de prix, aucune limite de réservation
passée à l'heure de la réponse. **12 cartes avec plafond vérifiable**, toutes
sous ce plafond dans la bonne unité ; aucun filtre MCP EUR pour ces budgets
étrangers. Ces contrôles ne mesurent ni le rappel de l'inventaire ni les
suppléments facultatifs ni la qualité complète d'une conversation.

`live-budget-answers-v15` : **2 parcours adaptés / 7 tours**, sans cache également.
« USD » et « US dollars » complètent bien les plafonds50/60, conservés ensuite.
La fenêtre09h–17h et la borne de départ20h persistent. Arlington trouve une offre
affichée sous50USD mais à51USD frais inclus, puis aucune offre vérifiable sur09h–17h ; San Diego ne trouve pas de
formule vérifiable sous60USD. Le contrôle du prix affiché seul était insuffisant pour ce lot. Sa phrase « only one matches » reste trop générale pour une page de
résultats : ne pas la considérer comme une preuve d'exhaustivité.

Les traces fraîches déployées montrent priceRangeMax100EUR pour le clientUSD100.
Le candidat le corrige. Les défauts sémantiques établis restent **C** sur les
segments concernés : Orlando redemande la zone après indifférence ; Paris perd
la clarification22h ; carte cadeau est classée ack et reçoit un accueil ;
Ripley confond le filtre d'occupation2adultes avec une demande adults-only sans
vérification de politique. **Les autres cas partiels ne deviennent pas A/B.**
Brooklyn/Davenport nécessitent des réponses adaptées aux clarifications ; trois
séquences restent limitées par la devise native non explicitement attestée.

Pescara est vérifiée sur la côte adriatique (42.47194,14.206623), Tours conserve
starRatings5, Rome/Milan conservent leurs équipements. Les résultats vides du MCP
frais en fin de journée ne prouvent pas une régression face à l'export legacy.
L'absence de fuseau natif à Singapour empêche un verdict de disponibilité.
La normalisation des montants écrits en lettres reste une limite à évaluer :
le nouveau validateur exige actuellement une représentation numérique citée.

Coût après ces deux lots : **75.5730USD engagés**, **64.4730USD observés** et
**11.10USD de provisions**, aucun lot modèle pending. La provisionCI existante
est réutilisée pour le prochain push ; les étapes live du précédent run avaient
été ignorées par leurs gardes de configuration. Aucun changement de modèle.

## Données et fiabilité de la mesure

- Export frais via l’API SQL en lecture : **32 822 tours / 13 340 sessions**, du
  20 février au 7 octobre. Ce n’est pas un backup SQL complet.
- Échantillon figé avant lecture : 72 conversations de développement et **36 de
  validation encore non lues**. Filtres de longueur, identifiant et domaine ; ils
  ne prouvent pas que chaque session est organique. Échantillon mensuel équilibré,
  pas pondéré par le trafic ; pas de session d’avril éligible.
- Langfuse historique : 48/72 sessions avec traces, 24 sans. Une session possède
  un tour de destination dans Langfuse absent de l’export ; elle est écartée du
  rejeu exact. Des nombres égaux de tours ne prouvent pas un contexte complet.
- Grille A/B/C/D/F historique conservée. Les juges économiques et GPT-4.1 ont été
  calibrés, mais la revue des A/B a encore trouvé un changement de pays répété,
  un prix horaire traité comme total et des affirmations de services/politique
  insuffisamment étayées. **Les distributions automatiques sont retirées du
  verdict qualité**. Les corrections manuelles et sorties originales restent
  conservées ; aucun taux global de réussite validé n’est annoncé.

## Comparaison fraîche

14 séquences réelles de développement, 44 messages chacune des trois versions :
**132 réponses** legacy production / B2C déployé / candidat v18-v3, toutes terminées
et revues qualitativement (texte, cartes et profil ; traces ciblées pour les causes).
Ce lot a été choisi pour diagnostiquer des défauts ; ce n’est pas un échantillon
aléatoire de satisfaction. Il complète les 41 séquences et 24 objectifs de v17,
sans leur attribuer rétrospectivement le code v18.

Les sessions/cookies sont indépendants. Les deux déployés sont appelés par leur
vrai endpoint ; le candidat utilise la configuration de modèles Railway et des
services locaux isolés, avec cache MCP/Mapbox par arguments exacts. Date courante
par cas, contexte natif manquant signalé. Legacy export/Qdrant et MCP préprod
(reflet exact de la prod selon Victor) ont des chemins et fraîcheurs différents.
Une différence d’hôtel ou un résultat vide ne suffit pas à conclure à un défaut.

Douze traces fraîches ciblées ont été lues (Arlington legacy, Orlando et Londres
B2C), sans ERROR/WARNING observé : les défauts décrits ci-dessous sont sémantiques,
pas expliqués par une panne MCP. Les anciens 429/quota et 400/extract_claims sont
consignés comme incidents historiques distincts.

| Parcours | Constat de la comparaison fraîche |
|---|---|
| Arlington Texas → budget → 9h–17h | Legacy change vers Virginie/DC après « Arlington ». Candidat conserve Texas et les heures ; devise encore à traiter. |
| Orlando, 100 USD, quartier indifférent | Les nouveaux agents traitent USD100 comme EUR100. B2C déployé et candidat v3 répondent par un accueil générique à l’indifférence. |
| San Diego, budget contextuel, jusqu’à 20h | Legacy conserve60 ; candidat v3 annonce le montant sans le persister. Les réponses suivantes dépassent le budget. |
| Jacuzzi puis Londres ; spa puis Rome | Candidat conserve mieux l’équipement après clarification ; le déployé le perd. Une installation d’hôtel ne prouve pas un accès inclus ou privé. |
| Pescara | Les deux nouveaux agents choisissent un hameau près de Pérouse. Mapbox avait bien renvoyé la ville adriatique ; le classement par inventaire la remplaçait. |
| Ripley MS, baignoire, adultes seulement | Ville/État mal extraits ; une clarification géo peut être remplacée par une fausse panne. Deux occupants adultes ne prouvent pas un hôtel réservé aux adultes. |
| Cinq étoiles → Tours | Déployé propose trois étoiles sans réserve ; candidat conserve le filtre et retourne vide. |
| Milan → spa → jacuzzi | Candidat poursuit la recherche ; déployé redemande la ville. Vérification de l’accès privé/inclus toujours nécessaire. |
| Cinéma sans ville ; Davenport ambigu | Une clarification nécessaire n’est pas un échec. Ne pas récompenser une destination inventée. |
| Brooklyn → « le premier » | Après clarification non répondue, aucune liste n’existe : sélection non comparable. Rejeu adaptatif nécessaire. |
| Paris « ferme vers22h » | Il faut distinguer réception, arrivée et départ. Réponse Paris ne résout pas cette ambiguïté ; la question initiale se perd. |
| Carte cadeau puis Singapour | Politique legacy à vérifier ; manque de fuseau natif et date locale déjà au lendemain empêchent un verdict de disponibilité. |

## Changements du candidat

- Géo : destination demandée prioritaire sur GPS ; pays vérifié prioritaire sur
  locale ; ville résolue indépendamment ; identité IATA/terminal contrôlée ; repli
  administratif borné pour un quartier après échec SearchBox, avec pays/nom/distance
  vérifiés. Aucun nom de ville ajouté à une liste d’exceptions.
- Triage existant : fenêtre horaire optionnelle avec citation du message courant,
  persistée avant la feuille. Un après-midi vague n’est pas une preuve de 12h.
- Relances : dernière réponse du concierge bornée transmise comme contexte non
  fiable au triage uniquement. La feuille ne reçoit pas les suggestions de l’agent
  comme nouvelle source de préférences. Pas de nouvel appel LLM, pas de regex ajouté,
  pas de données de politique ni de consentement déduites de cette réponse.
- Fiches collectives : identifiants de la sélection, dédupliqués, maximum 5 ; même
  date et même formule quand connues. Prix et horaires de la même offre ; si la
  formule a disparu, pas de remplacement silencieux par un prix différent.
- MCP timeSlotMode choisi par code : contain pour heures, overlap pour daypart,
  retiré sans fenêtre. Évite l’envoi de l’enum invalide start_only.
- Diagnostic géo : un DataPart de télémétrie conserve le texte de la feuille pour
  l’invocation courante ; aucun ancien tour, résultat outil ou raisonnement repris.
- Homonymes : une municipalité exacte mieux classée par Mapbox ne doit pas être
  remplacée par une subdivision du même pays au seul motif de l’inventaire. Une
  subdivision mieux classée reste candidate (contre-exemple Brooklyn NY).

Concierge propriétaire de l’état, feuilles stateless A2A, LiteLLM conservé.

## Rejeux des corrections et limites

Les variantes sont figées et identifiées par empreintes. Les erreurs intermédiaires
restent dans les artefacts et dans les coûts.

- Pilotes JFK : conservation11h–16h et lecture collective des fiches. Le premier
  pilote avait exposé une formule125 USD remplacée par156 USD ; le rejeu d’une vraie
  réponse MCP vérifie maintenant la conservation125 USD (preuve adaptateur, pas à
  elle seule validation du parcours complet).
- Triage sur24 diagnostics : objet horaire atomique, 4o-mini 10/12, 4.1-mini 12/12.
  Pilote conversationnel à cinq cas encore mixte : **aucun remplacement global
  de modèle justifié**. Le précédent essai search 5.2 coûtait environ 4,8× sans gain
  global établi.
- Candidat v4 : 14 séquences / 44 tours terminés. L’indifférence poursuit Orlando,
  budget contextuel 60 persiste à San Diego ; devises et questions répétées restent
  incorrectes. Pescara résout la bonne ville mais retourne vide à la date courante.
- Ce rejeu révèle une régression de la préférence municipale : Brooklyn NY est
  écarté pour Maryland. Test négatif ajouté et règle resserrée pour conserver les
  subdivisions mieux classées. **Les tests locaux seuls n’avaient pas détecté ce
  défaut** (2 197 passaient avant l’ajout du contre-exemple).
- Candidat v5 : 14 séquences / 44 tours terminés, 2 198 tests locaux passent.
  Brooklyn redevient une clarification ; le texte de l’assistant transmis à la
  feuille a cependant contaminé une recherche Arlington avec « downtown », jamais
  demandé par le client. Cette transmission est retirée : la réponse précédente
  sert uniquement au triage.
- Candidat v6 : 14 séquences / 44 tours terminés et revus. Pescara résout la bonne
  ville ; Brooklyn reste une clarification. Orlando poursuit la recherche après
  indifférence mais redemande un quartier ; les devises restent incorrectes. Tours
  redemande inutilement un quartier ; Rome peut traiter spa comme un lieu. Ces
  variations empêchent tout gain global affirmé. Huit séquences ont un défaut
  significatif constaté (C) ; six restent partiellement/non évaluables, **pas A/B**.
- Ce lot expose aussi children=0 rejeté par MCP. Adaptateur corrigé pour omettre
  zéro sur le fil et conserver le retrait dans le profil. La déclaration virtuelle
  autorise ce retrait au modèle sans modifier le schéma du serveur.
- Candidat v8 final de ce checkpoint : Arlington réel (5 tours) et retrait d’un
  enfant synthétique (3 tours), tous terminés, aucun rejet MCP. Profil enfants
  1 → 0 → 0 ; appels MCP enfants1 → absent → absent ; date et fenêtre10h–17h
  conservées. Ce dernier parcours conserve une autre faiblesse : budget100EUR
  supposé au raffinement « moins cher ». **Seul le retrait d’occupant est validé**.
  Le lot complet à14 conversations est v6, pas rétroactivement v8.
- Validation du code v8 : **2 201 tests passent, 1 ignoré**, ruff, mypy, guardrails
  et diff-check verts localement (Python3.13 ; CI utilise3.12). Le contrôle de
  duplication exacte entre72 développement et36 validation trouve0 recoupement,
  sans lecture humaine des conversations de validation ; quasi-doublons non exclus.

## Travail encore nécessaire

1. Revue de la PR brouillon : correctifs ciblés, pas une autorisation de bascule.
2. Étendre la validation du budget typé livré en v15 : montants écrits en lettres,
   autres devises, portée du rappel et formulation non exhaustive des résultats.
3. Lever les pertes restantes de ville explicite, les relances redondantes, les
   fenêtres ambiguës et les affirmations adultes-only / accès spa privé ou inclus.
4. Repasser suites historiques, FAQ/annulations informatives et objectifs adaptatifs
   avec référents valides. Les neuf nouveaux objectifs synthétiques de
   `datasets/b2c-history-v18-regressions.json` sont des spécifications non encore
   exécutées comme fichier adaptatif ; pas des conversations organiques.
5. Candidat figé puis 36 sessions de validation tenues à l’écart, matrice de
   préservation complète, widget/See-all/expiration/âge et revue équipe. Le code ne
   permet pas encore d’affirmer que tous les six mois de correctifs sont préservés.

Artefacts privés : campagne `production_parity_v18` du workspace legacy, manifests,
entrées/sorties, outils, traces, factures et adjudications. Aucune donnée client ou
clé dans Git. Ledger commun v17, plafond 110 USD et réserve d’arrêt 10 USD. Les timeouts
et pilotes invalides restent facturés/provisionnés. Coût au checkpoint v8 (historique, remplacé par le coût v15 plus haut) :
**70.4099 USD**, dont **9.10 USD de provisions** et **61.3099 USD
observés**. Les provisions incluent 2 USD pour la CI de cette mise à jour ; cette
somme n’est pas une consommation observée. Aucun lot modèle pending à ce checkpoint.
Aucun GO ni déploiement implicite.


## 2026-10-08 — v28 : frontières, créneaux et demandes de lien

**Pas de GO remplacement ; aucun changement de modèle par défaut.**
124 réponses / 39 revues manuelles A/B/C/D/F sur plusieurs versions :
20 premières corrections, 21 réponses comparant deux nouvelles conversations
sur ancien prod / B2C / candidat, 42 réponses comparant uniquement les modèles
de triage, puis 41 réponses correctives. **Neuf réponses sur la source finale.**
Cas exposés, aucune statistique de population ni validation globale du nouvel agent.

Corrections sans nouvelle regex ni appel LLM supplémentaire :
- Une ville simple garde la recherche habituelle ; une limite municipale explicite
  déclenche la vérification d’appartenance. Province → ville et répétition du pays
  sont distinguées. Une restriction parmi des zones connues conserve leur type.
- Une zone recopiée sans preuve dans le message courant ne supprime plus le périmètre.
  Le libellé fournisseur « provincia di Brescia » reste lié à l’identité Brescia.
  Le dernier rejeu conserve enfin la province aux deux suivis, avec triage 4.1-mini.
- La synthèse reçoit une preuve de couverture à la minute :10–18 couvre 10 h 30–17 h.
  Aucun assemblage d’offres, aucune modification du filtre horaire arrondi du site.
- Le triage distingue URL de fiche hôtel et passage au checkout. Le rejeu réel
  fournit le lien vérifié sans confirmation de réservation ; « booked out » reste
  une recherche d’alternative, sans dérive vers FAQ/annulation.

**2 389 tests passés, un ignoré**, ruff, mypy (63 fichiers) et guardrails verts : 19 nouveaux
cas depuis v27, plusieurs erreurs reproduites en rouge avant correction. Les
contrôles couvrent aussi les libellés fournisseur et les raffinements de quartier.

Le challenge à code identique comprend 21 appels de triage par modèle. 4.1-mini
extrait mieux les provinces sur ces cas ; les défauts de suivi dans le code
l’affectaient aussi. Ce petit lot ne justifie pas un changement global de modèle.

**Échecs conservés :** 4o-mini traite encore des provinces comme des villes.
Les coordonnées confirment deux hôtels hors province de Bergamo aux T1/T2 : D,
pas une absence de preuve. Les trois réponses anciennes concernées restent D.
North Brisbane retourne des hôtels du CBD ; corridor Waterloo non résolu. Des appels
outils malformés épuisent le quota puis sont présentés comme une indisponibilité.
La synthèse confond parfois suppression du filtre jacuzzi et exclusion des hôtels
avec jacuzzi. Pagination/exhaustivité, accès privatif/inclus, âge/conditions FAQ,
occupation, widget et matrice historique restent ouverts.

Deux nouvelles sessions SQL, sept tours retrouvés dans Langfuse, contexte attesté
rejoué sans inventer de payload natif. Export 33 312 lignes/2 000 récentes ; même
provenance organique non certifiée. Les inventaires export et MCP diffèrent ;
les écarts de liste ne sont pas automatiquement des erreurs de modèle.

Audit : **219 cartes / 98 plafonds frais compris**, zéro écart de prix/jointure/expiration ; source finale **18 cartes / 15 plafonds**. Huit appartenances géographiques vérifiées sur source finale, zéro écart de portée pour ces deux parcours. Cela ne valide pas les autres familles.

Étape **1.19263 USD** ; cumul **88.12138/110 USD**, provisions 11,10 incluses, réserve 10. Aucun runner payant actif ; triage41 arrêté après mesure. Aucun merge/déploiement/écriture Railway. Rapports privés v28-summary/v28-review, reçus et messages hors Git.

## 2026-10-08 — v29 : préparer la géographie et dater les offres nommées

**Pas de GO remplacement.** Deux corrections sans nouvelle regex, appel modèle
supplémentaire ni augmentation du quota d’outils :

- Le concierge a déjà identifié les périmètres du tour : la feuille les résout
  avant son premier appel modèle. Cette préparation ne s’applique pas au seul
  profil hérité, qui pourrait précéder un changement de destination. Le géocodage
  fournit les coordonnées vérifiées et le même traitement borné recherche chaque
  zone. Les appels redondants réutilisent le plan ; un échec interdit les coordonnées
  inventées. Feuille toujours stateless, profil entrant/sortant A2A, LiteLLM conservé.
- Une réponse hôtel nommé contenant une offre datée dispose désormais du contexte
  de date pour la synthèse, même sans l’enveloppe `search_date` de la feuille.
  Une carte d’identité ne prouve pas une disponibilité ; plusieurs dates ne sont
  pas réduites à un seul jour. Le dernier rejeu annonce le 8 octobre après une
  recherche du 7 octobre, au lieu de masquer la date de l’offre Royal Sonesta.

Précision sur l’échec précédent décrit comme « appels mal formés » : les reçus
v28d montrent surtout deux recherches **avant géocodage**, consommant le quota
avant la recherche correctement ancrée. Sur v29, le premier tour devient un appel
modèle search_offers suivi de deux requêtes MCP en code, sans épuisement du quota.
Les deux contrôles de cinq suivis conservent date, minutes, 150 EUR, retrait jacuzzi,
restriction au 92 puis Lyon. Les formulations restent perfectibles (notes B).

**40 réponses / 13 revues manuelles A/B/C/D/F**, dont 15 réponses sur deux nouvelles
sessions comparées ancien prod/B2C/candidat. Trois réponses utilisent la source
finale ; huit autres utilisent la même logique avant une garde de type redondante.
**69 cartes / 35 plafonds** vérifiés contre reçus MCP : zéro écart prix/jointure/
expiration. Les quatre cartes hors province Bergamo restent des échecs géographiques.

**2 395 tests passés, un ignoré**, puis tests ciblés après correction du typage,
ruff, mypy (63 fichiers) et guardrails. Six nouveaux cas couvrent plan autoritaire, absence
ou échec de plan, date d’offre nommée, identité sans disponibilité et dates mixtes.
CI du commit à observer séparément ; aucun statut live déduit des jobs ignorés.

Export SQL actualisé : 33 324 lignes / 2 000 récentes. Deux sessions, cinq messages
retrouvés dans Langfuse. Les deux ont un GPS natif signalé, mais son payload exact
manque : comparaison texte/contexte attesté seulement, sans note de personnalisation.
L’ordre réel est âge 19 puis « Show Brooklyn », et romantique → Houston → hôtel nommé.
Ne pas le reconstruire d’après une narration plus plausible. Provenance organique
non certifiée par l’API SQL ; aucune donnée native inventée.

Échecs maintenus : le candidat répète Brooklyn NY/Maryland ; B2C déployé oublie
l’âge au suivi. Le romantique reste peu étayé. 4o-mini peut toujours confondre
province et ville, et cite « même date » comme fausse preuve de frontière pour
Verona. North Brisbane/East London, corridors, équipements privatifs/inclus, FAQ,
occupation, exhaustivité et widget/devise ne sont pas validés par cette étape.

Inventaire historique étendu : **256 commits**, 134 chemins de tests modifiés,
**2 088 tests nommés présents**, un fichier absent au commit prod. Ce catalogue
privé de métadonnées n’est ni 256 bugs distincts ni une preuve de portage. Les
32 familles restent prioritaires et non exhaustives ; le lien assertion→rejeu
reste à compléter. Aucun modèle par défaut modifié.

Étape **0.35549 USD** ; cumul **88.47687/110 USD**, provisions 11,10 incluses, réserve 10. Aucun runner payant actif. Rapports privés v29-summary/v29-review et historical-fix-inventory-v29. Aucun merge, déploiement ou écriture Railway.
