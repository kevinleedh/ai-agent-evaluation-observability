"""Tavily HTTP behavior and the real model SDK's offline tool-call round trip."""
from contextlib import redirect_stdout
import io
import json
from unittest.mock import MagicMock, Mock
import unittest

import httpx
from openai import OpenAI

from tavily_backend import MAX_TEXT, TavilyBackend, public_https_url
from terminal_tavily import ReviewSession, ask, load_settings

URL = "https://example.com/document"
QUERY = {"query": "official function calling docs", "search_reason": "Find execution ownership.",
         "information_needed": "Who executes custom tools."}
READ = {"document_id": "search-1-doc-1", "selection_reason": "Verify execution ownership.",
        "information_needed": "Who executes the function."}
REVIEW = {"decisions": [{"document_id": READ["document_id"], "decision": "select",
                        "reason": "The official tool flow is relevant.",
                        "information_needed": "Function execution ownership."}]}
TEXT = "The caller executes the custom function locally."
FINAL = {"claims": [{"claim_id": "c1", "claim": "The caller executes custom functions locally.",
                    "evidence": [{"document_id": READ["document_id"], "quote": TEXT}]}], "limitations": ""}


def candidate():
    return {"id": READ["document_id"], "title": "Function Calling", "url": URL,
            "snippet": "A partial preview of function execution."}


def backend_mock():
    backend = Mock()
    backend.search.return_value = {"status": "searched", "candidates": [candidate()]}
    backend.extract.return_value = {"status": "read", "source_url": URL, "text": TEXT,
                                    "truncated": False, "document_id": READ["document_id"]}
    return backend


class BackendTests(unittest.TestCase):
    def test_search_uses_real_endpoint_without_returning_credentials_or_generated_answer(self):
        def handle(request):
            self.assertEqual(request.url.path, "/search")
            self.assertEqual(request.headers["authorization"], "Bearer PRIVATE_TEST_KEY")
            payload = json.loads(request.content)
            self.assertFalse(payload["include_answer"])
            self.assertFalse(payload["include_raw_content"])
            self.assertFalse(payload["auto_parameters"])
            self.assertEqual(payload["max_results"], 5)
            return httpx.Response(200, json={"results": [{"title": "Docs", "url": URL,
                "content": "a" * 2100, "raw_content": "not requested", "score": 0.9}],
                "answer": "Never use this generated answer", "usage": {"credits": 1}})
        backend = TavilyBackend("PRIVATE_TEST_KEY", transport=httpx.MockTransport(handle))
        try:
            result = backend.search("query")
        finally:
            backend.close()
        self.assertEqual(result["candidates"][0]["id"], READ["document_id"])
        self.assertEqual(len(result["candidates"][0]["snippet"]), 2000)
        self.assertTrue(result["candidates"][0]["snippet_truncated"])
        self.assertNotIn("PRIVATE_TEST_KEY", str(result))
        self.assertNotIn("Never use this generated answer", str(result))
        self.assertNotIn("raw_content", result["candidates"][0])

    def test_search_records_skipped_nonpublic_and_duplicate_urls(self):
        response = {"results": [{"url": URL}, {"url": URL}, {"url": "https://127.0.0.1/x"},
                                {"url": "https://localhost/x"}, {"url": "http://example.com/x"}]}
        backend = TavilyBackend("test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response)))
        try:
            result = backend.search("query")
        finally:
            backend.close()
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(len(result["skipped_results"]), 4)

    def test_extract_checks_http_200_failure_results(self):
        response = {"results": [], "failed_results": [{"url": URL, "error": "Could not read page"}]}
        backend = TavilyBackend("test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response)))
        try:
            result = backend.extract(candidate())
        finally:
            backend.close()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["failed_results"][0]["error"], "Could not read page")

    def test_extract_accepts_only_requested_url_and_bounds_returned_text(self):
        def handle(request):
            self.assertEqual(request.url.path, "/extract")
            payload = json.loads(request.content)
            self.assertEqual(payload["urls"], [URL])
            self.assertNotIn("query", payload)  # Do not silently request reranked partial chunks.
            return httpx.Response(200, json={"results": [{"url": URL, "raw_content": "a" * 25000}],
                                            "failed_results": []})
        backend = TavilyBackend("test", transport=httpx.MockTransport(handle))
        try:
            result = backend.extract(candidate())
        finally:
            backend.close()
        self.assertEqual(result["status"], "read")
        self.assertEqual(len(result["text"]), MAX_TEXT)
        self.assertTrue(result["truncated"])

    def test_extract_does_not_accept_unrelated_url_or_empty_content(self):
        for results in ([{"url": "https://example.org/other", "raw_content": TEXT}],
                        [{"url": URL, "raw_content": " "}]):
            backend = TavilyBackend("test", transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"results": results})))
            try:
                self.assertEqual(backend.extract(candidate())["status"], "failed")
            finally:
                backend.close()

    def test_private_urls_and_embedded_credentials_are_rejected(self):
        for url in ("https://10.0.0.1/x", "https://127.0.0.1/x", "file:///etc/passwd",
                    "https://x.local/a", "https://user:pass@example.com/a", "https://example.com:8443/x"):
            self.assertFalse(public_https_url(url), url)
        self.assertTrue(public_https_url(URL))


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.backend = backend_mock()
        self.session = ReviewSession(self.backend, load_settings())

    def ready(self):
        self.session.execute("search_web", QUERY, [])
        self.session.execute("review_candidates", REVIEW, [])

    def test_reason_is_required_before_search_network_request(self):
        with self.assertRaises(ValueError):
            self.session.execute("search_web", {**QUERY, "search_reason": ""}, [])
        self.backend.search.assert_not_called()

    def test_review_is_exhaustive_and_explicitly_uses_search_snippets(self):
        self.session.execute("search_web", QUERY, [])
        with self.assertRaises(ValueError):
            self.session.execute("review_candidates", {"decisions": []}, [])
        result = self.session.execute("review_candidates", REVIEW, [])
        self.assertEqual(result["basis"], "question_and_search_titles_urls_snippets")

    def test_read_before_review_or_unknown_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self.session.execute("read_document", READ, [])
        self.ready()
        with self.assertRaises(ValueError):
            self.session.execute("read_document", {**READ, "document_id": "made-up"}, [])
        self.backend.extract.assert_not_called()

    def test_search_snippet_and_same_turn_read_are_not_quote_evidence(self):
        self.ready()
        with self.assertRaises(ValueError):
            self.session.execute("submit_answer", FINAL, [])
        self.session.execute("read_document", READ, [])
        with self.assertRaises(ValueError):
            self.session.execute("submit_answer", FINAL, [])
        result = self.session.execute("submit_answer", FINAL, list(self.session.reads))
        self.assertTrue(result["quote_checks_passed"])
        self.assertFalse(result["claim_support_evaluated"])

    def test_failed_read_and_duplicate_attempt_cannot_be_evidence_or_retried(self):
        self.ready()
        self.backend.extract.return_value = {"status": "failed", "text": "", "source_url": URL}
        self.session.execute("read_document", READ, [])
        with self.assertRaises(ValueError):
            self.session.execute("read_document", READ, [])
        with self.assertRaises(ValueError):
            self.session.execute("submit_answer", FINAL, self.session.reads)
        self.assertEqual(self.session.read_attempts, 1)

    def test_http_failure_is_recorded_without_secret_error_body_and_can_abstain(self):
        request = httpx.Request("POST", "https://api.tavily.com/search")
        response = httpx.Response(401, request=request, text="PRIVATE_TEST_KEY")
        self.backend.search.side_effect = httpx.HTTPStatusError("PRIVATE_TEST_KEY", request=request, response=response)
        result = self.session.execute("search_web", QUERY, [])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["http_status"], 401)
        self.assertNotIn("PRIVATE_TEST_KEY", str(result))
        self.session.execute("review_candidates", {"decisions": []}, [])
        result = self.session.execute("submit_answer", {"claims": [], "limitations": "Search failed; no evidence is available."}, [])
        self.assertEqual(result["status"], "abstained")
        with self.assertRaises(ValueError):
            self.session.execute("search_web", QUERY, [])


