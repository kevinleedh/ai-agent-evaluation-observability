"""Authenticate to the existing Pipedream MCP and record its tool catalog."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from langfuse import Langfuse

from mcp_connection import ROOT, connect, list_catalog, private_json


def settings():
    return json.loads((ROOT / 'settings.local.json').read_text())


def credentials():
    # Public package: use this lab's .env; externally set variables take precedence.
    load_dotenv(ROOT / '.env', override=False, interpolate=False)
    return {name: os.environ.get(name, '').strip() for name in
            ('LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY', 'LANGFUSE_BASE_URL')}


async def probe(config):
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(config['server_url'],
            headers={'Accept': 'application/json, text/event-stream'},
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                  'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                             'clientInfo': {'name': 'drive-eval-preflight', 'version': '0.1.0'}}})
    report = {'server_url': config['server_url'], 'http_status': response.status_code,
              'authentication_required': response.status_code == 401,
              'drive_access_verified': False, 'file_content_read': False}
    private_json(ROOT / 'runs' / 'connection-preflight.json', report)
    print(json.dumps(report, indent=2))


async def discover(config, keys, *, open_browser):
    lf = Langfuse(public_key=keys['LANGFUSE_PUBLIC_KEY'], secret_key=keys['LANGFUSE_SECRET_KEY'],
                  base_url=keys['LANGFUSE_BASE_URL'] or 'https://us.cloud.langfuse.com',
                  environment=config['environment'])
    try:
        if not lf.auth_check():
            raise RuntimeError('Langfuse authentication failed')
        print('Connecting to Pipedream MCP. Complete browser sign-in if prompted.', flush=True)
        # Authentication happens outside observations. OAuth URLs and tokens are not traced.
        async with connect(config, open_browser=open_browser) as (session, initialization):
            with lf.start_as_current_observation(
                name='drive-mcp-connection-check', as_type='span',
                input={'server_url': config['server_url'], 'operation': 'tools/list'},
                metadata={'stage': 'authentication_and_discovery', 'grok_called': False},
            ) as root:
                trace_url = lf.get_trace_url()
                pages = await list_catalog(session, lf)
                tools = [tool for page in pages for tool in page.get('tools', [])]
                report = {'status': 'connected', 'server_url': config['server_url'],
                          'server_info': initialization.serverInfo.model_dump(mode='json'),
                          'tool_count': len(tools), 'tool_names': [t['name'] for t in tools],
                          'drive_file_listing_verified': False, 'file_content_read': False,
                          'grok_called': False}
                root.update(output=report)
                stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                private_json(ROOT / 'runs' / f'mcp-catalog-{stamp}.json',
                             {'report': report, 'pages': pages, 'trace_url': trace_url})
                private_json(ROOT / 'runs' / 'latest-catalog.json',
                             {'report': report, 'pages': pages, 'trace_url': trace_url})
                print(f"Connected. Discovered {len(tools)} tools.")
                print('Trace:', trace_url)
                print('Saved catalog:', ROOT / 'runs' / 'latest-catalog.json')
                print('Next: inspect actual Drive tool schemas before reading the test folder.')
    finally:
        lf.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true', help='Unauthenticated endpoint check only')
    parser.add_argument('--check', action='store_true', help='Offline configuration check')
    parser.add_argument('--no-browser', action='store_true', help='Print login URL instead of opening it')
    args = parser.parse_args()
    config, keys = settings(), credentials()
    if config['server_url'] != 'https://mcp.pipedream.net/v2':
        raise ValueError('This connection setup is scoped to the supplied Pipedream URL')
    if not 1024 <= config['callback_port'] <= 65535:
        raise ValueError('Invalid callback port')
    if args.check:
        missing = [k for k in ('LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY') if not keys[k]]
        print('Existing Langfuse credential setup:', 'ready' if not missing else 'missing')
        print('Google Cloud project required by this client: no')
        print('No API calls. Pipedream/Google authentication is not verified.')
        return 1 if missing else 0
    if args.probe:
        asyncio.run(probe(config))
        return 0
    if not all(keys[k] for k in ('LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY')):
        raise RuntimeError('Existing Langfuse credentials are required')
    asyncio.run(discover(config, keys, open_browser=not args.no_browser))
    return 0


if __name__ == '__main__':
    # Suppress transport logs that could contain OAuth codes in request URLs.
    for namespace in ('httpx', 'httpcore', 'mcp'):
        logging.getLogger(namespace).setLevel(logging.CRITICAL)
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nStopped. Authentication or discovery was not confirmed.')
        raise SystemExit(130)
    except Exception as error:
        print('Connection did not complete:', type(error).__name__)
        print('No Drive access or document-reading success is claimed.')
        print('Retry the launcher; complete browser authorization and enable Google Drive.')
        raise SystemExit(1)
