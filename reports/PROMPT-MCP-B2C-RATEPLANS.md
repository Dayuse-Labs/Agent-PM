# Prompt à injecter dans une session Claude Code sur le repo MCP_B2C

> Copier/coller tout ce qui suit (à partir de la ligne `---`). Rédigé le 2026-07-28 depuis
> AgentB2C, **après probes live** : 4 300 offres réelles sur 51 hôtels via `get_hotel_details`,
> plus un snapshot catalogue de production (8 701 hôtels / 22 177 rate plans).

---

## Contexte

Je développe **AgentB2C** (orchestrateur conversationnel day-use, ADK Python), consommateur de tes
tools MCP en lecture seule. Je viens de livrer un **sélecteur de rateplan** : quand l'utilisateur
choisit un hôtel, la carte de réservation liste toutes les formules du jour et chaque ligne renvoie
au tunnel avec son `ratePlanUuid`.

**C'est déjà en PR et fonctionnel avec ce que tu exposes aujourd'hui** — je ne suis pas bloqué. Je
viens chercher **deux champs**, dont un qui débloque l'argument commercial central du day-use.

J'ai fait mes devoirs avant d'écrire : tout ce qui suit est mesuré, pas supposé.

## Le contrat que j'observe aujourd'hui

Probe live `get_hotel_details`, **4 300 offres sur 51 hôtels multi-formules**. Le schéma d'une
offre fait **exactement 18 clés, présentes sur 100 % des offres** :

```
availabilityDate, ratePlanId, ratePlanUuid, ratePlanPolicyUuid,
startHour, startMinute, endHour, endMinute,
priceEuro, priceEuroWithBookingFees,
offerType, commercialType, bedding, capacity, childrenCapacity,
isOvernight, cutoffDeadlineUtc, minutesRemainingUntilCutoff
```

Deux de ces champs m'ont fait changer ma conception, et méritent des remerciements :

- **`offerType`** — enum fermé, 5 valeurs sur mon échantillon : `dayuse.day` (72 %),
  `dayuse.late_break` (13 %), `dayuse.early` (11 %), `dayuse.dayuse_pm` (3 %), `dayuse.dayuse_am`
  (0,7 %). Je le traduis côté widget en « Journée / Soirée / Matinée / Après-midi » dans 7 langues.
  **C'est le seul champ qui distingue deux formules d'un même hôtel** — sans lui je n'avais pas de
  feature.
- **`bedding` + `capacity`** — peuplés sur 100 % des offres (`double`, `double_king`,
  `double_queen`, `twin_*`, `single` ; capacity = 2 sur 92 %). Ils me servent de descripteur de
  chambre.

## Demande n° 1 — `originalPriceEuro` (la vraie demande)

| | |
|---|---|
| **Champ** | `originalPriceEuro`, centimes EUR, **même convention que `priceEuro`** |
| **Colonne Postgres** | `rate_plans.original_price` |
| **Remplissage en base** | **21 912 / 22 177 = 98,8 %** |
| **Envoyé par MCP aujourd'hui** | **jamais** (0 / 4 300 offres, testé aussi en `originalPrice`, `original_price`, `priceEuroBeforeDiscount`) |

C'est le tarif nuit que le prix day-use casse — **l'argument de vente central du produit**
(« €219 barré, −60 % »). Aucune de nos surfaces ne peut l'afficher aujourd'hui parce que le champ
ne sort pas de MCP. Mon rendu est déjà écrit, testé et mergeable ; il attend la donnée.

Un champ, présent sur 98,8 % du parc. Si tu n'en fais qu'un, fais celui-là.

## Demande n° 2 — `ratePlanName` (bonus 2-en-1, moins urgent)

| | |
|---|---|
| **Champ** | `ratePlanName`, string |
| **Colonne Postgres** | `rate_plans.rate_plan_name` |
| **Remplissage** | rempli, mais **texte libre saisi par le partenaire, en langue locale** |
| **Envoyé par MCP aujourd'hui** | **jamais** (0 / 4 300) |

**Attention à l'usage que j'en fais** — pas un titre. Deux mesures :

1. C'est le nom de la **CHAMBRE**, pas de la formule (« Standard Double Room », « Chambre Double
   Standard », « Camera doppia standard », « Standard-Doppelzimmer »).
2. **2 829 des 5 591 hôtels multi-formules donnent le MÊME nom à toutes leurs formules** → l'utiliser
   comme titre afficherait trois lignes identiques. `offerType` fait ce travail.

