"""Finite common catalogue for controlled legacy/AgentB2C comparisons.

Not a replacement MCP implementation or a production export. Search-only,
EUR, one captured day; unsupported dimensions fail explicitly. Provider offers
are kept verbatim. Legacy imports are lazy so the new repo needs no old runtime.
"""
from __future__ import annotations

import copy
import json
import math
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any


def distance_km(lat: float, lon: float, other_lat: float, other_lon: float) -> float:
    a, b = math.radians(lat), math.radians(other_lat)
    delta_lat = b - a
    delta_lon = math.radians(other_lon - lon)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(delta_lon / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(value)))


def folded(value: str) -> str:
    return ' '.join(value.casefold().replace('-', ' ').split())


def available(offer: dict[str, Any], now: datetime | None = None) -> bool:
    deadline = offer.get('cutoffDeadlineUtc')
    if not deadline:
        return True
    return datetime.fromisoformat(deadline.replace('Z', '+00:00')) > (now or datetime.now(UTC))


class UnsupportedDimension(ValueError):
    """A control must not silently invent facts absent from the snapshot."""


class CommonInventory:
    def __init__(self, snapshot: dict[str, Any]):
        self.snapshot = copy.deepcopy(snapshot)
        self.day = snapshot['date']
        self.rows = snapshot['hotels']
        assert len({r['provider']['hotelId'] for r in self.rows}) == len(self.rows)
        for row in self.rows:
            for offer in row['provider']['offers']:
                assert offer['availabilityDate'][:10] == self.day
                assert isinstance(offer['priceEuroWithBookingFees'], (int, float))

    @classmethod
    def read(cls, path: Path) -> CommonInventory:
        return cls(json.loads(path.read_text()))

    def search(self, args: dict[str, Any]) -> dict[str, Any]:
        if args['date'] != self.day:
            raise UnsupportedDimension('date outside captured inventory')
        for key in ('hotelEquipmentIds', 'roomEquipmentIds', 'addonCategoryIds'):
            if args.get(key):
                raise UnsupportedDimension('snapshot does not establish equipment/add-on membership')
        results = []
        for row in self.rows:
            hotel = row['provider']
            distance = distance_km(args['lat'], args['lon'], hotel['lat'], hotel['lon'])
            if distance > args.get('radiusKm', 20):
                continue
            if args.get('starRatings') and hotel.get('starRating') not in args['starRatings']:
                continue
            offers = []
            for offer in hotel['offers']:
                if not available(offer):
                    continue
                price = offer['priceEuroWithBookingFees'] / 100
                if price < args.get('priceRangeMin', 0) or price > args.get('priceRangeMax', math.inf):
                    continue
                window = args.get('timeSlot', {})
                start = offer['startHour'] * 60 + offer.get('startMinute', 0)
                end = offer['endHour'] * 60 + offer.get('endMinute', 0)
                if end <= start:
                    raise UnsupportedDimension('cross-midnight window semantics outside this control')
                if end <= window.get('startHour', 0) * 60 or start >= window.get('endHour', 23) * 60:
                    continue
                if any(args.get(key, 0) > (offer.get(field) or 0)
                       for key, field in [('adults', 'capacity'), ('children', 'childrenCapacity')]):
                    continue
                offers.append(copy.deepcopy(offer))
            if offers:
                result = copy.deepcopy(hotel)
                result['offers'] = offers
                results.append((distance, result))
        # Frozen provider order breaks equal-distance ties. Ranking remains an
        # experimental dependency: it is not asserted to reproduce Elasticsearch.
        results.sort(key=lambda item: item[0])
        start, size = args.get('from', 0), args.get('size', 5)
        return {'resolvedDate': self.day, 'results': [r for _, r in results[start:start + size]],
                'total': len(results), 'has_more': start + size < len(results)}

    def legacy_hotels(self) -> list[Any]:
        from src.domain.entities.hotel import Hotel
        from src.domain.value_objects.location import Location
        from src.domain.value_objects.money import Money
        from src.domain.value_objects.timeslot import TimeSlot

        hotels = []
        for row in self.rows:
            h = row['provider']
            slots = []
            for o in h['offers']:
                # Use the same visible price with no second fee addition. Fees
                # remain included once; controls exclude fee-exempt display.
                if h.get('showPricesWithoutBookingFees'):
                    raise UnsupportedDimension('fee-exempt display outside legacy control')
                slots.append(TimeSlot(
                    start=time(o['startHour'], o.get('startMinute', 0)),
                    end=time(o['endHour'], o.get('endMinute', 0)),
                    price=Money(Decimal(str(o['priceEuroWithBookingFees'])) / 100, 'EUR'),
                    rateplan_id=str(o['ratePlanId']), timezone=h.get('timezone') or 'UTC',
                    rate_plan_name=o.get('ratePlanName'),
                ))
            hotels.append(Hotel(
                hotel_id=h['hotelId'], name=h['name'], country_code=row['country_code'],
                city=h['cityName'], metro=h['cityName'], address=h.get('address') or '',
                location=Location(city=h['cityName'], country=h.get('countryName') or row['country_code'],
                                  country_code=row['country_code'], latitude=h['lat'], longitude=h['lon']),
                stars=h.get('starRating') or 0, rating=0, timeslots=slots,
            ))
        return hotels


