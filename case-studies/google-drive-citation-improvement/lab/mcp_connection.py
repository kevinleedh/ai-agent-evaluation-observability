"""Use an existing remote MCP server; this module does not implement a server."""
import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
from urllib.parse import parse_qs, urlsplit
import webbrowser

from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

ROOT = Path(__file__).resolve().parent


def private_json(path, value):
    """Atomically store private data without world-readable intermediate files."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class OAuthStorage:
    """SDK-managed tokens stay local and never enter Langfuse or Grok inputs."""
    def __init__(self, directory):
        self.directory = Path(directory)

    def read(self, name, model):
        path = self.directory / name
        return model.model_validate_json(path.read_text()) if path.exists() else None

    async def get_tokens(self):
        return self.read('tokens.json', OAuthToken)

    async def set_tokens(self, tokens):
        private_json(self.directory / 'tokens.json', tokens.model_dump(mode='json'))

    async def get_client_info(self):
        return self.read('client.json', OAuthClientInformationFull)

    async def set_client_info(self, client_info):
        private_json(self.directory / 'client.json', client_info.model_dump(mode='json'))


class BrowserLogin:
    """Loopback OAuth callback. Authorization codes are not printed or saved."""
    def __init__(self, port, *, open_browser=True):
        self.port = port
        self.open_browser = open_browser
        self.state = None
        self.server = None
        self.thread = None
        self.loop = None
        self.future = None

    async def __aenter__(self):
        self.loop = asyncio.get_running_loop()
        self.future = self.loop.create_future()
        return self

    def start_server(self):
        # Reusing valid tokens needs no callback listener. Keep the port free
        # until OAuth actually asks to open the authorization page.
        if self.server:
            return
        login = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                state = query.get('state', [None])[0]
                if parsed.path != '/callback' or not login.state or state != login.state:
                    self.send_error(400, 'Invalid OAuth callback')
                    return
                code = query.get('code', [None])[0]
                denied = bool(query.get('error'))
                if not code and not denied:
                    self.send_error(400, 'Missing authorization code')
                    return
                login.loop.call_soon_threadsafe(login.deliver, code, state, denied)
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(b'Authorization response received. Return to your terminal.')

        self.server = ThreadingHTTPServer(('127.0.0.1', self.port), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def deliver(self, code, state, denied):
        if self.future.done():
            return
        if denied:
            self.future.set_exception(RuntimeError('Authorization was not granted'))
        else:
            self.future.set_result((code, state))

    async def redirect(self, url):
        if urlsplit(url).scheme != 'https':
            raise RuntimeError('Authorization endpoint must use HTTPS')
        self.state = parse_qs(urlsplit(url).query).get('state', [None])[0]
        if not self.state:
            raise RuntimeError('OAuth state missing')
        self.start_server()
        print('Sign in to Pipedream and enable Google Drive in the browser.', flush=True)
        opened = await asyncio.to_thread(webbrowser.open, url) if self.open_browser else False
        if not opened:
            print('Open this authorization URL in your browser:\n' + url, flush=True)

    async def callback(self):
        return await asyncio.wait_for(asyncio.shield(self.future), timeout=300)

    async def __aexit__(self, *args):
        if self.server:
            await asyncio.to_thread(self.server.shutdown)
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)
        if not self.future.done():
            self.future.cancel()


@asynccontextmanager
async def connect(settings, *, open_browser=True):
    url = settings['server_url']
    # Keep the credential store tied to this exact server URL.
    server_key = sha256(url.encode()).hexdigest()[:16]
    async with BrowserLogin(settings['callback_port'], open_browser=open_browser) as login:
        auth = OAuthClientProvider(
            server_url=url,
            client_metadata=OAuthClientMetadata(
                client_name='Drive document evaluation lab',
                redirect_uris=[f"http://127.0.0.1:{settings['callback_port']}/callback"],
                grant_types=['authorization_code', 'refresh_token'],
                response_types=['code'],
                token_endpoint_auth_method='none',
            ),
            storage=OAuthStorage(ROOT / '.auth' / server_key),
            redirect_handler=login.redirect,
            callback_handler=login.callback,
        )
        async with streamablehttp_client(url, auth=auth, timeout=30, sse_read_timeout=300) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                initialization = await session.initialize()
                yield session, initialization


def payload_fingerprint(payload):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return {'returned_payload_bytes': len(encoded), 'returned_payload_sha256': sha256(encoded).hexdigest()}


async def traced_request(langfuse, *, name, arguments, operation, metadata=None):
    """Record the complete returned MCP payload; forward that same object."""
    with langfuse.start_as_current_observation(
        name=name, as_type='tool', input=arguments,
        metadata={'execution_source': 'client_observed_remote_mcp',
                  'timing_basis': 'client_request_wrapper', **(metadata or {})},
    ) as observation:
        try:
            result = await operation()
            payload = result.model_dump(mode='json', by_alias=True, exclude_none=True)
            observation.update(output=payload, metadata=payload_fingerprint(payload))
            if payload.get('isError'):
                observation.update(level='ERROR', status_message='MCP tool returned isError')
            return payload
        except BaseException as error:
            # HTTP errors may contain credentials or callback codes in their URLs.
            observation.update(output={'status': 'failed', 'error_type': type(error).__name__},
                               level='ERROR', status_message=type(error).__name__)
            raise


async def list_catalog(session, langfuse):
    """Discovery only: no file action is executed and no Grok request is made."""
    pages = []
    cursor = None
    seen = set()
    while True:
        result = await traced_request(
            langfuse, name='mcp.tools-list', arguments={'cursor': cursor},
            operation=lambda: session.list_tools(cursor=cursor),
        )
        pages.append(result)
        cursor = result.get('nextCursor')
        if not cursor:
            return pages
        if cursor in seen:
            raise RuntimeError('MCP tools/list repeated its pagination cursor')
        seen.add(cursor)
