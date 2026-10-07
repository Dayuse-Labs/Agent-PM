"""Loopback-only MCP seam for the finite, read-only common inventory control."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from evals.common_inventory import CommonInventory, UnsupportedDimension


def app(snapshot: Path, catalog: Path, receipts: Path) -> Starlette:
    inventory = CommonInventory.read(snapshot)
    tools = json.loads(catalog.read_text())['tools']

    def record(value: dict) -> None:
        receipts.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with receipts.open('a') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        receipts.chmod(0o600)

    async def rpc(request):
        if request.method != 'POST':
            return Response(status_code=405)
        body = await request.json()
        if 'id' not in body:
            return Response(status_code=202)
        params = body.get('params', {})
        try:
            if body['method'] == 'initialize':
                result = {'protocolVersion': params['protocolVersion'], 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'dayuse-common-inventory', 'version': '1'}}
            elif body['method'] == 'tools/list':
                result = {'tools': [t for t in tools if t['name'] == 'search_offers']}
            elif body['method'] == 'ping':
                result = {}
            elif body['method'] == 'tools/call':
                if params['name'] != 'search_offers':
                    raise UnsupportedDimension('search-only control')
                data = inventory.search(params.get('arguments', {}))
                result = {'content': [{'type': 'text', 'text': json.dumps(data)}],
                          'structuredContent': data, 'isError': False}
                record({'params': params, 'outcome': 'served', 'hotel_ids': [h['hotelId'] for h in data['results']]})
            else:
                raise UnsupportedDimension('method unsupported')
            return JSONResponse({'jsonrpc': '2.0', 'id': body['id'], 'result': result})
        except (UnsupportedDimension, KeyError, TypeError, ValueError) as error:
            record({'params': params, 'outcome': 'unsupported', 'error_type': type(error).__name__})
            return JSONResponse({'jsonrpc': '2.0', 'id': body['id'], 'error': {
                'code': -32602, 'message': 'Outside the supported common-inventory control.'}})

    return Starlette(routes=[Route('/mcp', rpc, methods=['POST', 'GET', 'DELETE'])])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--receipts', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8378)
    args = parser.parse_args()
    uvicorn.run(app(args.snapshot, args.catalog, args.receipts), host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