class RoundTripTests(unittest.TestCase):
    def test_real_sdk_continuation_and_trace_snapshots_with_quote_correction(self):
        backend, lf = backend_mock(), MagicMock()
        observations, count = [], 0
        def observation(**kwargs):
            obj, context = MagicMock(), MagicMock()
            observations.append((kwargs["name"], obj))
            context.__enter__.return_value = obj
            return context
        lf.start_as_current_observation.side_effect = observation
        lf.get_trace_url.return_value = "https://example.com/trace"
        def extract(item):
            trace_tool = next(obj for name, obj in observations if name == "tavily-extract")
            trace_tool.update.assert_called_once_with(input=READ)
            return {"status": "read", "source_url": URL, "text": TEXT, "truncated": False,
                    "document_id": READ["document_id"]}
        backend.extract.side_effect = extract
        def handle(request):
            nonlocal count
            count += 1
            body = json.loads(request.content)
            if count == 1:
                self.assertEqual([t["name"] for t in body["tools"]], ["search_web"])
                self.assertNotIn("previous_response_id", body)
                name, arguments = "search_web", QUERY
            else:
                self.assertEqual(body["previous_response_id"], f"response_{count-1}")
                name, arguments = {2: ("review_candidates", REVIEW), 3: ("read_document", READ),
                                   4: ("submit_answer", FINAL), 5: ("submit_answer", FINAL)}[count]
            if count == 4:
                self.assertEqual(json.loads(body["input"][0]["output"])["text"], TEXT)
                arguments = json.loads(json.dumps(FINAL))
                arguments["claims"][0]["evidence"][0]["quote"] = "This quote was never retrieved."
            if count == 5:
                self.assertEqual(json.loads(body["input"][0]["output"])["status"], "failed")
            return httpx.Response(200, json={"id": f"response_{count}", "object": "response",
                "created_at": 1, "status": "completed", "model": "test-model", "usage": None,
                "output": [{"type": "function_call", "id": f"fc{count}", "call_id": f"call{count}",
                            "name": name, "arguments": json.dumps(arguments)}]})
        with OpenAI(api_key="offline", base_url="https://example.invalid/v1",
                    http_client=httpx.Client(transport=httpx.MockTransport(handle))) as client:
            with redirect_stdout(io.StringIO()):
                result = ask("Who executes custom tools?", langfuse=lf, client=client,
                             backend=backend, settings=load_settings())
        self.assertEqual(count, 5)
        self.assertEqual(result["output"]["search_attempts"], 1)
        self.assertEqual(result["output"]["read_attempts"], 1)
        self.assertEqual(result["output"]["status"], "answered")
        self.assertEqual([x for x, _ in observations].count("claim-evidence"), 2)
        self.assertIn("tavily-search", [x for x, _ in observations])
        root = observations[0][1]
        self.assertEqual(root.update.call_args.kwargs["output"]["candidate_review"]["basis"],
                         "question_and_search_titles_urls_snippets")


if __name__ == "__main__":
    unittest.main()