**Pourquoi je le veux quand même** : il **encode souvent la prestation incluse**. Exemples réels du
snapshot — hôtel 20235 : `rate_plan_name = "Standard Double Room With Meal"` avec
`addons_included = ['Meal']` ; hôtel 22463 : `"Habitat Room with F&B credit"` avec
`addons_included = ['F&B credit']`. Donc **un seul champ me donne le descriptif de chambre ET
l'indice de prestation**, là où `addons_included` seul ne couvrirait que 4,6 % du parc.

Je l'affiche en sous-titre de ligne, tel quel, sans traduction (c'est du texte partenaire — je ne
prétendrai pas l'avoir traduit).

## Ce que je NE demande PAS — n'y passe pas de temps

Vérifié sur les 22 177 lignes du snapshot de production :

| Colonne | Réalité mesurée | Conclusion |
|---|---|---|
| `room_type` | **NULL sur 22 177 / 22 177** | Colonne vide. Inutile à exposer — j'utilise `bedding`/`capacity`. |
| `addons_included` | **1 020 / 22 177 = 4,6 %**, casse incohérente (« Fitness Access » vs « Fitness access ») | Trop creux pour porter l'UI, et `ratePlanName` (demande n° 2) en donne l'essentiel. À exposer un jour, normalisé, sans urgence. |

## Contraintes non négociables

- **Purement additif.** Ne renomme, ne supprime, ne réordonne aucun des 18 champs existants. Trois
  consommateurs dépendent du contrat actuel, dont un guard AgentB2C qui vérifie que la carte
  affichée et le lien du tunnel décrivent la même réservation.
- **Absent plutôt que deviné.** Colonne NULL → **omets la clé**. Pas `0`, pas `null`, pas de
  valeur par défaut. Côté widget, clé absente = pas de badge de remise, ce qui est le comportement
  correct : une remise est une **affirmation**, et une affirmation fausse sur un prix nous expose
  juridiquement.
- **Unité identique à `priceEuro`** (centimes EUR). Si tu choisis autre chose, dis-le
  explicitement : je code contre ta description, une imprécision de nom ou d'unité me coûte un
  aller-retour complet.
- **Priorité `get_hotel_details`** — c'est le tool du tour de sélection, là où les formules
  s'affichent. `search_offers` en bonus (« à partir de » enrichi d'une remise). Si tu n'en fais
  qu'un, fais `get_hotel_details`.
- **Lecture seule**, aucune régression de latence sur les chemins existants.

## Méthode attendue

1. **Probe d'abord, code ensuite. Dis-moi ce que tu trouves AVANT d'implémenter.** Trois issues
   très différentes en coût :
   - **(a)** le champ est dans l'index ES mais pas projeté dans la réponse du tool → simple ajout
     de projection, meilleure nouvelle ;
   - **(b)** absent de l'index ES → changement de mapping + réindexation, donc une demande en
     amont sur le pipeline d'indexation (repo dayuse.com) et **pas chez toi** : dis-le moi et je
     porte la demande ailleurs, sans te faire perdre de temps ;
   - **(c)** présent mais incohérent (ex. tarif nuit ≤ tarif jour sur une partie du parc) →
     donne-moi **le taux d'anomalie**. Je filtre déjà `original ≤ price`, mais je dois savoir si
     c'est 0,1 % ou 20 % : ça change ce que je promets au produit.
2. **Le contrat exact en sortie** : nom, type, unité, tools concernés, et **taux de remplissage
   constaté dans ES** — pas dans Postgres, c'est ES qui me répond.
3. **Une preuve live, pas un mock.** Un appel réel montrant le champ dans une réponse réelle. Un
   test unitaire vert ne prouve pas que l'index porte la donnée — c'est exactement l'erreur qui
   m'aurait fait concevoir cette feature autour de `rate_plan_name`.

## Note de franchise

Si `originalPriceEuro` est un chantier d'indexation lourd, dis-le tout de suite. Mon sélecteur part
en prod sans lui, et je préfère « c'est (b), voici qui contacter » en deux heures qu'un chantier
surprise d'une semaine. Le seul scénario qui me coûte cher, c'est un champ livré sous un nom ou une
unité que je n'attendais pas.

Question annexe, si c'est gratuit pour toi : **l'enum `offerType` a-t-il d'autres valeurs** que mes
5 ? Mon échantillon fait 51 hôtels. Je dégrade proprement (valeur inconnue → j'affiche le créneau
horaire), mais avec la liste exhaustive je traduis proprement les 7 langues. Même question pour
`bedding`.
