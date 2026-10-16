"""Offline checks: never infer an actual search from citations alone."""
from types import SimpleNamespace
import unittest

from unittest.mock import Mock
from run_builtin import ReasoningSummaryRecorder, SearchTraceRecorder, search_evidence


def response(output, **extra):
    body = {"output": output, **extra}
    return SimpleNamespace(output_text="Example final answer.", model_dump=lambda **_: body)


class SearchEvidenceTests(unittest.TestCase):
    def test_citations_without_call_do_not_verify_search(self):
        result = search_evidence(response([], citations=["https://langfuse.com/docs"]))
        self.assertEqual(result["search_status"], "not_verified")
        self.assertEqual(len(result["source_urls"]), 1)

    def test_failed_call_is_not_a_completed_search(self):
        result = search_evidence(response([
            {"type": "web_search_call", "status": "failed", "id": "failed-search"}
        ]))
        self.assertEqual(result["search_status"], "not_verified")
        self.assertEqual(result["returned_search_calls"][0]["status"], "failed")

    def test_completed_call_and_annotations_preserved_without_reasoning(self):
        result = search_evidence(response([
            {"type": "reasoning", "summary": [{"text": "INTERNAL TEST SENTINEL"}]},
            {"type": "web_search_call", "status": "completed", "id": "search-1",
             "action": {"type": "search", "query": "Langfuse code evaluator network"}},
            {"type": "message", "content": [{"type": "output_text", "annotations": [
                {"type": "url_citation", "url": "https://langfuse.com/docs", "title": "Docs"}
            ]}]},
        ], citations=["https://langfuse.com/docs"]))
        self.assertEqual(result["search_status"], "observed_completed_call")
        self.assertEqual(result["source_urls"], ["https://langfuse.com/docs"])
        self.assertNotIn("INTERNAL TEST SENTINEL", str(result))


class SearchTraceTests(unittest.TestCase):
    def event(self, kind, **fields):
        body = {"type": kind, **fields}
        return SimpleNamespace(model_dump=lambda **_: body)

    def test_separate_search_and_open_calls_remain_sibling_tools(self):
        parent = Mock()
        tools = [Mock(), Mock()]
        parent.start_observation.side_effect = tools
        recorder = SearchTraceRecorder(parent)
        for call_id in ("search-1", "page-1"):
            recorder.record(self.event("response.output_item.added", item={
                "type": "web_search_call", "id": call_id, "status": "in_progress"}))
        recorder.record(self.event("response.output_item.done", item={
            "type": "web_search_call", "id": "search-1", "status": "completed",
            "action": {"type": "search", "query": "official documentation",
                       "sources": [{"url": "https://example.com/docs"}]}}))
        recorder.record(self.event("response.output_item.done", item={
            "type": "web_search_call", "id": "page-1", "status": "failed",
            "action": {"type": "open_page", "url": "https://example.com/docs"}}))
        recorder.close()
        self.assertEqual(parent.start_observation.call_count, 2)
        self.assertEqual(tools[0].end.call_count, 1)
        self.assertEqual(tools[1].end.call_count, 1)
        self.assertIn("official documentation", str(tools[0].update.call_args_list))
        self.assertIn("ERROR", str(tools[1].update.call_args_list))

    def test_interrupted_search_is_not_marked_completed(self):
        parent = Mock()
        recorder = SearchTraceRecorder(parent)
        recorder.record(self.event("response.web_search_call.searching", item_id="search-1"))
        recorder.record(self.event("response.reasoning_text.delta", delta="PRIVATE SENTINEL"))
        recorder.close()
        self.assertEqual(len(recorder.events), 1)
        self.assertNotIn("PRIVATE SENTINEL", str(recorder.events))
        self.assertIn("WARNING", str(parent.start_observation.return_value.update.call_args_list))

    def test_final_only_calls_do_not_claim_execution_timing(self):
        parent = Mock()
        recorder = SearchTraceRecorder(parent)
        recorder.reconcile(response([{"type": "web_search_call", "id": "final-only",
                                      "status": "completed", "action": {"type": "search"}}]))
        metadata = parent.start_observation.call_args.kwargs["metadata"]
        self.assertEqual(metadata["timing_basis"], "final_response_only")
        self.assertFalse(metadata["execution_duration_observed"])


class ReasoningSummaryTests(unittest.TestCase):
    def event(self, kind, **fields):
        return SimpleNamespace(model_dump=lambda **_: {"type": kind, **fields})

    def test_deltas_done_and_final_summary_do_not_duplicate_text(self):
        parent = Mock()
        recorder = ReasoningSummaryRecorder(parent)
        for text in ("Official ", "source."):
            recorder.record(self.event("response.reasoning_summary_text.delta",
                                      item_id="r1", summary_index=0, delta=text))
        recorder.record(self.event("response.reasoning_summary_text.done",
                                  item_id="r1", summary_index=0, text="Official source."))
        recorder.reconcile(response([{"type": "reasoning", "id": "r1", "summary": [
            {"type": "summary_text", "text": "Official source."}],
            "encrypted_content": "NEVER_LOG_THIS"}]))
        recorder.close()
        self.assertEqual(len(recorder.summaries), 1)
        self.assertEqual(recorder.summaries[0]["text"], "Official source.")
        self.assertNotIn("NEVER_LOG_THIS", str(parent.mock_calls))
        self.assertEqual(parent.start_observation.return_value.end.call_count, 1)

    def test_reasoning_text_events_and_final_only_sections_are_supported(self):
        recorder = ReasoningSummaryRecorder(Mock())
        recorder.record(self.event("response.reasoning_text.delta", item_id="r1",
                                  content_index=0, delta="Check current documentation."))
        recorder.reconcile(response([{"type": "reasoning", "id": "r2", "summary": [
            {"type": "summary_text", "text": "A separate disclosed summary."}]}]))
        self.assertEqual(len(recorder.summaries), 2)
        self.assertEqual(recorder.summaries[1]["origin"], "final_response")

    def test_missing_summary_is_not_inferred_from_search_or_ciphertext(self):
        parent = Mock()
        recorder = ReasoningSummaryRecorder(parent)
        recorder.reconcile(response([
            {"type": "web_search_call", "action": {"type": "open_page", "url": "https://example.com"}},
            {"type": "reasoning", "id": "r1", "summary": [], "encrypted_content": "HIDDEN"}]))
        self.assertEqual(recorder.summaries, [])
        parent.start_observation.assert_not_called()
        recorder.close()
        self.assertEqual(parent.start_observation.call_args.kwargs["output"]["status"],
                         "not_returned")


if __name__ == "__main__":
    unittest.main()
