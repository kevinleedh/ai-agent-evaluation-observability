import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from mcp.types import CallToolResult, TextContent
from mcp.shared.auth import OAuthToken

from mcp_connection import BrowserLogin, OAuthStorage, list_catalog, payload_fingerprint, traced_request


class Observation:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class Tracer:
    def __init__(self):
        self.records = []

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        observation = Observation()
        self.records.append((kwargs, observation))
        yield observation


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_reuse_does_not_bind_callback_port(self):
        with patch('mcp_connection.ThreadingHTTPServer') as server:
            async with BrowserLogin(8766, open_browser=False) as login:
                self.assertIsNone(login.server)
            server.assert_not_called()

    async def test_full_unicode_body_is_recorded_and_forwarded_without_shortening(self):
        text = ('Full document paragraph. Unicode \u03a9 verification.\n' * 4000) + 'END-OF-DOCUMENT'
        result = CallToolResult(content=[TextContent(type='text', text=text)], isError=False)
        expected = result.model_dump(mode='json', by_alias=True, exclude_none=True)
        tracer = Tracer()

        async def operation():
            return result

        forwarded = await traced_request(tracer, name='drive.read', arguments={'fileId': 'fixture'}, operation=operation)
        captured = tracer.records[0][1].updates[0]['output']
        self.assertIs(captured, forwarded)
        self.assertEqual(forwarded, expected)
        self.assertEqual(forwarded['content'][0]['text'], text)
        self.assertEqual(tracer.records[0][1].updates[0]['metadata'], payload_fingerprint(expected))

    async def test_transport_errors_do_not_leak_exception_text(self):
        tracer = Tracer()

        async def operation():
            raise RuntimeError('secret-token-in-request-url')

        with self.assertRaises(RuntimeError):
            await traced_request(tracer, name='drive.read', arguments={}, operation=operation)
        serialized = json.dumps(tracer.records[0][1].updates)
        self.assertNotIn('secret-token', serialized)
        self.assertIn('ERROR', serialized)

    async def test_mcp_error_payload_is_retained_and_marked_as_error(self):
        tracer = Tracer()

        async def operation():
            return CallToolResult(content=[TextContent(type='text', text='File unavailable')], isError=True)

        result = await traced_request(tracer, name='drive.read', arguments={}, operation=operation)
        self.assertTrue(result['isError'])
        self.assertTrue(any(update.get('level') == 'ERROR' for update in tracer.records[0][1].updates))

    async def test_discovery_keeps_all_pages(self):
        from mcp.types import ListToolsResult

        class Session:
            def __init__(self):
                self.cursors = []

            async def list_tools(self, cursor=None):
                self.cursors.append(cursor)
                return ListToolsResult(tools=[], nextCursor='page-2' if cursor is None else None)

        session, tracer = Session(), Tracer()
        pages = await list_catalog(session, tracer)
        self.assertEqual(session.cursors, [None, 'page-2'])
        self.assertEqual(len(pages), 2)
        self.assertEqual(len(tracer.records), 2)

    async def test_discovery_rejects_repeated_cursor(self):
        from mcp.types import ListToolsResult

        class Session:
            async def list_tools(self, cursor=None):
                return ListToolsResult(tools=[], nextCursor='same-page')

        with self.assertRaisesRegex(RuntimeError, 'pagination'):
            await list_catalog(Session(), Tracer())

    async def test_oauth_tokens_are_private_and_server_local(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OAuthStorage(Path(directory) / '.auth' / 'one-server')
            self.assertIsNone(await store.get_tokens())
            await store.set_tokens(OAuthToken(access_token='test-only-token', token_type='Bearer'))
            self.assertEqual((await store.get_tokens()).access_token, 'test-only-token')
            path = store.directory / 'tokens.json'
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertFalse((path.parent.parent / 'other-server' / 'tokens.json').exists())


if __name__ == '__main__':
    unittest.main()