class LegacyRepository:
    """Repository seam; no new model, geographic dictionary, or production DB."""
    def __init__(self, inventory: CommonInventory):
        self.hotels = inventory.legacy_hotels()

    async def get_by_id(self, hotel_id):
        return next((h for h in self.hotels if h.hotel_id == int(hotel_id)), None)

    async def get_by_ids(self, hotel_ids):
        return [h for h in self.hotels if h.hotel_id in hotel_ids]

    async def find_by_name(self, name, limit=100):
        return [h for h in self.hotels if folded(name) in folded(h.name)][:limit]

    async def find_by_city(self, city, country_code=None):
        return [h for h in self.hotels if folded(h.city) == folded(city)
                and (not country_code or h.country_code == country_code)]

    async def find_by_metro(self, metro, country_code=None):
        return await self.find_by_city(metro, country_code)

    async def find_by_zone(self, city, zone, country_code=None):
        # No neighbourhood membership is asserted by these provider records.
        return []

    async def find_by_location(self, location, radius_km=10, country_code=None):
        return [h for h in self.hotels if (not country_code or h.country_code == country_code)
                and distance_km(location.latitude, location.longitude,
                                h.location.latitude, h.location.longitude) <= radius_km]

    async def count_by_location(self, location, radius_km=30, country_code=None):
        return len(await self.find_by_location(location, radius_km, country_code))

    async def get_all_cities(self):
        return sorted({h.city for h in self.hotels})

    async def count_by_city(self, city):
        return len(await self.find_by_city(city))

    async def search(self, *, city=None, country_code=None, limit=100, **kwargs):
        if any(value is not None for value in kwargs.values()):
            raise UnsupportedDimension('unsupported repository fallback filter')
        return (await self.find_by_city(city, country_code))[:limit] if city else self.hotels[:limit]


class LegacyAvailability:
    def __init__(self, inventory: CommonInventory):
        self.entries = {(h['provider']['hotelId'], int(o['ratePlanId'])):
                        {'available': True, 'price_minor': o['priceEuroWithBookingFees'], 'booking_fee_minor': 0, 'cutoffDeadlineUtc': o.get('cutoffDeadlineUtc')}
                        for h in inventory.rows for o in h['provider']['offers']}

    def ensure_loaded(self):
        return None

    def get_rate_plan(self, hotel_id, rate_plan_id):
        row = self.entries.get((hotel_id, rate_plan_id))
        return {**row, 'available': available(row)} if row else None


class NoVectorEvidence:
    async def search(self, *args, **kwargs):
        # Absence, not fabricated equal embedding scores. Mood/semantic ranking
        # is explicitly outside the conclusions of this controlled experiment.
        return []
