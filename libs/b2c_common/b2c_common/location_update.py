"""One grounded destination transaction, adapted to the existing profile reducer.

The model describes intent once. Coordinates, identity and membership remain
provider-owned; this adapter never parses destination intent from prose.
Legacy callers can keep their old extraction fields until they migrate.
"""
from __future__ import annotations

from typing import Any
from .search_areas import area_name_in_text

LOCATION_UPDATE_INSTRUCTION = '''
Destination changes use ONLY location_update (do not also emit location_intent,
requested_landmark, requested_areas or requested_subarea):
{"action":"preserve|change|refine|correct|device|select|missing|unknown",
 "evidence":"exact current message quote", "parent_city":"optional exact containing city",
 "position":1, "targets":[{"kind":"city|region|neighborhood|landmark|hotel",
 "query":"place name only", "country":"ISO2", "evidence":"exact current place quote",
 "scope":"nearby|inside", "code":"optional explicitly stated administrative code"}]}
Omit unused fields. Preserve/missing/device/select have NO targets. Select is
only a choice of one of LOCATION CONTEXT.options, never a hotel or multiple places.
Preserve means there is NO geographic update. A new airport/address within the
same city is change, not preserve. Refine with parent_city means the user supplies
the containing city for the EXISTING named hotel, landmark, address or neighborhoods;
retain the old target, do NOT put the parent city in targets. Correct with targets
repairs the SAME intended place and retains its previous parent. Change replaces it.
A bare city answering your location question is search, never a social acknowledgement.
Use change with one target for a new destination; up to three targets are alternatives.
A city is a municipality; a region is a state/county/province; a neighborhood is a
sub-city district. Never label a neighborhood as a state or county. An airport,
station, street address or postcode is a landmark, not an administrative region.
Keep airport codes, terminals and street numbers in query. A hotel uses hotel kind.
Query contains the actual named place only, excluding words meaning nearby,
surroundings or instead. Copy its spelling from MESSAGE; the provider resolves it.
For a city, nearby is the default unless city limits are required. For a neighborhood,
inside means results must belong to it, nearby explicitly allows adjacent places.
A region is always inside; do not silently reduce it to a city. An ordinary city
or neighborhood name is not a request for another confirmation when unambiguous.
Countries/parent cities supplied later refine the outstanding specific destination.
Negative locations are NEVER targets: retain the requested location when the user
says the proposed results are in the wrong place. Use unknown if the positive target
cannot be recovered from context. Do not infer coordinates, travel times or radii.
If the country is unknown, omit it; do not invent a country from language or locale.
'''


def adapt_location_update(data: dict[str, Any], message: str, context: dict | None) -> dict[str, Any]:
    """Translate a single transaction; malformed transactions cannot mutate place."""
    if 'location_update' not in data:
        return data
    result = {**data, 'requested_landmark': None, 'requested_areas': None,
              'requested_subarea': None, 'hotel_name': None,
              'location_intent': {'action': 'unknown', 'kind': 'none'}}
    raw = data['location_update']
    if not isinstance(raw, dict):
        return result
    action, evidence = raw.get('action'), raw.get('evidence')
    if action not in {'preserve', 'change', 'refine', 'correct', 'device', 'select', 'missing', 'unknown'}:
        return result
    if action != 'preserve' and (not isinstance(evidence, str) or not evidence.strip() or evidence not in message):
        return result
    targets = raw.get('targets')
    if action in {'preserve', 'device', 'select', 'missing', 'unknown'}:
        if targets:
            return result  # A contradictory transaction is not a silent no-op.
        result['location_intent'] = {k: raw[k] for k in ('action', 'evidence', 'position') if k in raw}
        return result
    if action == 'refine' and not targets:
        parent = raw.get('parent_city')
        if isinstance(parent, str) and parent.strip() and area_name_in_text(parent, message):
            result['location_intent'] = {'action': 'refine', 'parent_city': parent, 'evidence': evidence}
        return result
    if not isinstance(targets, list) or not 1 <= len(targets) <= 3:
        return result
    clean = []
    for target in targets:
        if not isinstance(target, dict):
            return result
        kind, query, quote = target.get('kind'), target.get('query'), target.get('evidence')
        if kind not in {'city', 'region', 'neighborhood', 'landmark', 'hotel'}:
            return result
        if (not isinstance(query, str) or not query.strip() or len(query) > 200
                or not isinstance(quote, str) or not quote.strip() or quote not in message
                or not area_name_in_text(query, quote)):
            return result
        country = target.get('country')
        if country is not None and (not isinstance(country, str) or len(country) != 2
                                   or not country.isascii() or not country.isalpha()):
            return result
        scope = target.get('scope', 'nearby' if kind == 'city' else 'inside')
        if scope not in {'nearby', 'inside'}:
            return result
        clean.append({**target, 'query': query.strip(), 'country': country.upper() if country else None, 'scope': scope})
    result['location_intent'] = {'action': action, 'evidence': evidence}
    if len(clean) == 1 and clean[0]['kind'] == 'hotel':
        result['hotel_name'] = clean[0]['query']
        return result
    if len(clean) == 1 and (clean[0]['kind'] == 'landmark' or
                           (clean[0]['kind'] == 'neighborhood' and clean[0]['scope'] == 'nearby')):
        target = clean[0]
        parent = raw.get('parent_city')
        if not isinstance(parent, str) or not area_name_in_text(parent, message):
            confirmed = (context or {}).get('confirmed_city')
            parent = confirmed if isinstance(confirmed, str) and (
                raw.get('parent_city') == confirmed or area_name_in_text(confirmed, message)
                or action in {'correct', 'refine'}) else None
        result['requested_landmark'] = {'query': target['query'], 'city': parent,
                                       'country_guess': target['country'], 'evidence': target['evidence']}
        return result
    if any(t['kind'] not in {'city', 'region', 'neighborhood'} for t in clean):
        # Mixed incompatible target kinds need clarification.
        return result
    result['requested_areas'] = [
        {'query': t['query'], 'kind': {'city': 'municipality', 'region': 'administrative', 'neighborhood': 'neighborhood'}[t['kind']],
         'country': t['country'] or '', 'evidence': t['evidence'],
         **({'boundary_evidence': evidence} if t['kind'] == 'city' and t['scope'] == 'inside' else {}),
         **({'code': t['code']} if t.get('code') else {})}
        for t in clean
    ]
    return result
