# PROGRESS — qa14707

| ID  | Title                                                                                    | Phase | Batch | Depends on | Model  | Status      | Attempts | Branch   | Tokens est. / actual  |
|-----|------------------------------------------------------------------------------------------|-------|-------|------------|--------|-------------|----------|----------|-----------------------|
| Q01 | Proof bench — QA14707 eval set, evaluators and multi-turn replay                         | 1     | 1A    | —          | sonnet | merged      | 1        | task/Q01 | 2.7M / see /workflows |
| Q02 | Time slot in the language of the conversation                                            | 1     | 1B    | —          | sonnet | merged      | 2        | task/Q02 | 0.8M / see /workflows |
| Q03 | `Clarification` contract and structured emission by the leaf                             | 2     | 2A    | —          | opus   | merged      | 2        | task/Q03 | 3.1M / see /workflows |
| Q04 | Concierge: clarification rendered by template, persistent state, anti-loop on the state  | 2     | 2B    | Q03        | opus   | merged      | 1        | task/Q04 | 4.7M / see /workflows |
| Q05 | Routing: the answer to the question goes before the booking                              | 2     | 2C    | Q04        | opus   | merged      | 1        | task/Q05 | 4.1M / see /workflows |
| Q14 | A chosen homonym option reaches the leaf with its region                                 | 3     | 3C    | Q07, Q08   | opus   | added       | 0        | —        | 2.5M / —              |
| Q06 | `GeoIntent` v1.1 contract and offline ADK proof                                          | 2     | 2A    | —          | opus   | merged      | 1        | task/Q06 | 2.0M / see /workflows |
| Q07 | The leaf extracts the place into a `GeoIntent`                                           | 3     | 3A    | Q06        | opus   | needs-human | 1        | task/Q07 | 4.7M / see /workflows |
| Q15 | Seam: the leaf reads the user's own words apart from the concierge's context             | 3     | 3B    | Q07        | sonnet | added       | 0        | —        | 0.8M / —              |
| Q08 | Address and postcode resolved by the geocoder                                            | 3     | 3B    | Q07        | opus   | todo        | 0        | —        | 3.1M / —              |
| Q09 | Removal: city rescue by preposition, `pending_place` text matching                       | 4     | 4A    | Q08, Q15   | sonnet | todo        | 0        | —        | 1.6M / —              |
| Q10 | Removal: US ZIP by regex (S-L7f)                                                         | 4     | 4B    | Q09        | sonnet | todo        | 0        | —        | 1.6M / —              |
| Q11 | Removal: question extracted by regex and yes/no by word list, on the clarification route | 4     | 4B    | Q09, Q15   | sonnet | todo        | 0        | —        | 2.3M / —              |
| Q12 | Documentation: HANDOFF, CHANTIERS, S-L plan                                              | 5     | 5A    | —          | sonnet | todo        | 0        | —        | 1.6M / —              |
| Q13 | Global review (read-only)                                                                | 5     | 5B    | Q12        | opus   | todo        | 0        | —        | 2.6M / —              |

Statuses: todo · added · merged · blocked · failed · needs-human · cancelled
