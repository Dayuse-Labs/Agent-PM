# Réponse MCP_B2C — enrichissement des offres (rate plans)

> Réponse à `PROMPT-MCP-B2C-RATEPLANS.md`. Rédigée le 2026-07-28 depuis le repo MCP_B2C,
> **après probe live** du cluster Elasticsearch (staging `hotel_staging_5`, réindexé le 2026-07-28) :
> 183 035 offres réelles sur 1 000 hôtels pour les taux de remplissage, 1 636 090 offres pour les
> énumérations, et un appel réel des tools pour la preuve de bout en bout.

## Verdict : c'est le cas (a) pour les deux champs — rien à faire côté pipeline d'indexation

Tes deux champs **sont déjà dans l'index**, mais dans le `_source` sans être **mappés**
(`dynamic:false`). Ils étaient donc invisibles à la fois du `_mapping` et de nos schémas Zod, qui
strippent les clés inconnues — d'où tes 0/4 300. Aucun réindex, aucune demande à porter sur
`dayuse.com`. Ils sont livrés.

Deux corrections utiles à ton modèle mental :

1. Le champ prix ne s'appelle pas `originalPrice` : c'est **`ratePlanPrices[].comparativePriceEuro`**.
   Tu as testé `originalPrice`, `original_price`, `priceEuroBeforeDiscount` — les trois sont bien
   absents. Le nom `comparative*` est la convention Dayuse pour le tarif barré.
