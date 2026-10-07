# Audit prod / AgentB2C — 7 octobre 2026

**Décision : correctif ciblé à revoir, pas de GO de lancement ni de preuve que le
nouvel agent surpasse globalement la production.** Les répétitions conservent des
échecs de géographie, de créneau et de suivi. Le jeu synthétique et le protocole
sont dans [REAL_USER_JOURNEYS.md](REAL_USER_JOURNEYS.md). Les conversations et traces
privées restent hors Git.

## Configuration réellement comparée

| Bras | Source / déploiement | Modèles | Recherche |
|---|---|---|---|
| Production historique | `a08a7792ed95dedca6255b5c588a80a504dd6249`, SHA Railway vérifié | GPT-5.2, confirmé dans Langfuse | Export / Qdrant, `ai.dayuse.com/v3/chat` |
| B2C déployé | release `cbe88b9`, image sans métadonnée Git SHA ; digests archivés | Triage, search, FAQ : 4o mini ; synthèse : 5.2 low | MCP, via widget `/v3/chat/stream` |
| Main local / variantes | `cbe88b9963f28fbea932ac2a6ce23d22112f2b76` | Config Railway, puis un rôle changé par essai | MCP en lecture, services A2A / Redis isolés |
| Candidat final | même main + ce patch | Config Railway inchangée | Même proxy/cache MCP que les variantes locales |

Le MCP `dayuse-dev` interroge **la préproduction, reflet exact de la production
selon la confirmation de Victor**. Ce n'est pas un inventaire fictif. Les chemins
export/Qdrant et MCP, la fraîcheur des snapshots et la pagination peuvent néanmoins
différer ; nous n'avons pas vérifié une identité de snapshot. Le domaine direct du
concierge retournait 502 au contrôle initial ; le chemin widget client fonctionnait
et a servi aux rejeux. La préprod legacy a aussi été inspectée, sans rejeu envoyé.

## Ce que corrige le patch

- Le concierge persiste les contraintes reconnues avant l'appel de la feuille :
  un timeout ou une réponse sans payload ne doit plus effacer la demande.
- Tant qu'aucune ville n'est résolue, la feuille reçoit l'historique utilisateur
  récent borné. Une fois la ville connue, le profil fait référence pour éviter de
  réactiver un ancien budget. Les feuilles restent stateless.
- Le nom de la ville seul ne valide plus un quartier/POI différent : le faux
  géocodage Bercy → centre de Paris est refusé.
- `search_offers` utilise les coordonnées du géocodage réussi du tour. Les appels
  prématurés avec coordonnées inventées sont bloqués localement, sans fabriquer
  une panne MCP ni un inventaire vide.
- Une origine POI/GPS vérifiée impose `sortBy=distance` **avant pagination**. Le tri
  des recherches ville et les recherches par nom restent inchangés. L'argument
  optionnel passe par le garde de schéma existant.
- Le snapshot du contrat `search_offers` est rafraîchi depuis le MCP live, avec
  date de vérification propre à cet outil. Aucun nouveau regex ; aucune sélection
  de modèle ou configuration de production modifiée.

## Preuve isolée du tri de proximité

Même origine, date, rayon, première page de cinq hôtels ; seul `sortBy` change.
Distances à vol d'oiseau recalculées depuis les coordonnées retournées par le MCP.

| Origine | Plage des distances, pertinence par défaut | Tri distance |
|---|---|---|
| GPS Midtown Manhattan | 3,559–10,196 km | 0,149–0,242 km |
| Heathrow Terminal 3 | 1,099–1,842 km | 0,304–1,118 km |
| La Défense | 1,006–2,473 km | 0,362–0,788 km |

Les cinq distances sont croissantes dans chacun des trois essais avec le nouveau
tri. Cela ne prouve ni un temps de marche ni une résolution correcte de toutes
les formulations. Une mauvaise origine reste une mauvaise origine.

## Campagne et limites de mesure

- 41 séquences historiques, 139 tours par bras : legacy déployé, B2C déployé,
  puis candidat final local. 40 viennent des logs prod sans classification certaine
  client/QA ; une est synthétique. Les 24 séquences géographiques précédemment
  retenues sont incluses. Les anciennes dates ne valent pas vérité de disponibilité.
- 24 objectifs adaptatifs synthétiques sur les deux agents déployés et le candidat
  intermédiaire v2 ; 7 objectifs ciblés rejoués sur le candidat final. Les dialogues
  divergent en fonction des réponses, ils ne sont pas des paires identiques.
- 2 séquences de feedback adaptées (7 tours par bras). Lecture Langfuse fraîche :
  7 scores `user-feedback`, dont 5 négatifs en production dans seulement 2 sessions.
  Chaque score est joint à sa trace exacte. Ce n'est pas un taux de satisfaction.
- 7 séquences critiques répétées : deux rejeux supplémentaires main/v2, puis un
  rejeu supplémentaire du candidat final. Les gains de contexte ne sont pas stables
  sur toutes les répétitions : Milford réussit 2/3 fois en v2 contre 0/3 pour main.
