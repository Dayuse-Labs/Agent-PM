# PROGRESS — qa14707

| ID  | Title                                                                                    | Phase | Batch | Depends on | Model  | Status | Attempts | Branch   | Tokens est. / actual  |
|-----|------------------------------------------------------------------------------------------|-------|-------|------------|--------|--------|----------|----------|-----------------------|
| Q01 | Proof bench — QA14707 eval set, evaluators and multi-turn replay                         | 1     | 1A    | —          | sonnet | merged | 1        | task/Q01 | 2.7M / see /workflows |
| Q02 | Time slot in the language of the conversation                                            | 1     | 1B    | —          | sonnet | merged | 2        | task/Q02 | 0.8M / see /workflows |
| Q03 | `Clarification` contract and structured emission by the leaf                             | 2     | 2A    | —          | opus   | merged | 2        | task/Q03 | 3.1M / see /workflows |
| Q04 | Concierge: clarification rendered by template, persistent state, anti-loop on the state  | 2     | 2B    | Q03        | opus   | merged | 1        | task/Q04 | 4.7M / see /workflows |
| Q05 | Routing: the answer to the question goes before the booking                              | 2     | 2C    | Q04        | opus   | merged | 1        | task/Q05 | 4.1M / see /workflows |
| Q14 | A chosen homonym option reaches the leaf with its region                                 | 3     | 3C    | Q07, Q08   | opus   | merged | 1        | task/Q14 | 3.2M / see /workflows |
| Q06 | `GeoIntent` v1.1 contract and offline ADK proof                                          | 2     | 2A    | —          | opus   | merged | 1        | task/Q06 | 2.0M / see /workflows |
| Q07 | The leaf extracts the place into a `GeoIntent`                                           | 3     | 3A    | Q06        | opus   | merged | 1        | task/Q07 | 4.7M / see /workflows |
| Q15 | Seam: the leaf reads the user's own words apart from the concierge's context             | 3     | 3B    | Q07        | sonnet | merged | 1        | task/Q15 | 0.8M / see /workflows |
| Q08 | Address and postcode resolved by the geocoder                                            | 3     | 3B    | Q07        | opus   | merged | 1        | task/Q08 | 3.1M / see /workflows |
| Q16 | The market's country reaches the leaf's postcode tie-break                               | 3     | 3D    | Q14        | opus   | merged | 1        | task/Q16 | 2.0M / see /workflows |
| Q17 | A malformed GeoIntent field no longer voids the whole intent                             | 3     | 3E    | Q16        | opus   | todo   | 1        | —        | 1.6M / —              |
| Q18 | A place survives an added article or a corrected typo in its mention                     | 3     | 3F    | Q17        | sonnet | todo   | 0        | —        | 1.2M / —              |
| Q19 | A carried country is a hard filter only for the city it was carried with                 | 3     | 3G    | Q18        | sonnet | todo   | 0        | —        | 1.2M / —              |
| Q20 | A street or an address without a postcode is resolved by the address lookup              | 3     | 3H    | Q19        | opus   | todo   | 0        | —        | 2.6M / —              |
| Q21 | A homonym option picked by the user is resolved without the reply's state in the query   | 3     | 3I    | Q20        | opus   | todo   | 0        | —        | 1.6M / —              |
| Q22 | A named hotel not found in a named city falls back to that city's search in code         | 3     | 3J    | Q21        | opus   | todo   | 0        | —        | 1.6M / —              |
| Q23 | GeoIntent asks the place's city and country right after its name (production leaf model) | 3     | 3K    | Q22        | opus   | todo   | 0        | —        | 2.3M / —              |
| Q24 | `hotels_within_km` no longer passes on an empty hotel list                               | 3     | 3E    | —          | sonnet | merged | 2        | task/Q24 | 0.8M / see /workflows |
| Q09 | Removal: city rescue by preposition, `pending_place` text matching                       | 4     | 4A    | Q08, Q15   | sonnet | todo   | 0        | —        | 1.6M / —              |
| Q10 | Removal: US ZIP by regex (S-L7f)                                                         | 4     | 4B    | Q09, Q16   | sonnet | todo   | 0        | —        | 1.6M / —              |
| Q11 | Removal: question extracted by regex and yes/no by word list, on the clarification route | 4     | 4B    | Q09, Q15   | sonnet | todo   | 0        | —        | 2.3M / —              |
| Q12 | Documentation: HANDOFF, CHANTIERS, S-L plan                                              | 5     | 5A    | —          | sonnet | todo   | 0        | —        | 1.6M / —              |
| Q13 | Global review (read-only)                                                                | 5     | 5B    | Q12        | opus   | todo   | 0        | —        | 2.6M / —              |

Statuses: todo · added · merged · blocked · failed · needs-human · cancelled