2. Le nom de chambre n'est **pas sur l'offre** (l'objet offre a 45 clés dans le `_source`, aucune
   n'est un nom). Il vit dans un bloc **`ratePlans[]` à la racine du document hôtel**, non mappé lui
   aussi, joint à l'offre par `ratePlanId` — jointure vérifiée à **100 %** (94 732 / 94 732 offres).
   Et il est **localisé**, donc je te donne du vrai anglais, pas du texte partenaire en langue locale.

## Contrat exact en sortie

Trois clés ajoutées à l'objet offre, **purement additif** : aucune des 18 clés existantes n'est
renommée, supprimée ou réordonnée. Présentes sur `get_hotel_details` **et** `search_offers` (ainsi que
`compare_hotels.bestOffer` et le récap de `generate_booking_link`, qui partagent le même mapper).

| Clé                 | Type       | Unité / forme                        | Champ ES source                       | Remplissage constaté **dans ES**            |
| ------------------- | ---------- | ------------------------------------ | ------------------------------------- | ------------------------------------------- |
| `originalPriceEuro` | `number`   | **centimes EUR**, identique à `priceEuro` | `ratePlanPrices[].comparativePriceEuro` | 100 % en base ; **99,06 %** après filtre remise |
| `ratePlanName`      | `string`   | anglais (`names.en`)                 | `ratePlans[].names` (joint par `ratePlanId`) | **100 %**                                   |
| `includedAmenities` | `string[]` | noms anglais, tableau non vide       | `ratePlans[].amenitiesAccessIncluded` | **39 %** des formules (clé omise sinon)     |

### `originalPriceEuro` — l'unité est bien la tienne

Conversion FX vérifiée cohérente sur les offres hors zone euro (hôtel 7, USD) :
`hotelPrice` 10000 → `priceEuro` 8762 et `hotelComparativePrice` 18000 → `comparativePriceEuro`
15771, soit le **même ratio 0,8762**. C'est bien le tarif barré converti, pas une valeur en devise
hôtel.

⚠️ N'utilise **pas** `hotelComparativePrice` si tu le vois passer ailleurs : il est en **devise
hôtel**, et seules **34,6 %** des offres du parc sont en EUR.

### Le point qui demande ton attention : ES n'a jamais de NULL ici

Ton hypothèse « colonne NULL → clé omise » n'est pas reproductible : le champ est rempli sur
**100 %** des 183 035 offres probées (jamais `0`, jamais négatif). Le seul signal exploitable côté
serveur pour « pas de vraie remise » est donc `comparative ≤ price`.

**Taux d'anomalie mesuré** (ta question 1c) :

| Situation                    | Part                       |
| ---------------------------- | -------------------------- |
| `> priceEuro` (vraie remise) | **99,06 %**                |
| `== priceEuro`               | 0,08 %                     |
| `< priceEuro`                | **0,86 %**                 |
| Hôtels touchés par ≥ 1 anomalie | **27 / 1 000 (2,7 %)** |

Donc : **0,94 %**, pas 20 %. Et c'est une incohérence de la donnée partenaire, pas un artefact de
change — exemple hôtel 234 (BRL) : `hotelComparativePrice` 70439 < `hotelPrice` 79800, l'inversion
existe déjà en devise hôtel.

**Décision retenue** : le MCP **omet la clé** quand la valeur n'est pas **strictement supérieure** à
`priceEuro`. La règle est dans le domaine (`Offer.pickDiscountedFrom`) et testée. Conséquence pour
toi : ton filtre `original ≤ price` devient redondant (tu peux le garder, il ne coûte rien), et
**clé présente ⇒ remise réelle**, jamais d'affirmation fausse à afficher.

Distribution de la remise implicite, si ça t'aide à cadrer le discours produit :

| Tranche | 0–10 % | 10–25 % | 25–40 %   | 40–60 %   | 60–80 % | ≥ 80 % |
| ------- | ------ | ------- | --------- | --------- | ------- | ------ |
| Part    | 1,4 %  | 15,8 %  | **38,3 %** | **34,3 %** | 9,1 %   | 0,2 %  |

### `ratePlanName` — tes deux mises en garde sont confirmées, et l'anglais est disponible

- **C'est bien le nom de la chambre, pas de la formule.** Mesuré sur ES : **33,6 %** des hôtels
  multi-formules (108/321) n'ont qu'un seul nom distinct pour toutes leurs formules. `offerType`
  reste le discriminant, comme tu l'avais conclu. La description du tool le dit explicitement à
  l'agent.
- **Bonne nouvelle sur la langue** : `names` est un objet localisé (13 locales) et le slot `en` est
  rempli à **100 %**, réellement traduit dans **~87 %** des cas (les ~11 % restants sont du texte
  partenaire recopié à l'identique dans toutes les locales). Tu reçois donc `ratePlanName` en
  anglais — tu peux l'afficher tel quel, ou le laisser traduire par ton LLM sans mentir sur la
  provenance.

### `includedAmenities` — mieux que ce que tu espérais tirer du nom

Plutôt que de deviner la prestation incluse en parsant `"Standard Double Room With Meal"`, le rate
plan porte `amenitiesAccessIncluded`, structuré et localisé : je te le projette en tableau de noms
anglais (`["Outdoor pool"]`, `["Fitness room", "Indoor pool"]`, `["Free parking"]`). Couverture
**39 %** des formules, contre les 4,6 % que tu mesurais sur `addons_included`. Clé **omise** quand la
formule n'inclut rien.

À noter : `addons` (51 % non vide, avec prix) et `packagedAddons` (6,6 %, ≈ ton `addons_included`)
existent aussi dans le même bloc. Non exposés — dis-le si tu les veux, c'est le même chemin.

## Ce que je ne livre PAS, et pourquoi

**La surface de chambre.** Le champ `ratePlans[].surface` existe et est rempli à 92 %… mais **l'unité
change selon le marché et le document ne porte aucun champ d'unité** :

| Pays    | n   | médiane | min | max | part > 100 |
| ------- | --- | ------- | --- | --- | ---------- |
| FR      | 507 | 15      | 9   | 43  | 0 %        |
| IT      | 411 | 19      | 10  | 50  | 0 %        |
| GB      | 147 | 20      | 7   | 58  | 0 %        |
| **US**  | 47  | **245** | 29  | 398 | **91 %**   |

Les partenaires US saisissent des **square feet**, les autres des **m²** — et 9 % des valeurs US sont
≤ 100, donc même une inférence par `countryCode` transformerait une vraie chambre de 29 m² en 2,7 m².
Je ne peux pas t'annoncer une unité que je ne connais pas : c'est exactement l'imprécision qui te
coûte un aller-retour. **Le champ n'est pas exposé.** Si la surface t'intéresse, la demande est à
porter en amont (ajouter l'unité, ou normaliser à l'indexation) — là c'est bien du cas (b).

Confirmé aussi : `room_type` est vide (tu l'avais mesuré, je n'ai rien trouvé de mieux côté ES) ;
`bedding` et `capacity` restent tes descripteurs de chambre, et ils sont déjà dans le contrat.

## Effet de bord que j'ai dû corriger (à connaître)

Les nouvelles clés ajoutent **~123 caractères par offre (+25 %)**. Or `get_hotel_details` **sans
`date`** renvoyait jusqu'à 100 offres à venir : la réponse passait de 46 138 à 50 119 caractères,
au-delà du plafond de troncature du serveur (50 000) → `structuredContent` supprimé et JSON tronqué
**illisible**. Mesuré sur 6 hôtels : 5 basculaient en réponse tronquée.

Corrigé dans la même livraison : l'appel **sans date** renvoie les **40 dates les plus proches** avec
`hasMoreUpcomingOffers: true` quand il y en a d'autres (rappeler avec `date` pour les voir). Les 6
hôtels repassent à 25–28 k caractères avec `structuredContent` valide. **Ton chemin avec `date` n'est
pas concerné** (une poignée d'offres, ~5 600 caractères).

Contexte : sur le parc, la médiane est de **164 offres à venir par hôtel** (p90 = 328) — l'appel sans
date n'a jamais été un moyen viable de tout lister.

## Preuve live (appel réel, pas un mock)

`get_hotel_details` sur l'hôtel 18 (Pullman Miami Airport), date `2026-07-30`, via le serveur MCP
branché sur l'Elastic réel :

```json
[
  {
    "ratePlanId": 16868,
    "offerType": "dayuse.day",
    "priceEuro": 10427,
    "originalPriceEuro": 15640,
    "ratePlanName": "Superior Room, 2 full-size beds, City View",
    "includedAmenities": ["Outdoor pool"]
  },
  {
    "ratePlanId": 16867,
    "offerType": "dayuse.day",
    "priceEuro": 10427,
    "originalPriceEuro": 15640,
    "ratePlanName": "Superior Room, 1 King-size bed, City View",
    "includedAmenities": ["Outdoor pool"]
  }
]
```

`search_offers` (Paris, `2026-07-30`) — même contrat, deux formules du même hôtel partageant le nom
de chambre mais pas le créneau (ta mise en garde, en vrai) :

```json
{
  "priceEuro": 9500,
  "originalPriceEuro": 28000,
  "ratePlanName": "Comfort Room",
  "includedAmenities": ["Fitness room", "Indoor pool"]
}
```

Et la preuve que le filtre d'anomalie mord : sur l'hôtel 234 (BRL, `comparative < price`), 6 des 40
offres renvoyées **n'ont pas** la clé `originalPriceEuro` — les 34 autres l'ont.

## Réponse à ta question annexe — les énumérations, exhaustives

Agrégations `terms` sur **tout l'index** (1 636 090 offres, hôtels actifs non-test) : `sum_other` = 0,
donc les listes sont complètes.

**`offerType` — 7 valeurs**, tes 5 plus deux résidus :

| Valeur                       | Part    |
| ---------------------------- | ------- |
| `dayuse.day`                 | 72,76 % |
| `dayuse.early`               | 10,32 % |
| `dayuse.late_break`          | 10,02 % |
| `dayuse.dayuse_pm`           | 3,78 %  |
| `dayuse.dayuse_am`           | 3,10 %  |
| `daycationBusiness.business` | 0,01 %  |
| `.` (un point, donnée sale)  | 0,01 %  |

Garde ta dégradation propre (valeur inconnue → afficher le créneau) : elle couvre exactement ces deux
derniers cas, qui ne méritent pas de traduction.

**`bedding` — 14 valeurs, et 3,24 % d'offres sans valeur** (ton échantillon à 100 % n'était pas
représentatif) :

| `double` | `double_king` | `double_queen` | `twin_double` | _(absent)_ | `twin_two_queens` | `twin_doubles` | `twin_singles` | `single` | `family` | `quadruple` | `triple` | `none` | `twin_two_kings` |
| -------- | ------------- | -------------- | ------------- | ---------- | ----------------- | -------------- | -------------- | -------- | -------- | ----------- | -------- | ------ | ---------------- |
| 50,37 %  | 21,85 %       | 10,02 %        | 6,53 %        | 3,24 %     | 2,76 %            | 1,46 %         | 1,17 %         | 1,01 %   | 0,54 %   | 0,54 %      | 0,30 %   | 0,19 % | 0,03 %           |

En bonus, les autres énumérations fermées du contrat, tant que j'y étais :

- `commercialType` : `dayuse` 99,71 %, `dayaccess` 0,29 %
- `mainAssetType` : `dayuse` 99,71 %, `daypool` 0,16 %, `cabana` 0,06 %, `spapass` 0,06 %, `sunbed` 0,02 %
- `prepaymentRequirement` : `none` 73,27 %, `partial` 23,30 %, `full` 3,43 %
- `status` : `open` 74,52 %, `closed` 15,80 %, `free_sale` 9,37 %, `request` 0,31 %

## Réserves honnêtes

- **Les chiffres viennent du cluster staging** (`dayuse-staging-eu`, index `hotel_staging_5`), pas de
  la prod : c'est celui auquel le MCP est branché. La prod est un cluster distinct alimenté par le
  même indexeur — les champs devraient s'y comporter à l'identique, mais **à revérifier au déploiement**
  (un appel réel suffira).
- **Aucune écriture** n'a été faite : `_search`, `_mapping` et agrégations uniquement.
- **Latence** : la jointure ne coûte aucune requête supplémentaire — le repository ne filtre pas le
  `_source`, donc `ratePlans` était déjà sur le fil. Le seul effet mesuré sur le volume est celui
  décrit plus haut, corrigé.
