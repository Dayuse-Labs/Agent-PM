"""One grounded destination transaction, adapted to the existing profile reducer.

The model describes intent once. Coordinates, identity and membership remain
provider-owned; this adapter never parses destination intent from prose.
Legacy callers can keep their old extraction fields until they migrate.
"""
from __future__ import annotations

from typing import Any
from .search_areas import MAX_AREAS, area_name_in_text

LOCATION_UPDATE_INSTRUCTION = '''
Destination changes use ONLY location_update (do not also emit location_intent,
requested_landmark, requested_areas or requested_subarea):
{"action":"preserve|change|refine|correct|device|select|missing|unknown",
 "evidence":"exact current message quote", "parent_city":"optional exact containing city",
 "position":1, "targets":[{"kind":"city|region|neighborhood|landmark|address|postcode|hotel",
 "query":"place name only", "country":"ISO2", "evidence":"exact current place quote",
 "scope":"nearby|inside", "region":"optional verbatim containing state/province",
 "region_scope":"context|inside",
 "code":"optional explicitly stated administrative code"}]}
Omit unused fields. Preserve/missing/device/select have NO targets. Select is
only a choice of one of LOCATION CONTEXT.options, never a hotel or multiple places.
For action=select, position is REQUIRED: the integer 1-based position in those
options. For example, a first-option reply emits action=select, position=1 and
its literal evidence. Never omit position or put it in hotel pick_position.
If those options are places, "tell me about the first option" selects that
place with family=search; it is not a hotel-details lookup.
Preserve means there is NO geographic update. A new airport/address within the
same city is change, not preserve. Refine with parent_city means the user supplies
the containing city for the EXISTING named hotel, landmark, address or neighborhoods;
retain the old target (including a postal district), do NOT put the parent city in targets. If LOCATION CONTEXT
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
For a new landmark or neighborhood within the confirmed city, retain that confirmed parent_city
unless the user states another city. Do not ask again for an already confirmed parent.
A city is a municipality; a region is a state/county/province; a neighborhood is a
sub-city district. Never label a neighborhood as a state or county. An airport,
station is a landmark, not an administrative region. A standalone postal code
uses postcode kind (including a postal district). Keep the code in query, and
any stated city in parent_city. Postal lookup uses the provider postcode type,
not a city or POI. Default scope is nearby; it locates the postal centroid,
not a promise of membership in a postal boundary.
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
A region is always inside; do not silently reduce it to a city.
When results must remain in a containing department/state, use region_scope=inside
alongside its literal region. Nearby a city within that region still requires
membership in the region. A region used only to disambiguate a city uses context.
A short postal district is still an explicit location, even when it is not a
complete delivery postcode. Retain its literal token as a postcode target when
asking for its containing city; omit an uncertain country instead of omitting
the target. A request for "cheapest" does not erase the location alongside it.
Never infer missing postcode digits or replace the district with its city. An ordinary city
or neighborhood name is not a request for another confirmation when unambiguous.
Countries/parent cities supplied later refine the outstanding specific destination.
Negative locations are NEVER targets: retain the requested location when the user
says the proposed results are in the wrong place. Use unknown if the positive target
cannot be recovered from context. Do not infer coordinates, travel times or radii.
country is a soft geographic hint, not a claim of user confirmation: use geographic
knowledge of the named place/region when clear; the provider will verify it. If
uncertain, omit it. Never infer a destination country from language or locale.
When LOCATION CONTEXT has pending_clarification.kind=location, the last question
asked for a place. Interpret a numeric reply in that scope, not as a budget or
hotel selection. If its geographic identity is unclear, use unknown; never
invent coordinates, a containing city, or an administrative name to force a match.
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
        # Preserving the search area does not discard a separately named
        # property whose facts the customer requests. Search/booking intent
        # still requires a destination transaction; details grant read only.
        name = data.get('hotel_name')
        if (action == 'preserve' and data.get('family') == 'details'
                and isinstance(name, str) and name.strip() and len(name) <= 200
                and area_name_in_text(name, message)):
            result['hotel_name'] = name.strip()
        return result
    if action == 'refine' and not targets:
        parent = raw.get('parent_city')
        if isinstance(parent, str) and parent.strip() and area_name_in_text(parent, message):
            result['location_intent'] = {'action': 'refine', 'parent_city': parent, 'evidence': evidence}
        return result
    if not isinstance(targets, list) or not 1 <= len(targets) <= MAX_AREAS:
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
        if kind not in {'city', 'region', 'neighborhood', 'landmark', 'address', 'postcode', 'hotel'}:
            return result
        if (not isinstance(query, str) or not query.strip() or len(query) > 200
                or not isinstance(quote, str) or not quote.strip() or quote not in message):
            return result
        if not area_name_in_text(query, quote):
            if 'evidence' not in target or len(quote) > 200:
                return result
            # The literal mention is the source of destination identity. A
            # canonical model label (abbreviation expansion, translation or
            # typo correction) never replaces it. Provider validation remains
            # mandatory; the quote itself grants no coordinates or boundary.
            query = quote
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
        scope = target.get('scope', 'nearby' if kind in {'city', 'postcode'} else 'inside')
        if scope not in {'nearby', 'inside'}:
            return result
        if kind == 'postcode' and scope == 'inside':
            return result  # Exact postal-boundary membership is not this point lookup.
        clean.append({**target, 'query': query.strip(), 'evidence': quote,
                      'country': country.upper() if country else None,
                      'region': region, 'scope': scope})
        # A model may supply an administrative code from its knowledge or
        # earlier context alongside a currently named place. That optional
        # hint is not a new user constraint. Retain the independently quoted
        # name and let the provider verify it; literal codes still go through
        # validate_areas' mandatory provider-code matching contract.
        code = target.get('code')
        if (isinstance(code, str) and code.strip()
                and not area_name_in_text(code, message)
                and not query.strip().isdigit()):
            clean[-1].pop('code', None)
    # A parent may be repeated as a target by extraction. Collapse it ONLY
    # when the structured relations explicitly identify that same city as the
    # parent of every other target. Merely listing a city beside a POI does not
    # authorize dropping an accepted alternative.
    cities = [t for t in clean if t['kind'] == 'city']
    dependents = [t for t in clean if t['kind'] in {'landmark', 'neighborhood', 'address', 'postcode'}]
    if len(cities) == 1 and len(dependents) == len(clean) - 1 and dependents:
        city = cities[0]['query']
        if all(isinstance(parent := t.get('parent_city', raw.get('parent_city')), str)
               and parent.strip().casefold() == city.casefold()
               for t in dependents):
            clean = dependents
            raw = {**raw, 'parent_city': city}
    result['location_intent'] = {'action': action, 'evidence': evidence}
    previous = (context or {}).get('requested_destination') or {}
    if not isinstance(previous, dict):
        previous = {}
    if (action == 'change' and len(clean) == 1 and clean[0]['kind'] == 'city'
            and previous.get('kind') == 'postcode'
            and (((context or {}).get('pending_clarification') or {}).get('kind') == 'location'
                 or str((context or {}).get('confirmed_city') or '').casefold() == clean[0]['query'].casefold())
            and area_name_in_text(message.strip(), clean[0]['query'])):
        # A bare city answering the owned postcode-context question, or naming
        # its verified parent, cannot erase the district. Explicit switching
        # phrases fail the whole-message equality test and retain change.
        result['location_intent'] = {'action': 'refine', 'parent_city': clean[0]['query'], 'evidence': evidence}
        return result
    if len(clean) == 1 and clean[0]['kind'] == 'hotel':
        result['hotel_name'] = clean[0]['query']
        return result
    if len(clean) == 1 and (clean[0]['kind'] in {'landmark', 'address', 'postcode'} or
                           (clean[0]['kind'] == 'neighborhood' and clean[0]['scope'] == 'nearby')):
        target = clean[0]
        parent = target.get('parent_city', raw.get('parent_city'))
        if not isinstance(parent, str) or not area_name_in_text(parent, message):
            confirmed = (context or {}).get('confirmed_city')
            parent = confirmed if isinstance(confirmed, str) and (
                raw.get('parent_city') == confirmed or area_name_in_text(confirmed, message)
                or action in {'correct', 'refine'}) else None
        result['requested_landmark'] = {'query': target['query'], 'city': parent,
                                       'country_guess': target['country'], 'evidence': target['evidence'],
                                       **({'kind': target['kind']} if target['kind'] in {'address', 'postcode'} else {})}
        return result
    if len(clean) > 3 and any(t['kind'] not in {'city', 'region', 'neighborhood'} for t in clean):
        result['location_intent'] = {'action': 'unknown', 'kind': 'none'}
        return result
    if len(clean) > 1 and all(t['kind'] == 'landmark' for t in clean):
        parent = raw.get('parent_city')
        if not isinstance(parent, str) or not area_name_in_text(parent, message):
            parent = None
        result['requested_landmarks'] = [
            {'query': t['query'], 'city': (t['parent_city'] if isinstance(t.get('parent_city'), str)
                and area_name_in_text(t['parent_city'], message) else parent),
             'country_guess': t['country']}
            for t in clean
        ]
        return result
    if any(t['kind'] not in {'city', 'region', 'neighborhood'} for t in clean):
        # An unsupported combination must not authorize an unrelated leaf search.
        result['location_intent'] = {'action': 'unknown', 'kind': 'none'}
        return result
    result['requested_areas'] = [
        {'query': t['query'], 'kind': {'city': 'municipality', 'region': 'administrative', 'neighborhood': 'neighborhood'}[t['kind']],
         'country': t['country'] or '', 'evidence': t['evidence'],
         **({'boundary_evidence': evidence} if t['kind'] == 'city' and t['scope'] == 'inside' else {}),
         **({'code': t['code']} if t.get('code') else {}),
         **({'region': t['region']} if t.get('region') else {}),
         **({'required_region': t['region']} if t.get('region') and (
             t.get('region_scope') == 'inside' or any(
                 old.get('kind') == 'administrative' and old.get('query', '').casefold() == t['region'].casefold()
                 for old in previous.get('areas') or [])) else {})}
        for t in clean
    ]
    # Parent placement is transport syntax, not a geographic decision. A
    # target-local parent and the transaction parent carry the same grounded
    # relation. Retain each independently, including mixed alternative areas.
    confirmed_parent = (context or {}).get('confirmed_city')
    for target, area in zip(clean, result['requested_areas'], strict=True):
        parent = target.get('parent_city', raw.get('parent_city'))
        if (target['kind'] == 'neighborhood' and isinstance(parent, str)
                and parent.strip() and (area_name_in_text(parent, message) or (
                    isinstance(confirmed_parent, str)
                    and parent.strip().casefold() == confirmed_parent.strip().casefold()))):
            area.update(query=parent.strip(), kind='municipality',
                        evidence=parent.strip() if area_name_in_text(parent, message) else target['evidence'],
                        subarea=target['query'])
    return result