- 16 invariants étroits sur les outils, annotés après observation ; pas un score
  global de qualité. Premier passage final : 3 passes, 4 échecs, 9 non exercés,
  contre 4/4/8 sur main. Le rejeu final des sept cas critiques conserve
  les échecs de créneau, durée et pagination ; Milford reste non exercé sur
  les deux passages finaux. Un appel absent ou une clarification ne compte pas comme
  une réussite. Aucun gain global ne peut être revendiqué à partir de ces nombres.
- Diagnostic séparé de 23 tours avec contraintes de cartes : final 3 conformes,
  8 avec écarts, 12 indéterminés ; legacy 15/5/3, B2C déployé 3/9/11. Une alternative
  honnêtement annoncée peut être une réponse utile : ce tableau ne note pas cette
  qualité de dialogue. Prix et créneau doivent appartenir à la même offre.

Le premier pilote du simulateur a inversé les rôles ; il est exclu de la qualité,
mais son coût est conservé. La validation automatique laisse encore passer des
changements d'objectif et une inversion de rôle : exclusions manuelles consignées.
Ni l'arrêt du simulateur, ni HTTP 200, ni le nombre de cartes ne valent succès.
Le registre de conservation contient 32 exigences, dont 23 partiellement ciblées
par cette campagne ; il ne garantit pas la conservation de six mois de correctifs.

## Modèles : pas de changement recommandé sur ces résultats

Mêmes 12 conversations / 41 tours, un passage exploratoire par bras. Coût total
observé des appels modèle de la conversation, incluant les autres rôles inchangés.

| Variante de main | Coût | Médiane / p95 |
|---|---:|---:|
| Config Railway | $0,224 | 5,8 / 11,8 s |
| Triage seul → 4.1 mini | $0,260 | 5,3 / 10,3 s |
| Search seul → 4.1 mini | $0,360 | 5,8 / 12,4 s |
| Search seul → 5.2 low | $1,078 | 9,9 / 19,7 s |
| Candidat final, config Railway | $0,237 | 5,8 / 12,6 s |

Search 5.2 coûte environ 4,8 fois le témoin sans résoudre globalement les échecs.
Échantillon trop petit pour départager statistiquement les modèles. Les problèmes
observés ne justifient pas un remplacement aveugle de 4o mini.

## Problèmes restant à traiter avant une validation de lancement

1. **Géographie et follow-up** : clarifications répétées JFK/Heathrow, Queens rejeté
   puis présenté comme panne, élargissement du rayon et exclusions de villes.
2. **Temps** : « 10 till 2 » supprimé par la sanitisation existante, 8h45 devenu
   08:00 avant la règle d'arrondi, durée seule transformée en heures. Le MCP live
   expose `timeSlotMode`, avec règles de bornes unilatérales différentes du code.
3. **Prix** : prix horaire interprété comme total ; montant USD appliqué au filtre
   EUR ; association du prix et du créneau de la même offre, frais compris.
4. **Contexte** : hôtel nommé/sélectionné perdu, retrait d'équipement fragile,
   question massage après recherche, retour FAQ vers recherche et pagination.
   Le feedback massage/JFK échoue encore sur le candidat final ; le suivi Lyon
   demain après-midi reste exploitable sans prouver un créneau complet.
5. **Couverture manquante** : navigateur/Voir tout, expiration, âges limites,
   fraîcheur et conflits FAQ, carte cadeau, retard/no-show, pannes injectées live,
   propriété d'une réservation et preuve d'action authentifiée. L'annulation sans
   compte est exercée en information, sans effectuer d'annulation réelle.

La production historique a aussi des défauts (South Plainfield → NYC malgré
l'exclusion, prix horaire Paramus, Berlin layover envoyé en FAQ). Elle sert de
comparateur, pas de vérité à reproduire.

## Validation et provenance

Tests locaux : **2 149 passés, 2 ignorés**. Ruff, mypy (59 fichiers), guardrails et
`git diff --check` passent. Python local 3.13 ; CI prévue en 3.12. Versions capturées :
google-adk 2.4.0, LiteLLM 1.90.2, mcp 1.28.1 ; dépendance fleet `8071917`.
Les quatre fichiers applicatifs ont des empreintes archivées avant le rejeu final.
La configuration Railway a été relue sans dérive sur les six services comparés.
Le schéma MCP `search_offers` live n'a pas changé pendant la campagne.

Artefacts privés : `reports/audit_eval_mcp_20261006/fresh_user_eval_v17/` dans le
workspace legacy : rapport comparatif HTML, reçus de coût, réponses, appels outils,
traces, configurations expurgées, exclusions, registre de couverture et scripts.
Les scripts privés exportés sont la version finale du harnais ; toutes les versions
intermédiaires du simulateur ne sont pas figées octet pour octet.

Coût cumulé observé des modèles, campagnes précédentes incluses : **$56.95**.
Provisions conservées : **$5.10**, dont $2 pour les évaluations automatiques
CI éventuelles. Total observé + provisions : **$62.05 / $110**. Marge
d’arrêt de $10 distincte ; aucun lot en attente. Mesure télémétrique, pas facture
fournisseur ni comptage exhaustif du coût infrastructure/Mapbox.
