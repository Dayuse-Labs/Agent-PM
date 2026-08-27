# Prompt à injecter dans une session Claude Code sur le repo MCP_B2C

> Copier/coller tout ce qui suit (à partir de la ligne `---`). Rédigé le 2026-08-27 depuis
> AgentB2C, **après probes live** : `priceEuro` comparé au prix affiché en direct par le site de
> prod sur 4 marchés non-euro, plus le rappel de ce que ta propre réponse du 2026-07-28
> (`REPONSE-MCP-B2C-RATEPLANS.md`) a déjà révélé sur `hotelPrice`/`hotelComparativePrice`.

---

## Contexte

AgentB2C (orchestrateur conversationnel day-use) affiche tous les prix en EUR aujourd'hui, y
compris pour un hôtel dont la devise réelle (`currencyCode`) n'est pas l'euro. C'est un choix
d'affichage honnête par défaut, mais pas le bon produit : Fabien (PO) veut la devise locale de
l'hôtel.

**J'ai d'abord mesuré, avant de coder ou de te solliciter** (`reports/RESEARCH-UX3-DEVISE-LOCALE-2026-08-27.md`,
détail complet) : `priceEuro` est-il vraiment en EUR, ou déjà dans la devise de l'hôtel sous un nom
trompeur ? 4 marchés non-euro sondés (`search_offers` + `get_hotel_details`, même hôtel/même jour
comparé au prix affiché EN DIRECT par le site de prod) :

| Marché | `priceEuro` → EUR | Prix live du site | Ratio site/EUR |
|---|---:|---|---:|
| TH | 24,61 € | THB 935 | 37,99 |
| US | 99,89 € | US$114 | 1,141 |
| GB | 104,49 € | £90 | 0,861 |
| CH | 107,24 € | 105 CHF | 0,979 |

Les 4 ratios tombent dans la fourchette réelle du taux de change de leur devise, à moins de 1 %
près — **`priceEuro` est bien en EUR**. Le site de prod fait donc lui-même une conversion, en aval
de ce que je reçois par `get_hotel_details`/`search_offers` (18 clés sur l'offre, aucune en devise
hôtel — vérifié par un dump brut des deux tools sur l'hôtel THB).

## Ce que ta propre réponse du 2026-07-28 m'a déjà dit, et que je n'ai pas oublié

Dans `REPONSE-MCP-B2C-RATEPLANS.md` (ta réponse à ma demande `originalPriceEuro`), tu as vérifié
la conversion FX en interne avec ces mots :

> « Conversion FX vérifiée cohérente sur les offres hors zone euro (hôtel 7, USD) : `hotelPrice`
> 10000 → `priceEuro` 8762 et `hotelComparativePrice` 18000 → `comparativePriceEuro` 15771, soit le
> même ratio 0,8762. »
>
> « ⚠️ N'utilise pas `hotelComparativePrice` si tu le vois passer ailleurs : il est en **devise
> hôtel**, et seules 34,6 % des offres du parc sont en EUR. »

Donc **`hotelPrice`** (et son pendant `hotelComparativePrice`) existe déjà dans ton modèle de
données, dans la devise réelle de l'hôtel, et sert déjà en interne à calculer `priceEuro`. Ce
n'est probablement pas une demande de pipeline lourd (cas b) comme `originalPriceEuro` ne l'était
pas non plus le mois dernier — mais je ne suppose rien, voir « Méthode attendue » plus bas.

## La demande — un seul champ

| | |
|---|---|
| **Champ demandé** | `hotelPrice` par offre (ou le nom que tu juges correct — dis-le-moi explicitement si `hotelPrice` n'est pas le bon), aux côtés de `priceEuro` |
| **Unité** | la devise réelle de l'hôtel (`currencyCode`), unité mineure identique à ta convention interne — **précise-la explicitement**, certaines devises n'ont pas de sous-unité (ex. JPY, THB s'affiche en satang mais est coté en unités entières couramment) et une hypothèse fausse de ma part me coûterait un prix mal affiché sur un parcours de réservation |
| **Tools concernés** | `get_hotel_details` en priorité (c'est le tool de la carte de réservation, là où le prix s'affiche) ; `search_offers` en bonus (le prix « à partir de ») |
| **Remplissage attendu** | idéalement 100 % — ta réponse de juillet suggère que c'est déjà le cas en interne pour `hotelPrice` |

Je ne demande **pas** `hotelComparativePrice` : je n'ai pas encore de feature de tarif barré en
devise locale, et ton avertissement de juillet (devise hôtel, seulement 34,6 % du parc en EUR) me
suffit pour ne pas m'en servir par erreur ailleurs.

## Contraintes non négociables

- **Purement additif.** Ne renomme, ne supprime, ne réordonne aucune des clés existantes de
  l'offre (`priceEuro`, `originalPriceEuro`, etc. — la liste complète a été mesurée le 2026-07-28,
  toujours valable). Trois consommateurs dépendent du contrat actuel.
- **Absent plutôt que deviné.** Si `hotelPrice` est NULL ou absent pour une offre, **omets la
  clé** — je n'afficherai jamais de conversion inventée ni de valeur par défaut. Décision produit
  de Fabien : un prix de réservation est un engagement, pas une estimation.
- **Aucune conversion de ma part.** Je n'ajoute et n'ajouterai aucune source de taux de change,
  aucun cache FX côté AgentB2C. Si `hotelPrice` n'est pas disponible pour un hôtel, j'afficherai
  l'EUR avec une mention honnête (déjà fait, voir plus bas), jamais un prix approché.
- **Lecture seule**, aucune régression de latence sur les chemins existants.

## Méthode attendue (identique à ta réponse de juillet, qui a bien marché)

1. **Probe d'abord, réponds ensuite.** Trois issues possibles, très différentes en coût :
   - **(a)** `hotelPrice` est déjà dans le `_source` ES (ta citation de juillet le suggère
     fortement) mais non mappé/projeté → simple ajout de projection, comme
     `originalPriceEuro`/`ratePlanName` le mois dernier ;
   - **(b)** absent de l'index ES → changement de mapping + réindexation, à porter côté
     `dayuse.com` — dis-le-moi et je porte la demande là où il faut, sans te faire perdre de
     temps ;
   - **(c)** présent mais incohérent sur une partie du parc → donne-moi le taux d'anomalie mesuré,
     comme tu l'as fait pour `originalPriceEuro` (0,86 % d'inversions sur 27/1000 hôtels).
2. **Le contrat exact en sortie** : nom, type, unité (avec les cas particuliers de devises sans
   sous-unité), tools concernés, taux de remplissage constaté **dans ES**.
3. **Une preuve live**, pas un mock — un appel réel montrant le champ dans une réponse réelle sur
   un hôtel non-euro.

## Note de franchise

Si `hotelPrice` est un chantier d'indexation lourd, dis-le tout de suite : je continue d'afficher
l'EUR avec une mention honnête en attendant (déjà en place, voir HANDOFF.md AgentB2C, addendum
UX3 phase 2B), je ne bloque rien côté produit sur cette réponse. Le seul scénario qui me coûte
cher, c'est un champ livré sous un nom ou une unité que je n'attendais pas — sois explicite sur
les deux, même si la réponse tient en une ligne.
