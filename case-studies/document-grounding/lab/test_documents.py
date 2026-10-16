"""Check declared reasons, execution order and model/tool continuation offline."""
from contextlib import redirect_stdout
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import httpx
from openai import OpenAI

from terminal_documents import ask, execute_read, fetch_document, validate_url
from document_audit import validate_review, validate_answer

CANDIDATES = [{"id": "web-search", "title": "Web Search",
               "url": "https://docs.x.ai/developers/tools/web-search"}]
ARGUMENTS = {"document_id": "web-search", "selection_reason": "Verify the official tool name.",
             "information_needed": "Name of the built-in search tool."}


class DocumentTests(unittest.TestCase):
    def test_missing_reason_prevents_network_access(self):
        fetch = Mock()
        for arguments in ({**ARGUMENTS, "selection_reason": " "},
                          {**ARGUMENTS, "information_needed": ""},
                          {**ARGUMENTS, "document_id": "unknown"}):
            with self.assertRaises(ValueError):
                execute_read(arguments, CANDIDATES, fetch)
        fetch.assert_not_called()

    def test_python_fetches_markdown_and_enforces_truncation(self):
        def handle(request):
            self.assertTrue(str(request.url).endswith('/web-search.md'))
            self.assertEqual(request.headers['accept'], '*/*')
            return httpx.Response(200, headers={"content-type": "text/markdown"}, text="a" * 25000)
        real_client = httpx.Client(transport=httpx.MockTransport(handle))
        with patch('terminal_documents.httpx.Client', return_value=real_client):
            result = fetch_document(CANDIDATES[0]["url"])
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["text"]), 24000)
        self.assertEqual(result["status"], "read")

    def test_failed_fetch_and_unapproved_urls_are_not_successes(self):
        with self.assertRaises(httpx.ConnectError):
            execute_read(ARGUMENTS, CANDIDATES, Mock(side_effect=httpx.ConnectError("offline")))
        for url in ('http://docs.x.ai/docs', 'https://localhost/x', 'https://docs.x.ai.evil.test/x'):
            with self.assertRaises(ValueError):
                validate_url(url)

    def test_actual_sdk_tool_call_roundtrip_records_reason_before_fetch(self):
        request_number = 0
        decisions = {"decisions": [{"document_id": "web-search", "decision": "select",
                                    "reason": "Check the search tool name.",
                                    "information_needed": "Official tool name."}]}
        final = {"claims": [{"claim_id": "C1", "claim": "The built-in search tool is web_search.",
                             "evidence": [{"document_id": "web-search", "quote": "The tool is web_search."}]}],
                 "limitations": ""}
        def handle(request):
            nonlocal request_number
            body = json.loads(request.content)
            request_number += 1
            base = {"id": f"response_{request_number}", "object": "response",
                    "created_at": 1, "status": "completed", "model": "test-model", "usage": None}
            if request_number == 1:
                self.assertEqual(body["tools"][0]["name"], "review_candidates")
                self.assertNotIn({"type": "web_search"}, body["tools"])
                name, arguments = 'review_candidates', decisions
            elif request_number == 2:
                self.assertEqual(body['previous_response_id'], 'response_1')
                name, arguments = 'read_document', ARGUMENTS
            elif request_number == 3:
                self.assertEqual(json.loads(body['input'][0]['output'])['text'], 'The tool is web_search.')
                name, arguments = 'submit_answer', json.loads(json.dumps(final))
                arguments['claims'][0]['evidence'][0]['quote'] = 'This quote was never retrieved.'
            else:
                self.assertEqual(json.loads(body['input'][0]['output'])['status'], 'failed')
                name, arguments = 'submit_answer', final
            return httpx.Response(200, json={**base, "output": [{
                'type': 'function_call', 'id': f'fc{request_number}', 'call_id': f'call{request_number}',
                'name': name, 'arguments': json.dumps(arguments)}]})
        lf = MagicMock()
        observations = []
        def observation(**kwargs):
            obj, context = MagicMock(), MagicMock()
            observations.append((kwargs['name'], obj))
            context.__enter__.return_value = obj
            return context
        lf.start_as_current_observation.side_effect = observation
        lf.get_trace_url.return_value = "https://example.com/trace"
        def fetch(arguments, candidates):
            tool = next(obj for name, obj in observations if name == 'read-document')
            tool.update.assert_called_once_with(input=ARGUMENTS)
            return {"status": "read", "source_url": CANDIDATES[0]["url"],
                    "content_url": CANDIDATES[0]["url"] + '.md',
                    "text": "The tool is web_search.", "truncated": False}
        with OpenAI(api_key="offline-test", base_url="https://example.invalid/v1",
                    http_client=httpx.Client(transport=httpx.MockTransport(handle))) as client:
            with patch('terminal_documents.execute_read', side_effect=fetch), redirect_stdout(io.StringIO()):
                result = ask("What is the search tool called?", langfuse=lf, client=client,
                             candidates=CANDIDATES, settings={"model": "test-model",
                             "reasoning_effort": "low", "max_output_tokens": 200})
        self.assertEqual(result["read_documents"][0]["selection_reason"], ARGUMENTS["selection_reason"])
        self.assertEqual(request_number, 4)
        self.assertTrue(result['claim_evidence'][0]['evidence'][0]['quote_verified'])
        self.assertFalse(result['claim_support_evaluated'])
        self.assertEqual(result['candidate_review']['decisions'], decisions['decisions'])

    def test_every_candidate_needs_exactly_one_decision(self):
        decision = {"document_id": "web-search", "decision": "exclude", "reason": "Unrelated to this question.", "information_needed": ""}
        with self.assertRaises(ValueError):
            validate_review({'decisions': []}, CANDIDATES)
        with self.assertRaises(ValueError):
            validate_review({'decisions': [decision, decision]}, CANDIDATES)
        self.assertEqual(validate_review({'decisions': [decision]}, CANDIDATES)['decisions'][0]['decision'], 'exclude')

    def test_evidence_must_come_from_a_successful_read_and_match_quote(self):
        document = {"document_id": "web-search", "status": "read", "source_url": CANDIDATES[0]['url'],
                    "text": "The tool is\nweb_search."}
        arguments = {'claims': [{'claim_id': 'C1', 'claim': 'The tool is called web_search.',
                     'evidence': [{'document_id': 'web-search', 'quote': 'The tool is web_search.'}]}], 'limitations': ''}
        with self.assertRaises(ValueError):
            validate_answer(arguments, [])
        with self.assertRaises(ValueError):
            validate_answer(arguments, [{**document, 'status': 'failed'}])
        checked = validate_answer(arguments, [document])
        self.assertTrue(checked['claim_evidence'][0]['evidence'][0]['quote_verified'])
        self.assertFalse(checked['claim_support_evaluated'])
        arguments['claims'][0]['evidence'] = []
        with self.assertRaises(ValueError):
            validate_answer(arguments, [document])

    def test_abstention_does_not_invent_evidence(self):
        answer = validate_answer({'claims': [], 'limitations': 'No candidate covers the question.'}, [])
        self.assertEqual(answer['status'], 'abstained')
        self.assertEqual(answer['claim_evidence'], [])


if __name__ == '__main__':
    unittest.main()
