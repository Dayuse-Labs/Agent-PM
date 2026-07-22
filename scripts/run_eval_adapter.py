#!/usr/bin/env python3
"""Eval-pack adapter: thin reverse proxy in front of the AgentB2C facade so the
black-box `dayuse_eval_pack` runner can assert on the candidate WITHOUT the pack
being modified (its README: adapter in front, never weakened cases).

Scope — field mapping only, never fabrication (an invented value would corrupt
the audit). Three rules, each applied to a hotel card ONLY when the key is
absent, never overwriting:

1. `country_code`  ← static full-name→ISO2 table applied to `country`
   (MCP_B2C sends `countryName` full names; the runner uppercases the fallback
   `country` into a pseudo-code — "FRANCE" never matches {"FR"}). Unknown
   names are LEFT UNMAPPED so the failure stays visible instead of silent.
2. `currency: "EUR"` ← iff `price` matches the facade's own `€X.XX` format
   (provenance fact: that string is always formatted from `priceEuro` cents).
3. `display_price`   ← the float parsed from that same `€X.XX` string
   (redundant with the runner's `price` fallback, but explicit in reports).

Every added field is disclosed per hotel under `eval_debug.adapter_mapped` in
the response the runner archives — the audit report can show exactly what the
adapter touched. Requests pass through UNCHANGED except one added header,
`X-Dayuse-Synthetic: 1`, so candidate conversation logs get is_synthetic=true.

Non-goals (documented capability gaps, never bridged here): latitude/longitude/
distance_km, booking_card, non-EUR currencies, requires_clarification flips.

Usage:
    python3 scripts/run_eval_adapter.py                    # :8110 -> :8100
    python3 scripts/run_eval_adapter.py --port 8110 --backend http://127.0.0.1:8100
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# The facade's own price format (facade.normalize_hotels / leaf normalize_hotel):
# always EUR, always formatted from priceEuro cents.
_PRICE_EUR_RE = re.compile(r"^€(\d+(?:\.\d{2})?)$")

# Full-name → ISO2 for the 29 markets present in the eval pack's prod inventory
# fixture (+ common spelling variants). Keys are matched case-insensitively.
# Deliberately NOT exhaustive: an unknown name must stay visible as a failure.
COUNTRY_NAME_TO_ISO2 = {
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "USA": "US",
    "FRANCE": "FR",
    "UNITED KINGDOM": "GB",
    "GREAT BRITAIN": "GB",
    "ITALY": "IT",
    "GERMANY": "DE",
    "AUSTRALIA": "AU",
    "CANADA": "CA",
    "NETHERLANDS": "NL",
    "THE NETHERLANDS": "NL",
    "SWITZERLAND": "CH",
    "SINGAPORE": "SG",
    "HONG KONG": "HK",
    "SPAIN": "ES",
    "BELGIUM": "BE",
    "UNITED ARAB EMIRATES": "AE",
    "UAE": "AE",
    "NEW ZEALAND": "NZ",
    "THAILAND": "TH",
    "AUSTRIA": "AT",
    "PORTUGAL": "PT",
    "IRELAND": "IE",
    "BRAZIL": "BR",
    "LUXEMBOURG": "LU",
    "CZECH REPUBLIC": "CZ",
    "CZECHIA": "CZ",
    "SAUDI ARABIA": "SA",
    "TURKEY": "TR",
    "TURKIYE": "TR",
    "TÜRKIYE": "TR",
    "SOUTH KOREA": "KR",
    "KOREA": "KR",
    "REPUBLIC OF KOREA": "KR",
    "QATAR": "QA",
    "MACAO": "MO",
    "MACAU": "MO",
    "SWEDEN": "SE",
    "BAHRAIN": "BH",
}


def map_hotel_card(card: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """One mapped copy of a hotel card + the list of fields the adapter added.
    Only absent keys are ever filled; existing values always win."""
    mapped = dict(card)
    added: list[str] = []

    if "country_code" not in mapped:
        country = mapped.get("country")
        if isinstance(country, str):
            code = COUNTRY_NAME_TO_ISO2.get(country.strip().upper())
            if code:
                mapped["country_code"] = code
                added.append("country_code")

    price = mapped.get("price")
    match = _PRICE_EUR_RE.fullmatch(price) if isinstance(price, str) else None
    if match:
        if "currency" not in mapped:
            mapped["currency"] = "EUR"
            added.append("currency")
        if "display_price" not in mapped:
            mapped["display_price"] = float(match.group(1))
            added.append("display_price")

    return mapped, added


def map_chat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """The /v3/chat response with every hotel card mapped. Adds
    `eval_debug.adapter_mapped` (hotel id → added fields) only when the adapter
    actually touched something; otherwise the payload is returned as-is."""
    hotels = payload.get("hotels")
    if not isinstance(hotels, list):
        return payload

    mapped_hotels: list[Any] = []
    disclosure: dict[str, list[str]] = {}
    for index, hotel in enumerate(hotels):
        if not isinstance(hotel, dict):
            mapped_hotels.append(hotel)
            continue
        mapped, added = map_hotel_card(hotel)
        mapped_hotels.append(mapped)
        if added:
            disclosure[str(mapped.get("id") or f"index_{index}")] = added

    if not disclosure:
        return payload

    out = dict(payload)
    out["hotels"] = mapped_hotels
    eval_debug = dict(out.get("eval_debug") or {})
    eval_debug["adapter_mapped"] = disclosure
    out["eval_debug"] = eval_debug
    return out


_HOP_BY_HOP_REQUEST_HEADERS = {"host", "content-length", "connection", "accept-encoding"}
_HOP_BY_HOP_RESPONSE_HEADERS = {"transfer-encoding", "connection", "content-length"}


class EvalAdapterHandler(BaseHTTPRequestHandler):
    backend: str

    def do_POST(self) -> None:  # noqa: N802 (stdlib method name)
        path = self.path.split("?", 1)[0]
        if not path.startswith("/v3/"):
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(f"{self.backend}{self.path}", data=body, method="POST")
        for key, value in self.headers.items():
            if key.lower() not in _HOP_BY_HOP_REQUEST_HEADERS:
                req.add_header(key, value)
        req.add_header("X-Dayuse-Synthetic", "1")

        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as exc:
            resp = exc  # HTTPError quacks like a response (status/headers/read)
        except urllib.error.URLError as exc:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"eval-adapter: backend unreachable ({exc.reason})".encode())
            return

        status = getattr(resp, "status", None) or getattr(resp, "code", 502)
        content_type = resp.headers.get("Content-Type") or ""
        if path == "/v3/chat" and "application/json" in content_type:
            self._respond_mapped_json(status, resp)
        else:
            self._stream_through(status, resp)

    # --- JSON mapping branch (the runner's endpoint) ----------------------------------------
    def _respond_mapped_json(self, status: int, resp: Any) -> None:
        raw = resp.read()
        try:
            payload = json.loads(raw)
            body = json.dumps(map_chat_payload(payload), ensure_ascii=False).encode("utf-8")
        except (ValueError, TypeError):
            body = raw  # not JSON after all — pass through untouched
        self.send_response(status)
        for key, value in resp.getheaders():
            if key.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    # --- pass-through branch (SSE etc. — streams incrementally) ------------------------------
    def _stream_through(self, status: int, resp: Any) -> None:
        self.send_response(status)
        for key, value in resp.getheaders():
            if key.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS:
                self.send_header(key, value)
        self.send_header("Connection", "close")
        self.end_headers()
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except BrokenPipeError:
                break

    def log_message(self, fmt: str, *args: object) -> None:  # path+status only, never a body
        print(f"eval-adapter: {self.address_string()} {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8110)
    parser.add_argument("--backend", default="http://127.0.0.1:8100")
    args = parser.parse_args()

    EvalAdapterHandler.backend = args.backend.rstrip("/")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), EvalAdapterHandler)
    print(f"eval-adapter: http://127.0.0.1:{args.port}/v3/chat -> {args.backend}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
