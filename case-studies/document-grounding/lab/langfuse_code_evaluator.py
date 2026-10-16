"""Paste this entire file into Langfuse's Python Code evaluator editor.

Target: terminal-python-document-review, root observations with the v2 output schema.
The root records metadata.prompt_version=2; do not require root version=2.
Uses only the selected root's input/output snapshot, not sibling observations.
"""
import json
from dataclasses import dataclass


@dataclass
class Score:
    name: str
    value: bool
    data_type: str
    comment: str


@dataclass
class EvaluationResult:
    scores: list


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def normalize(value):
    return " ".join(value.split())


def evaluate(ctx):
    inputs = decode(ctx.observation.input)
    output = decode(ctx.observation.output)
    if not isinstance(inputs, dict) or not isinstance(output, dict):
        raise ValueError("Select a document-review root with JSON input/output.")
    if output.get("status") == "failed":
        raise ValueError("Execution failed; leave answer-quality scoring unassigned.")
    required = ("candidate_review", "read_documents", "claim_evidence", "status")
    if "candidates" not in inputs or any(key not in output for key in required):
        raise ValueError("Missing v2 root data. Select a terminal-python-document-review root with v2 output fields.")

    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    candidates = inputs["candidates"]
    decisions = output["candidate_review"].get("decisions", [])
    reads = output["read_documents"]
    claims = output["claim_evidence"]
    if not all(isinstance(value, list) for value in (candidates, decisions, reads, claims)):
        raise ValueError("Expected candidate, decision, read and claim arrays.")

    candidate_ids = [d.get("id") for d in candidates]
    decision_ids = [d.get("document_id") for d in decisions]
    if not all(nonempty(value) for value in candidate_ids + decision_ids):
        raise ValueError("Candidate and decision IDs must be nonempty strings.")
    check(bool(candidates) and len(set(candidate_ids)) == len(candidate_ids),
          "Candidate IDs are empty or duplicated.")
    check(len(decision_ids) == len(candidate_ids) and set(decision_ids) == set(candidate_ids),
          "Every candidate must have exactly one decision.")
    for decision in decisions:
        check(decision.get("decision") in ("select", "exclude") and nonempty(decision.get("reason")),
              "A candidate has an invalid decision or empty reason.")
        if decision.get("decision") == "select":
            check(nonempty(decision.get("information_needed")), "A selected candidate has no intended information.")

    selected = {d["document_id"] for d in decisions if d.get("decision") == "select"}
    urls = {d["id"]: d.get("url") for d in candidates}
    documents = {}
    for read in reads:
        doc_id = read.get("document_id")
        if not isinstance(doc_id, str):
            raise ValueError("Read document IDs must be strings.")
        check(doc_id in selected, "A read document was not selected.")
        check(nonempty(read.get("selection_reason")) and nonempty(read.get("information_needed")),
              "A read document has no reason or intended information.")
        check(read.get("source_url") == urls.get(doc_id), "A read source URL differs from its candidate URL.")
        successful = read.get("status") == "read" and nonempty(read.get("text"))
        check(successful, "A recorded read is unsuccessful or has empty text.")
        if successful:
            documents[doc_id] = (normalize(read["text"]), read.get("source_url"))

    status = output["status"]
    check(status in ("answered", "abstained"), "Invalid final status.")
    check(nonempty(output.get("answer")), "Final answer is empty.")
    if status == "answered":
        check(bool(claims), "An answered result contains no claims.")
    if status == "abstained":
        check(not claims and nonempty(output.get("limitations")), "Abstention contains claims or has no explanation.")

    claim_ids = [claim.get("claim_id") for claim in claims]
    check(all(nonempty(value) for value in claim_ids)
          and len(set(str(value) for value in claim_ids)) == len(claim_ids),
          "Claim IDs are missing or duplicated.")
    quotes_checked = 0
    for claim in claims:
        claim_id = claim.get("claim_id", "unknown")
        check(nonempty(claim.get("claim")), f"{claim_id}: empty claim text.")
        evidence = claim.get("evidence")
        check(isinstance(evidence, list) and bool(evidence), f"{claim_id}: no evidence.")
        for entry in evidence if isinstance(evidence, list) else []:
            doc_id = entry.get("document_id")
            document = documents.get(doc_id) if isinstance(doc_id, str) else None
            if document is None:
                errors.append(f"{claim_id}: evidence references an unread document.")
                continue
            quote = entry.get("quote")
            check(nonempty(quote) and normalize(quote) in document[0], f"{claim_id}: quote not found in retrieved text.")
            check(entry.get("source_url") == document[1], f"{claim_id}: evidence URL mismatch.")
            quotes_checked += 1

    comment = "; ".join(dict.fromkeys(errors)) if errors else (
        f"Root snapshot checks passed: {len(decisions)} decisions, {len(reads)} reads, "
        f"{len(claims)} claims, {quotes_checked} quotes checked. Status: {status}. "
        "Semantic support and sibling tool execution records were not evaluated."
    )
    return EvaluationResult(scores=[Score(
        name="code_trace_integrity", value=not errors,
        data_type="BOOLEAN", comment=comment,
    )])
