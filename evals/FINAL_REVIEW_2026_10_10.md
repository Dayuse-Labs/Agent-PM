# Dernière revue — 10 octobre 2026

**PR finalisée pour revue équipe. Le candidat est mieux noté sur le corpus historique évalué; la supériorité générale en production reste non démontrée.** Le critère demandé est un gain par rapport à la prod, sans attendre la disparition de tous les défauts. Les notes et les limites du [comparatif complet](PRODUCTION_PARITY_2026_10_10.md) restent inchangées. Cette décision concerne la revue de la PR, pas une autorisation de bascule générale.

- Sur 100 parcours multi-tours : **73 A/B contre 48 en prod**, 43 mieux notés, 14 moins bien, 43 identiques. Aucun D/F candidat dans cette revue, contre 8 D côté legacy. Les 27 C restent des défauts significatifs.
- Les 14 parcours moins bien notés ont été relus intégralement dans les deux branches : 11 C et 3 B côté candidat. Les problèmes concernent surtout les clarifications, le contexte géographique et les adresses. Aucun nouveau défaut majeur identifié dans cette dernière relecture; pas de changement de notes pour faciliter la livraison.
- **84/280 réponses candidat contiennent des cartes, contre 142/280 en prod.** Le candidat montre 299 occurrences de cartes : 298 offres datées reliées aux reçus MCP, plus une carte d’identité hôtel sans disponibilité confirmée. La prod en montre 603. Cette différence doit rester visible : les notes de dialogue ne démontrent pas un meilleur rappel de l’inventaire. Export/Qdrant contre MCP, fraîcheur différente et clarifications contribuent au décalage; leurs effets ne sont pas isolés.
- Le complément adaptatif, séparé du score des 100 parcours, reste à 3 B/1 C candidat contre 1 B/3 C legacy. L’adresse composite madrilène reste un échec.

## Vérification finale

Aucun changement de runtime depuis `315377106070e11390a84c3236993ce0d5177026` : 85 empreintes sources vérifiées. B2C main refetché, toujours `cbe88b9963f28fbea932ac2a6ce23d22112f2b76`. Les 200 fichiers sources des revues candidat et legacy ont été revérifiés. Pas de nouvelle campagne payante ni nouvelle comparaison live dans cette dernière passe.

La suite complète locale termine avec **3304 tests réussis et 2 ignorés**. Le contrat JavaScript, ignoré faute de Node dans le PATH du shell, a ensuite été exécuté avec Node disponible : **1 test supplémentaire réussi**. Bilan : **3305 tests vérifiés, seul le test Langfuse live payant optionnel non exécuté**. Ruff, mypy (85 sources), guardrails et diff passent. Ce n’est pas une exécution CI distante : le dernier job GitHub ne démarre pas pour un problème de paiement/plafond du compte; l’état du commit livré est référencé dans la PR.

## Passage à la revue et préparation de la bascule

La nouvelle architecture est préservée : concierge propriétaire du profil Redis, feuilles A2A sans état, LiteLLM et MCP en lecture seule. Aucune nouvelle regex ni table d’alias géographiques. FAQ/SAV restent en phase 2.

Avant merge et trafic, la revue humaine de Fabien prévue par le dépôt reste nécessaire, ainsi que le rétablissement de la CI. La configuration évaluée doit être explicitement reprise ou réévaluée : triage GPT-5.2, reasoning low, 2048 tokens, timeout 15 s; recherche 4o-mini; synthèse GPT-5.2. Le triage B2C actuellement déployé reste 4o-mini : merger le code ne reproduit pas à lui seul le candidat évalué. Les 27 C, la fréquence de résultats et les réponses sur l’accès aux équipements sont à considérer lors de la décision de trafic.

**Coût supplémentaire de cette passe : 0 USD.** Cumul inchangé : 224.871435847648 / 230 USD, dont 7.10 USD de provisions antérieures. Aucun merge, déploiement ou changement Railway. Aucun travail payant en cours; services de rejeu arrêtés.
