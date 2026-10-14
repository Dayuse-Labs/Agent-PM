# DIAGNOSTIC — Retours QA de Raphael sur #14707 (2026-10-14)

> Source : https://gitlab.com/dayuse/dayuse/dayuse-com/-/work_items/14707, commentaire du 2026-10-14 (08:54 UTC).
> Preuves : 14 traces Langfuse des sessions de Raphael (08:44 → 09:15 UTC), code `main` local `49d5bd3`. Aucun code modifié.
> ⚠️ `origin/main` a 7 commits d'avance sur le `main` local (PORT1, sans fichier géo) : fetch avant de brancher.

## 0. La prod n'est pas `main`

Les 14 traces portent `release = cbe88b9` (build du 07/10). #135 (= #124 + #125 : `pending_search`, `pending_place`, hôtel nommé, garde #18, `fc5cbd9`) **n'est pas déployée**. Conséquence immédiate : les retours du 30/09 traités par #124/#125 (Saint-Paul à Londres, conversation qui se réinitialise) n'ont jamais été servis à la QA. Le ticket est en « To test » sur un build plus ancien que ce qui a été annoncé.

## 1. Diagnostic (prouvé par trace sauf mention)

| Retour | Ce qui s'est passé | Cause racine | `main` corrige ? |
|---|---|---|---|
| **1.** Créneau « 10am - 4pm » en conversation FR | Le MCP renvoie `10:00`–`16:00` ; `formatTimeAMPM` (`web/vendor/static/js/chat/utils.js:46`) code am/pm en dur, appelé à `hotels/card.js:677` et `:717`. La carte de réservation a un 3e format, brut (`ui/messages.js:663`, `10:00 – 16:00`) | Widget : l'affichage ignore la langue | Non |
| **2A.** « paris Gare du nord » → « Paris, Bruxelles ou une autre ? » | Feuille (4o-mini) : `geocode_location(city="", zone="Gare du Nord", raw_user_message="Gare du nord Paris")` → `geocode_city_needed` (question **sans option**, par construction) → la **synthèse gpt-5.2 invente « Bruxelles »**. Au tour suivant, « 10 am » est perdu (`search_offers` sans `timeSlot`) | (a) le LLM de la feuille jette la ville nommée (exception « lieu nommé d'après une ville où il n'est pas », `hotel_search_agent/agent.py:173-190`) ; (b) la synthèse réécrit une question du code et y ajoute des options | Par une regex (`fc5cbd9`, `_city_named_in_message`, `geocode_tool.py:230-270`), qui ne capture même pas « paris » ici (« room in » est avalé) |
| **2B.** « Boulevard de la République Versailles » | `zone="Boulevard de la République Versailles"`, `city=""` → `city_needed` → la synthèse invente « Versailles (78) ou une autre commune » | La ville est enfouie dans `zone` : le contrat (2 chaînes libres `city`/`zone`) n'a pas de place pour une adresse | Non |
| **3 T0.** « 2 boulevard Poissonnière 75009 » | `zone="2 boulevard Poissonnière"` (code postal retiré), `city=""` → `city_needed` → la synthèse invente « c'est bien Paris (75009) ? » / « plusieurs communes » | Aucun champ code postal. La seule règle existante est un ZIP US par regex | Non |
| **3 C1.** « Oui Pari vers 14h » → boucle | La feuille, sans état, ne reçoit que « Oui Pari vers 14h ». La zone est reprise du profil, la ville reste vide (« Pari » non compris) → `city_needed` → paraphrase « il me manque la ville (Paris, Lyon, etc.) ». `guard_anti_clarification_loop` = 0 : il compare des paraphrases | Pas d'état de clarification structuré ; garde anti-boucle sur du texte | En partie : `pending_search` (#135) renvoie la demande et la question à la feuille, mais la question est extraite **par regex** de la paraphrase (`profile.py:1041-1071`) |
| **3 C2.** « Je confirme » → « Je n'ai pas encore de liste d'hôtels » | Triage `{"family":"booking","booking_confirmation":"confirm"}` → route `generate_booking_link` → `find_hotel_by_name("Je confirme")` en erreur → gabarit `_NEEDS_SELECTION_NO_LIST` (`templates.py:364-367`) | Le triage ne voit jamais la question de l'assistant (`dialogue_context.py`). Le routage ne renvoie une demande en attente vers la recherche que si `family == "ack"` (`b2c_concierge/agent.py:1307-1314`) | **Non** (lu dans le code) : sur `main`, une `booking` passe devant et `pending_search` est jetée. Depuis PORT1 (#137), le triage reçoit la dernière question posée (`previous_question`), mais seul le budget s'en sert ; la priorité de routage est inchangée |

**Défaut latent (prouvé hors ligne).** `select_us_postal_anchor` (`geo_guards.py:458`) prend tout code postal français pour un ZIP américain : `75009` et `13001` donnent `PostalAnchor(value='75009', reason='single_candidate')`. `geocode_tool.py:671-675` force alors `country_code="US"` dès que le modèle n'a pas mis de pays. « 2 boulevard Poissonnière 75009 Paris » peut donc être cherché aux États-Unis.

**Autre constat.** Toutes les traces portent `locale:"en", currency:"USD"` pour un testeur français. La question du géocodeur sort en anglais, et seule la synthèse la remet en français. Demander à Raphael l'URL de test.

## 2. Lecture : trois défauts de structure, pas six bugs

1. **Le contrat d'extraction du lieu est trop pauvre.** Il tient en deux chaînes libres (`city`, `zone`) et un prompt d'exceptions. Une adresse, un code postal, une ville écrite dans le nom d'un lieu n'y ont pas de place : le LLM les tasse, les jette ou les déplace. Chaque incident a ajouté une exception au prompt ou une regex (`fc5cbd9`, ZIP US).
2. **La question de clarification n'appartient à personne.** Le code la produit sans option. La synthèse la réécrit et invente des options. Le tour suivant la retrouve par regex dans la paraphrase, et le triage ne la voit pas.
3. **L'affichage ignore la langue de la conversation** (créneau).

## 3. Suite

Le plan exécutable (décisions tranchées, tâches, prérequis, critères) est dans [`README.md`](README.md) et les fichiers `Q01-…` à `Q13-…`.
