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
 "position":1, "targets":[{"kind":"city|region|neighborhood|landmark|address|hotel",
 "query":"place name only", "country":"ISO2", "evidence":"exact current place quote",
 "scope":"nearby|inside", "region":"optional verbatim containing state/province",
 "code":"optional explicitly stated administrative code"}]}
Omit unused fields. Preserve/missing/device/select have NO targets. Select is
only a choice of one of LOCATION CONTEXT.options, never a hotel or multiple places.
Preserve means there is NO geographic update. A new airport/address within the
same city is change, not preserve. Refine with parent_city means the user supplies
the containing city for the EXISTING named hotel, landmark, address or neighborhoods;
retain the old target, do NOT put the parent city in targets. If LOCATION CONTEXT
requested_destination.kind is landmarks, those are ALL accepted alternatives.
A city answering their containing-city question refines ALL of them using
parent_city and no targets. It does not replace them with a bare city search.
An explicit request to switch to a new destination still uses change.
Correct with targets
repairs the SAME intended place and retains its previous parent. Change replaces it.
A bare city answering your location question is search, never a social acknowledgement.
Use change with one target for a new destination. Multiple targets are ONLY
alternative destinations the customer accepts, never the components of an address.
A city followed by a state/province/country is ONE target: city in query, verbatim
state/province in region, geographic country hint in country. Never make the
containing state a second destination. A corridor BETWEEN places is not their union;
use unknown and ask for a central location if the corridor cannot be represented.
For a neighborhood/landmark with its containing city stated in MESSAGE, parent_city
is required and targets contains only the neighborhood/landmark, not that city.
For a new landmark within the confirmed city, retain that confirmed parent_city
unless the user states another city. Do not ask again for an already confirmed parent.
A city is a municipality; a region is a state/county/province; a neighborhood is a
sub-city district. Never label a neighborhood as a state or county. An airport,
station or standalone postcode is a landmark, not an administrative region.
A numbered street address uses address kind. Keep its full literal street number,
street, city, state and postcode together in query; never convert it to a landmark
or split it into alternative destinations. A complete address does not require
an additional parent_city to be resolved. If the address is questioned, a city-only
answer refines it; a replacement street address uses correct with address kind.
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
country is a soft geographic hint, not a claim of user confirmation: use geographic
knowledge of the named place/region when clear; the provider will verify it. If
uncertain, omit it. Never infer a destination country from language or locale.
'''


def adapt_location_update(data: dict[str, Any], message: str, context: dict | None) -> dict[str, Any]:
    """Translate a single transaction; malformed transactions cannot mutate place."""
    if 'location_update' not in data:
        return data
    result = {**data, 'requested_landmark': None, 'requested_areas': None,
              'requested_subarea': None, 'hotel_name': None, 'requested_landmarks': None,
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
        kind, query = target.get('kind'), target.get('query')
        # The transaction already carries a literal quote. Requiring the model
        # to repeat it for every target discards otherwise grounded destinations.
        # An explicitly supplied invalid quote still fails validation below.
        quote = target.get('evidence', evidence)
        if kind not in {'city', 'region', 'neighborhood', 'landmark', 'address', 'hotel'}:
            return result
        if (not isinstance(query, str) or not query.strip() or len(query) > 200
                or not isinstance(quote, str) or not quote.strip() or quote not in message
                or not area_name_in_text(query, quote)):
            return result
        country = target.get('country')
        if country is not None and (not isinstance(country, str) or len(country) != 2
                                   or not country.isascii() or not country.isalpha()):
            return result
        region = target.get('region')
        if region is not None and (not isinstance(region, str) or not region.strip()
                                   or not area_name_in_text(region, message)):
            # Optional model knowledge is not a user constraint. Discard it
            # without discarding the independently grounded destination name.
            region = None
        scope = target.get('scope', 'nearby' if kind == 'city' else 'inside')
        if scope not in {'nearby', 'inside'}:
            return result
        clean.append({**target, 'query': query.strip(), 'evidence': quote,
                      'country': country.upper() if country else None,
                      'region': region, 'scope': scope})
    result['location_intent'] = {'action': action, 'evidence': evidence}
    if len(clean) == 1 and clean[0]['kind'] == 'hotel':
        result['hotel_name'] = clean[0]['query']
        return result
    if len(clean) == 1 and (clean[0]['kind'] in {'landmark', 'address'} or
                           (clean[0]['kind'] == 'neighborhood' and clean[0]['scope'] == 'nearby')):
        target = clean[0]
        parent = raw.get('parent_city')
        if not isinstance(parent, str) or not area_name_in_text(parent, message):
            confirmed = (context or {}).get('confirmed_city')
            parent = confirmed if isinstance(confirmed, str) and (
                raw.get('parent_city') == confirmed or area_name_in_text(confirmed, message)
                or action in {'correct', 'refine'}) else None
        result['requested_landmark'] = {'query': target['query'], 'city': parent,
                                       'country_guess': target['country'], 'evidence': target['evidence'],
                                       **({'kind': 'address'} if target['kind'] == 'address' else {})}
        return result
    if len(clean) > 1 and all(t['kind'] == 'landmark' for t in clean):
        parent = raw.get('parent_city')
        if not isinstance(parent, str) or not area_name_in_text(parent, message):
            parent = None
        result['requested_landmarks'] = [
            {'query': t['query'], 'city': parent, 'country_guess': t['country']}
            for t in clean
        ]
        return result
    if any(t['kind'] not in {'city', 'region', 'neighborhood'} for t in clean):
        # An unsupported combination must not authorize an unrelated leaf search.
        result['location_intent'] = {'action': 'unknown', 'kind': 'none'}
        return result
    parent = raw.get('parent_city')
    if (isinstance(parent, str) and area_name_in_text(parent, message)
            and all(t['kind'] == 'neighborhood' for t in clean)):
        result['requested_areas'] = [
            {'query': parent, 'kind': 'municipality', 'country': t['country'] or '',
             'evidence': parent, 'subarea': t['query']} for t in clean
        ]
        return result
    result['requested_areas'] = [
        {'query': t['query'], 'kind': {'city': 'municipality', 'region': 'administrative', 'neighborhood': 'neighborhood'}[t['kind']],
         'country': t['country'] or '', 'evidence': t['evidence'],
         **({'boundary_evidence': evidence} if t['kind'] == 'city' and t['scope'] == 'inside' else {}),
         **({'code': t['code']} if t.get('code') else {}),
         **({'region': t['region']} if t.get('region') else {})}
        for t in clean
    ]
    return result
