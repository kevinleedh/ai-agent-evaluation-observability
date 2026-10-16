"""Offline checks of the same root-snapshot evaluator used in Langfuse.

The public fixtures contain source excerpts, not complete raw trace exports.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from langfuse_code_evaluator import evaluate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def fixture(name="function-calling"):
    return json.loads((FIXTURES / (name + ".json")).read_text())


def run(data, serialized=False):
    inputs, output = data["input"], data["output"]
    if serialized:
        inputs, output = json.dumps(inputs), json.dumps(output)
    ctx = SimpleNamespace(observation=SimpleNamespace(input=inputs, output=output))
    return evaluate(ctx).scores[0]


class HostedEvaluatorTests(unittest.TestCase):
    def test_positive_snapshot_checks_four_quotes(self):
        result = run(fixture())
        self.assertTrue(result.value)
        self.assertEqual(result.data_type, "BOOLEAN")
        self.assertIn("4 quotes checked", result.comment)
        self.assertIn("Semantic support and sibling", result.comment)

    def test_serialized_input_and_output(self):
        self.assertTrue(run(fixture(), serialized=True).value)

    def test_abstention_is_not_a_weather_verification(self):
        result = run(fixture("weather-abstention"))
        self.assertTrue(result.value)
        self.assertIn("0 quotes checked. Status: abstained", result.comment)

    def test_missing_candidate_decision(self):
        data = fixture()
        data["output"]["candidate_review"]["decisions"].pop()
        self.assertFalse(run(data).value)

    def test_duplicate_candidate_decision(self):
        data = fixture()
        decisions = data["output"]["candidate_review"]["decisions"]
        decisions[-1] = copy.deepcopy(decisions[0])
        self.assertFalse(run(data).value)

    def test_missing_declared_information(self):
        data = fixture()
        data["output"]["read_documents"][0]["information_needed"] = " "
        self.assertFalse(run(data).value)

    def test_invented_quote_despite_self_reported_verified_flag(self):
        data = fixture()
        entry = data["output"]["claim_evidence"][0]["evidence"][0]
        entry["quote"] = "This sentence never appeared in the retrieved document."
        self.assertTrue(entry["quote_verified"])
        result = run(data)
        self.assertFalse(result.value)
        self.assertIn("quote not found", result.comment)

    def test_unread_source(self):
        data = fixture()
        data["output"]["claim_evidence"][0]["evidence"][0]["document_id"] = "citations"
        self.assertFalse(run(data).value)

    def test_empty_evidence(self):
        data = fixture()
        data["output"]["claim_evidence"][0]["evidence"] = []
        self.assertFalse(run(data).value)

    def test_wrong_source_url(self):
        data = fixture()
        data["output"]["claim_evidence"][0]["evidence"][0]["source_url"] = "https://example.invalid/"
        self.assertFalse(run(data).value)

    def test_failed_execution_is_unscored(self):
        data = fixture()
        data["output"]["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "leave answer-quality scoring unassigned"):
            run(data)

    def test_semantically_false_claim_can_pass_presence_checks(self):
        data = fixture()
        data["output"]["claim_evidence"][2]["claim"] = (
            "The model provider executes every custom function on its own servers."
        )
        data["output"]["answer"] = "\n".join(
            c["claim"] for c in data["output"]["claim_evidence"]
        )
        self.assertTrue(run(data).value)
        # This deliberately demonstrates the boundary; no LLM judgment is simulated.


if __name__ == "__main__":
    unittest.main()
