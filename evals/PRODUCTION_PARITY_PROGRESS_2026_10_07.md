# Évaluation recherche avant remplacement de la production — 9 octobre 2026

**La PR apporte des correctifs vérifiés, mais le remplacement de production reste NO GO.**
Runtime évalué `83a640a8a51ac4b3692dc1ce6f36ac60c6bcbfe4` (v68), main
`cbe88b9` fetchée et inchangée. Production réellement appelée sur `ai.dayuse.com`,
déploiement `a08a7792`. Aucun merge, déploiement, réservation ou changement Railway.
FAQ, annulations et SAV restent en phase 2 ; les anciens changements FAQ du diff
cumulé ne sont pas validés par ce bilan recherche.

## Comparaison avec la production actuelle

58 conversations / 163 réponses **par agent**, toutes relues. Entrées identiques,
adaptateurs GPS propres au contrat de chaque API, nouvelles sessions synthétiques.
48 conversations historiques, une mixte et neuf scénarios synthétiques : 139 tours
reliés aux sources et 24 tours de test. Corpus ciblé, exposé pendant le développement,
issu de l'historique mai–octobre ; ni exhaustif ni holdout aveugle.

| Agent | A | B | C | D | F | Non notés |
|---|---:|---:|---:|---:|---:|---:|
| Production actuelle | 2 | 21 | 28 | 2 | 0 | 5 |
| Candidat v68 | 12 | 21 | 18 | 0 | 0 | 7 |

A = satisfaisant, B = défaut mineur, C = significatif, D = majeur, F = critique.
Revue Codex, pas validation humaine indépendante. Comparaison descriptive des
paires : **24 mieux notées, 5 moins bonnes, 19 identiques, 10 non comparables**
(au moins un agent non noté). Pas de supériorité statistique revendiquée.
Une clarification non répondue ne devient pas un succès. Les suivis historiques
peuvent devenir incohérents si les réponses des agents divergent.

La production utilise export/Qdrant ; le candidat utilise le MCP de préproduction,
reflet de la production selon l'équipe. Les passages sont successifs, aux dates
courantes : disponibilité, inventaire et récupération diffèrent. Une différence
de liste n'est donc pas automatiquement une erreur de modèle. Le témoin n'est
plus seulement une ancienne réponse SQL : ses 163 réponses ont été rejouées.

## Correctifs publiés et preuve réelle

Le concierge conserve les contraintes structurées et les transmet aux feuilles
A2A stateless ; Redis appartient toujours au concierge, modèles via LiteLLM.
Aucune nouvelle regex, dictionnaire de lieux ou phase modèle dans ce dernier lot.

- **Précision de lieu** : rue non résolue conservée après précision de ville ;
  23rd Street survit à New York. Pour un nouveau landmark dans la même ville,
  seul le pays déjà confirmé par le fournisseur est conservé. Le POI doit encore
  être résolu et contrôlé ; ni coordonnées anciennes ni pays contradictoire hérités.
- **Aéroports** : conservation de l'identifiant IATA structuré des POI aéroport,
  sans contourner identité, État, terminal ou contrôle de distance. LAX utilise
  désormais les coordonnées de l'aéroport ; DFW retourne des hôtels au terminal.
  Cela ne résout pas encore JFK ni tous les codes sans ville/GPS.
- **Participants** : modification citée dans le message courant extraite au
  triage existant, imposée au profil et aux paramètres A2A. Le retrait d'un enfant
  reste à zéro au suivi moins cher, sans rétablissement par une ancienne réponse.
- **Offre et équipements** : faits de la formule sélectionnée liés à hôtel,
  UUID et date ; noms, capacités, couchage et équipements listés survivent à
  search/details. Les faits périmés sont ignorés. Un jacuzzi hôtel ne prouve pas
  un jacuzzi dans la chambre ; la restitution reste toutefois imparfaite.
- **Nombres ambigus** : clarification avant recherche/synthèse lorsque le budget
  manque de provenance ou que le rôle numérique n'est pas reconnu. Les réponses
  explicites montant+devise reprennent le lieu. L'ancien champ bare_budget_value
  laisse encore certains nombres prendre prématurément le rôle de budget.

## Préservation de l'historique et suivis adaptatifs

**24 parcours géographiques supplémentaires / 72 tours historiques**, sans
recouvrement des lignes SQL avec le lot principal, reliés aux tests legacy dans
`geo_preservation_registry.json`. Sur les critères géographiques ciblés :
**9 préservés, 7 partiels, 5 en échec, 3 non évaluables**. Ce ne sont pas des notes
produit globales, et aucun nouveau témoin production n'a été rejoué sur ce lot.
Les résultats anciens du registre sont archivés séparément.

Préservés notamment : East Brunswick, Abu Dhabi, Milford CT, Melbourne Australie,
Heathrow terminal 3, Paris Bercy et Paddington. Encore en échec : Halton/Peel,
Berlin Mitte, JFK, correction de La Défense après faute initiale et demande de
trajet Metropark–Princeton. La Défense simple récupère au deuxième tour ; Milano
reste en Italie mais sa question de quartier échoue. Ambiguïtés Disneyland,
Halifax et Brooklyn sans réponse géographique restent non évaluables.

