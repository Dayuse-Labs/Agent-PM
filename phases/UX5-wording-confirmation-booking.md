# UX5 — Le lien de réservation ne doit pas dire « c'est confirmé »

> Issu de la liste Fabien du 2026-08-27, item 5. **La plus petite des six, et la plus urgente
> à mettre en prod** : c'est une phrase qui induit l'utilisateur en erreur sur l'état de sa
> réservation. À faire AVANT UX2, qui réécrit le même fichier.

## Symptôme rapporté

> « Revoir le wording du message quand on choisit un rateplan : "C'est confirmé — voici votre
> lien de réservation pour Eklo Hotels Paris Roissy CDG Aéroport". Ça laisse à penser que le
> booking est confirmé. »

## Constat — le texte répond à la mauvaise question

`agents/b2c_concierge/b2c_concierge/templates.py:96-110`

```python
def booking_link_response(*, hotel_name: str, url: str | None, language: str) -> str:
    ...
    if language == "fr":
        return f"C'est confirmé — voici votre lien de réservation pour {hotel_name} : {url}"
    return f"Confirmed — here is your booking link for {hotel_name}: {url}"
```

Fabien a raison, et le fichier lui-même le prouve. Le tour **précédent** dit
(`templates.py:86-87`) :

> « Confirmez-vous cette réservation ? Je ne génère le lien qu'après votre confirmation explicite. »

Donc « C'est confirmé » confirme **l'intention de l'utilisateur**, pas la réservation. Mais
placé juste à côté d'un lien de réservation et du nom de l'hôtel, il se lit comme *« votre
chambre est réservée »*. C'est un contresens produit sur l'acte le plus engageant du parcours,
et il est d'autant plus trompeur que le lien mène à un tunnel où **rien n'est encore payé ni
bloqué**.

## Ce qu'il faut faire

Réécrire les deux branches pour dire ce qui est vrai : le lien est **prêt**, la réservation se
**termine** sur la page. Aucun changement de logique, aucun changement de payload, aucun
changement de signature.

Direction (le wording final est un arbitrage produit — proposer 2 ou 3 variantes à Fabien dans
la MR plutôt que d'en imposer une) :

- FR : `Voici votre lien pour réserver {hotel} — il reste à finaliser sur la page Dayuse : {url}`
- EN : `Here's your link to book {hotel} — you'll finalize on the Dayuse page: {url}`

Contraintes non négociables :

- ne pas affirmer un état de réservation qui n'existe pas (ni « confirmé », ni « réservé ») ;
- ne pas non plus verser dans le juridique anxiogène : c'est un lien, pas un contrat ;
- la phrase reste **une** ligne : la carte `booking_card` porte déjà le prix, le créneau et
  le CTA (`web/vendor/static/js/chat/ui/messages.js`), le texte ne doit pas la doubler.

Vérifier au passage `booking_offer_summary_response` (`templates.py:70-94`) : c'est le tour
d'AVANT, il est correct (il pose la question). Ne pas y toucher.

## Périmètre

`agents/b2c_concierge/b2c_concierge/templates.py` — une fonction, deux `return`. Plus les
tests qui asseyent la chaîne exacte.

## Pièges

- 🪤 Chercher les tests qui assertent la chaîne littérale **avant** d'éditer :
  `grep -rn "C'est confirmé" tests/ agents/*/tests/`. Un test qui ré-affirme le mauvais
  wording doit être corrigé, pas contourné.
- 🪤 **Ordonnancement** : UX2 réécrit intégralement `templates.py` pour 7 langues. UX5 doit
  être **mergée d'abord**, sinon UX2 traduit la mauvaise phrase en 5 langues de plus, ou pire,
  écrase la correction au merge.
- 🪤 Le guard R9 (`booking_confirmation`) n'est pas concerné : il garde `generate_booking_link`
  derrière le flag de confirmation dans l'état du tour, et il est re-dérivé de
  `profile.pending_booking` à son propre call site. Un texte ne l'affecte pas.

## DoD

1. 2 ou 3 variantes proposées à Fabien dans la description de MR ; celle retenue implémentée.
2. `pytest -q` vert (baseline 1452 passed, 1 skipped), `ruff`, `mypy`, guardrails verts.
3. **Preuve widget** : la séquence pick d'un rate plan en prod, capture du texte rendu.
   Pas seulement le test unitaire — c'est un changement dont la valeur est **ce que l'œil lit**.
4. `HANDOFF.md` : bloc daté (court, c'est une phrase).
