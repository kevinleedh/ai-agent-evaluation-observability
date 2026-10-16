"""Standard-library-only tests; no model, Tavily, or Langfuse requests."""
import copy
import json
from types import SimpleNamespace
import unittest

from langfuse_tavily_code_evaluator import evaluate

URL = "https://example.com/docs"
QUOTE = "The caller executes the custom function locally."


def fixture():
    candidate = {"id": "d1", "title": "Official documentation", "url": URL, "snippet": QUOTE}
    claim = {"claim_id": "c1", "claim": "The caller executes custom functions locally.",
             "evidence": [{"document_id": "d1", "source_url": URL, "quote": QUOTE}]}
    return {"input": {"question": "Who executes custom functions?", "budgets": {
                "max_search_attempts": 1, "max_results": 5, "max_read_attempts": 2, "max_model_calls": 10}},
            "output": {"backend": "tavily-search-extract", "status": "answered",
                "search_attempts": 1, "read_attempts": 1, "candidates": [candidate],
                "search_result": {"status": "searched", "query": "official function calling",
                    "search_reason": "Find execution ownership.", "information_needed": "Who runs the function.",
                    "request": {"query": "official function calling", "max_results": 5},
                    "candidates": [copy.deepcopy(candidate)], "returned_result_count": 1},
                "candidate_review": {"decisions": [{"document_id": "d1", "decision": "select",
                    "reason": "Relevant official explanation.", "information_needed": "Execution owner."}]},
                "read_documents": [{"document_id": "d1", "selection_reason": "Verify execution ownership.",
                    "information_needed": "Who runs the function.", "source_url": URL, "status": "read",
                    "request": {"urls": [URL]}, "text": QUOTE}],
                "claim_evidence": [claim], "limitations": "",
                "answer": "- " + claim["claim"] + " [d1](" + URL + ")"}}


def run(data, serialized=False):
    inp, out = data["input"], data["output"]
    if serialized:
        inp, out = json.dumps(inp), json.dumps(out)
    return evaluate(SimpleNamespace(observation=SimpleNamespace(input=inp, output=out))).scores[0]


class EvaluatorTests(unittest.TestCase):
    def test_positive(self):
        result = run(fixture())
        self.assertTrue(result.value)
        self.assertEqual(result.name, "code_tavily_trace_integrity")
        self.assertEqual(result.data_type, "BOOLEAN")
        self.assertIn("1 quotes", result.comment)
        self.assertIn("action order", result.comment)

    def test_serialized_io(self):
        self.assertTrue(run(fixture(), serialized=True).value)

    def test_empty_search_results_can_abstain(self):
        data = fixture()
        out = data["output"]
        out.update(status="abstained", candidates=[], read_documents=[], read_attempts=0,
                   claim_evidence=[], answer="Limitations: No results.", limitations="No results.")
        out["search_result"].update(candidates=[], returned_result_count=0)
        out["candidate_review"]["decisions"] = []
        self.assertTrue(run(data).value)

    def test_failed_unused_read_does_not_invalidate_other_successful_evidence(self):
        data = fixture()
        out = data["output"]
        candidate = {"id": "d2", "title": "Second document", "url": "https://example.org/docs"}
        out["candidates"].append(candidate)
        out["search_result"]["candidates"].append(copy.deepcopy(candidate))
        out["search_result"]["returned_result_count"] = 2
        out["candidate_review"]["decisions"].append({"document_id": "d2", "decision": "select",
            "reason": "Seek a second source.", "information_needed": "Execution owner."})
        out["read_documents"].append({"document_id": "d2", "status": "failed",
            "source_url": candidate["url"], "selection_reason": "Seek corroboration.",
            "information_needed": "Execution owner."})
        out["read_attempts"] = 2
        self.assertTrue(run(data).value)

    def test_self_reported_validation_flags_are_ignored(self):
        data = fixture()
        data["output"].update(quote_checks_passed=False, claim_support_evaluated=False)
        self.assertTrue(run(data).value)

    def test_wrong_target_is_unscored(self):
        data = fixture()
        data["output"]["backend"] = "other"
        with self.assertRaises(ValueError):
            run(data)

    def test_failed_execution_is_unscored_even_with_missing_final_fields(self):
        data = fixture()
        data["output"] = {"backend": "tavily-search-extract", "status": "failed"}
        with self.assertRaisesRegex(ValueError, "Execution failed"):
            run(data)

    def test_failed_search_is_unscored(self):
        data = fixture()
        data["output"]["search_result"]["status"] = "failed"
        with self.assertRaises(ValueError):
            run(data)

    def test_known_corruptions_are_false(self):
        # Every mutation begins with a fresh positive example.
        mutations = [
            ("empty_query", lambda o: o["search_result"].update(query="")),
            ("empty_search_reason", lambda o: o["search_result"].update(search_reason="")),
            ("missing_decision", lambda o: o["candidate_review"].update(decisions=[])),
            ("duplicate_decision", lambda o: o["candidate_review"]["decisions"].append(copy.deepcopy(o["candidate_review"]["decisions"][0]))),
            ("unknown_selected_id", lambda o: o["candidate_review"]["decisions"][0].update(document_id="invented")),
            ("read_excluded_source", lambda o: o["candidate_review"]["decisions"][0].update(decision="exclude")),
            ("read_url_mismatch", lambda o: o["read_documents"][0].update(source_url="https://example.org/other")),
            ("read_reason_missing", lambda o: o["read_documents"][0].update(selection_reason="")),
            ("wrong_extract_request", lambda o: o["read_documents"][0].update(request={"urls": ["https://example.org/other"]})),
            ("failed_read_quoted", lambda o: o["read_documents"][0].update(status="failed")),
            ("empty_successful_read", lambda o: o["read_documents"][0].update(text="")),
            ("duplicate_read", lambda o: o["read_documents"].append(copy.deepcopy(o["read_documents"][0]))),
            ("search_budget_exceeded", lambda o: o.update(search_attempts=2)),
            ("read_count_mismatch", lambda o: o.update(read_attempts=2)),
            ("invented_quote", lambda o: o["claim_evidence"][0]["evidence"][0].update(quote="This text was never returned by Extract.")),
            ("quote_too_short", lambda o: o["claim_evidence"][0]["evidence"][0].update(quote="The")),
            ("quote_too_long", lambda o: o["claim_evidence"][0]["evidence"][0].update(quote="a" * 1501)),
            ("quote_uses_unread_id", lambda o: o["claim_evidence"][0]["evidence"][0].update(document_id="d2")),
            ("evidence_url_mismatch", lambda o: o["claim_evidence"][0]["evidence"][0].update(source_url="https://example.org/other")),
            ("empty_evidence", lambda o: o["claim_evidence"][0].update(evidence=[])),
            ("malformed_evidence", lambda o: o["claim_evidence"][0].update(evidence=[None])),
            ("malformed_candidates", lambda o: o.update(candidates=[None])),
            ("changed_answer", lambda o: o.update(answer="The provider always runs custom functions.")),
            ("empty_answer", lambda o: o.update(answer="")),
            ("answered_without_claims", lambda o: o.update(claim_evidence=[])),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name):
                data = fixture()
                mutate(data["output"])
                self.assertFalse(run(data).value)

    def test_semantically_false_claim_with_real_quote_can_still_pass(self):
        data = fixture()
        claim = data["output"]["claim_evidence"][0]
        claim["claim"] = "The provider executes custom functions on its own servers."
        data["output"]["answer"] = "- " + claim["claim"] + " [d1](" + URL + ")"
        self.assertTrue(run(data).value)


if __name__ == "__main__":
    unittest.main()
