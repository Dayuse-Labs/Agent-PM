# Prompt à injecter dans une session Claude Code sur le repo MCP_B2C

> Copier/coller tout ce qui suit (à partir de la ligne `---`) dans une session fraîche ouverte sur
> le repo MCP_B2C. Rédigé le 2026-07-28 depuis AgentB2C, **après probes live** contre MCP_B2C et
> contre un snapshot catalogue de production (8 701 hôtels / 22 177 rate plans).

---

## Contexte

Je travaille sur **AgentB2C** (orchestrateur conversationnel day-use, ADK Python), qui consomme
tes tools MCP en lecture seule. Je viens de livrer un **sélecteur de rateplan** : quand
l'utilisateur choisit un hôtel, la carte de réservation liste toutes les formules du jour et
chaque ligne renvoie au tunnel avec son `ratePlanUuid`.

**C'est déjà fonctionnel avec ce que tu exposes aujourd'hui.** Je ne viens pas demander un
déblocage : je viens demander **un seul champ** qui manque, et te signaler deux champs qu'il ne
faut surtout pas que je te demande (j'ai vérifié, ils sont vides).

## Ce que j'ai vérifié moi-même avant de t'écrire

**Probe live `get_hotel_details`** (hôtel 22293, 4 596 offres sur 51 hôtels multi-formules) — les
offres portent déjà :

```
availabilityDate, ratePlanId, ratePlanUuid, ratePlanPolicyUuid,
startHour, startMinute, endHour, endMinute,
priceEuro, priceEuroWithBookingFees,
offerType, commercialType, bedding, capacity, childrenCapacity,
isOvernight, offerType, cutoffDeadlineUtc, minutesRemainingUntilCutoff
```

Deux découvertes qui ont **changé ma conception**, et pour lesquelles je te remercie sans le
savoir :

1. **`offerType` est exactement ce qu'il me fallait.** Enum fermé, 5 valeurs sur mon échantillon :
   `dayuse.day` (72 %), `dayuse.late_break` (13 %), `dayuse.early` (11 %), `dayuse.dayuse_pm`
   (3 %), `dayuse.dayuse_am` (0,7 %). Je le traduis côté widget en « Journée / Soirée / Matinée /
   Après-midi » dans 7 langues. **C'est le seul champ qui distingue deux formules d'un même
   hôtel** — voir pourquoi au point suivant.
2. **`bedding` + `capacity` sont peuplés** (`double`, `double_king`, `double_queen`, `twin_*`,
   `single` ; capacity = 2 sur 92 %). Ils me servent de descripteur de chambre.

**Question ouverte n° 1 (petite)** : mon échantillon fait 51 hôtels. **L'enum `offerType`
comporte-t-il d'autres valeurs** que ces 5 ? Je dégrade proprement (une valeur inconnue affiche le
créneau horaire), mais si tu me donnes la liste exhaustive je la traduis proprement. Même question
pour `bedding`.

## Ce que je NE te demande pas (vérifié vide — n'y passe pas de temps)

Snapshot catalogue de production, table `rate_plans`, 22 177 lignes :

| Colonne | Remplissage réel | Conclusion |
|---|---|---|
| `room_type` | **0 / 22 177** — NULL partout | Inutile à exposer. J'utilise `bedding`/`capacity`. |
| `addons_included` | **1 020 / 22 177 (4,6 %)** — et casse incohérente (« Fitness Access » vs « Fitness access ») | Trop creux pour porter l'UI. À exposer un jour, sans urgence, normalisé. |
| `rate_plan_name` | rempli, mais c'est le nom de la **CHAMBRE**, pas de la formule (« Standard Double Room », « Chambre Double Standard », « Camera doppia standard ») — et **2 829 des 5 591 hôtels multi-formules donnent le MÊME nom à toutes leurs formules** | Inutilisable comme titre de ligne : ça afficherait trois lignes identiques. `offerType` fait le travail. |

C'est aussi la réponse à la question que j'allais te poser sur la fiabilité du nommage hôtelier :
il est effectivement libre et multilingue. Tant mieux que `offerType` existe.

## La demande : UN champ

| Champ souhaité | Colonne Postgres | Remplissage en base | Pourquoi |
|---|---|---|---|
| **`originalPriceEuro`** (centimes EUR, même convention que `priceEuro`) | `rate_plans.original_price` | **21 912 / 22 177 = 98,8 %** | Le tarif nuit que le prix day-use casse. C'est **l'argument de vente central du day-use** et aucune de nos surfaces ne peut l'afficher : le champ ne sort pas de MCP. J'ai déjà le rendu (« €219 barré, −60 % ») écrit et testé, il attend la donnée. |

Un seul champ, présent sur 98,8 % du parc, qui débloque l'argument commercial le plus fort du
produit. C'est tout ce que je demande.

## Contraintes non négociables sur l'implémentation

- **Purement additif.** Ne renomme, ne supprime, ne réordonne aucun champ existant : trois
  consommateurs dépendent du contrat actuel, dont un guard AgentB2C qui vérifie que la carte
  affichée et le lien du tunnel décrivent la même réservation.
- **Absent plutôt que deviné.** Si `original_price` est NULL pour un rate plan, **omets la clé** —
  pas `0`, pas `null`, pas une estimation. Côté widget, pas de clé = pas de badge de remise, ce
  qui est le comportement correct : une remise est une **affirmation**, et une affirmation fausse
  sur un prix nous expose.
- **Même unité que `priceEuro`** (centimes EUR). Si tu choisis une autre unité ou un autre nom,
  dis-le explicitement — je code contre ta description, une imprécision me coûte un aller-retour.
- **Priorité `get_hotel_details`.** C'est le tool du tour de sélection. `search_offers` en bonus
  (j'y afficherais un « à partir de » avec la remise), mais si tu n'en fais qu'un, fais
  `get_hotel_details`.
- **Lecture seule**, aucune régression de latence sur les chemins existants.

## Ce que j'attends comme réponse

1. **Un probe live d'abord**, et dis-moi ce que tu trouves avant d'implémenter : `original_price`
   est-il dans l'index ES ? Trois issues très différentes en coût :
   - **(a)** dans l'index mais pas projeté dans la réponse → simple ajout de projection ;
   - **(b)** absent de l'index → changement de mapping + réindexation, donc une demande en amont
     sur le pipeline d'indexation (repo dayuse.com), **pas chez toi** — dis-le moi et je porte la
     demande ailleurs ;
   - **(c)** présent mais incohérent avec `priceEuro` (ex. tarif nuit inférieur au tarif jour sur
     une partie du parc) → donne-moi le taux d'anomalie. Je filtre déjà les cas
     `original ≤ price`, mais je veux savoir si c'est 0,1 % ou 20 %.
2. **Le contrat exact en sortie** : nom, type, unité, tools concernés, taux de remplissage
   constaté en ES (pas en Postgres — c'est ES qui me répond).
3. **Une preuve live**, pas un test sur mock : un appel réel montrant le champ dans une réponse
   réelle. Un test unitaire vert ne prouve pas que l'index porte la donnée.

## Note de courtoisie

Si `originalPriceEuro` est un chantier d'indexation lourd, dis-le franchement : mon sélecteur est
déjà en production sans lui, et je préfère une réponse « c'est (b), voici qui contacter » en deux
heures qu'un chantier surprise d'une semaine. Le seul scénario qui me coûte cher, c'est un champ
livré sous un nom ou une unité que je n'attends pas.