**Cinq diagnostics supplémentaires / 15 tours**, séparés des notes ci-dessus :
LAX et DFW récupèrent après ville explicite, avec origine aéroport vérifiée ;
Londres reprend le plafond 120 GBP. Denver reprend 65 USD et la durée, mais son
heure 8 h est omise dès le début de ce nouveau passage. L'échec de réponse
structurée de Venise ne se reproduit pas : **son premier C est conservé**.

## Blocages avant remplacement

Les cinq parcours moins bons que la prod concernent ZIP San Antonio, Lower
Manhattan ancré sur un commerce, San Bruno perdu au suivi budget, rooftop du soir
non vérifié et déjeuner transformé en petit-déjeuner dans les filtres.
Autres défauts : proximité aéroport Philadelphia encore calculée depuis le centre,
limites de quartiers/communes, omission de matinée ou heure d'arrivée, réactions
ironiques renvoyées à un accueil, jacuzzi privé non résolu et faux message de panne
quand la feuille répond sans résultat structuré. Des équipements pourtant listés
reçoivent encore une réserve inutile ; inversement, un équipement hôtel peut être
présenté comme un accès inclus dans la formule.

Le lot géographique a aussi affiché une formule William Vale à **0 EUR/0 USD**,
valeurs exactement présentes dans le reçu MCP. La jointure correcte ne valide
pas ce prix commercial : anomalie fournisseur et traitement des prix nuls à
clarifier. Aucun séjour gratuit ne doit être déduit de cette observation.

La prochaine correction doit traiter des familles ensemble : état sémantique
complet et réactions de suivi ; résolution/clarification des destinations et
périmètres ; preuves de formule, horaires et prix exploitables. Le gate reste un
rejeu complet et une revue équipe, pas seulement des tests unitaires verts.

## Contrôles et modèles

**2792 tests passent, 1 ignoré** ; ruff, mypy (71 fichiers) et guardrails verts.
71 fichiers runtime identiques avant/après les trois campagnes finales. Aucun
changement runtime pendant ces passages. Deux conversations indépendantes à la
fois, tours séquentiels ; aucune conclusion comparative de latence.

Lot principal : **262 cartes** jointes à hôtel/UUID/date/créneau du reçu du même
tour, zéro jointure manquante, écart de prix, expiration ou dépassement de plafond
vérifiable. 238 distances concordent avec l'origine stockée ; cela ne valide pas
cette origine ni un trajet. Deux créneaux 10 h 30 pour 10 h restent admis selon la
règle du site à l'heure entière, ici expliqués ; pas de garantie à la minute.
61 cartes avec occupation demandée, zéro capacité renseignée insuffisante,
une capacité absente. Geo : 115 cartes vérifiées, 103 distances ; diagnostics :
21 cartes et distances. Ces contrôles ne prouvent pas la qualité de la prose.

Configuration locale évaluée : **triage 4.1-mini / recherche 4o-mini / synthèse
5.2**. Nouveau B2C Railway a encore un triage 4o-mini ; le verdict ne se transpose
pas automatiquement à cette configuration. Production legacy : GPT-5.2.
518 appels physiques sur le lot principal, 226 geo et 42 diagnostics, tous avec
statut fournisseur ok ; cela n'exclut pas les échecs de résultat structuré.

Diagnostic modèle séparé : 18 contextes de triage figés × 2 tirages × 3 modèles,
108 appels pour 0,2067 USD. 5.2 améliore certains suivis mais omet aussi des
contraintes ; aucun gain universel démontré. Conserver la configuration évaluée
pour cette revue, sans upgrade global ni modification Railway. Ce petit diagnostic
exposé n'est pas un A/B complet permettant d'extrapoler les coûts en production.

## Coût et livraison

| Campagne de cette reprise | USD observés |
|---|---:|
| Candidat v65 | 1,595195 |
| Production actuelle, 58/163 | 3,419239 |
| Diagnostic trois modèles | 0,206713 |
| Candidat v66 | 1,555520 |
| Candidat v67 | 1,591637 |
| Candidat final v68, 58/163 | 1,584380 |
| Geo historique v68, 24/72 | 0,688725 |
| Diagnostics v68, 5/15 | 0,124687 |
| **Supplément consommé** | **10,766096** |

Autorisation humaine +40 EUR traitée conservativement comme +40 USD : plafond
opérationnel total **150 USD**, réserve 0,50. Cumul **119,739203 USD**, dont
**6,10 de provisions inconnues maintenues**. Estimation télémétrique des appels
modèle, pas facture fournisseur ni coût Codex/infrastructure. Langfuse production
relu deux fois au contrôle final : coût stable, aucun incrément tardif. Ledger
sans lot en attente ; les trois services agents locaux sont arrêtés.

Preuves privées hors Git : batch-v65 à batch-v68, manifestes, reçus, sources
hachées et revues liées à l'empreinte de chaque résultat. Rapport local
`production_parity_v18/current_evaluation.html` : conversations production/candidat
côte à côte et compléments ciblés. Source HTML contrôlée, pas inspection visuelle.
PR 134 demeure draft ; la CI du nouveau commit publié est vérifiée séparément.
