"""Candidate decisions and verifiable quote links for document review."""


def function(name, description, properties, required):
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False}}


REVIEW_TOOL = function("review_candidates", "Select or exclude EVERY candidate before reading any document.", {
    "decisions": {"type": "array", "items": {"type": "object", "properties": {
        "document_id": {"type": "string"},
        "decision": {"type": "string", "enum": ["select", "exclude"]},
        "reason": {"type": "string"}, "information_needed": {"type": "string"},
    }, "required": ["document_id", "decision", "reason", "information_needed"],
        "additionalProperties": False}}}, ["decisions"])

SUBMIT_TOOL = function("submit_answer", "Submit English claims with verbatim supporting quotes from successfully read documents.", {
    "claims": {"type": "array", "items": {"type": "object", "properties": {
        "claim_id": {"type": "string"}, "claim": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "object", "properties": {
            "document_id": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["document_id", "quote"], "additionalProperties": False}},
    }, "required": ["claim_id", "claim", "evidence"], "additionalProperties": False}},
    "limitations": {"type": "string"},
}, ["claims", "limitations"])


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate_review(arguments, candidates):
    decisions = arguments.get("decisions") if isinstance(arguments, dict) else None
    if not isinstance(decisions, list):
        raise ValueError("Provide a decisions array covering every candidate")
    known = {doc["id"] for doc in candidates}
    seen = set()
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError("Each decision must be an object")
        doc_id = decision.get("document_id")
        if not isinstance(doc_id, str) or doc_id not in known or doc_id in seen:
            raise ValueError("Candidate IDs must be known and appear exactly once")
        seen.add(doc_id)
        if decision.get("decision") not in ("select", "exclude") or not nonempty(decision.get("reason")):
            raise ValueError("Each candidate needs a select/exclude decision and a reason")
        if decision["decision"] == "select" and not nonempty(decision.get("information_needed")):
            raise ValueError("Selected candidates need information_needed")
    if seen != known:
        raise ValueError("Missing candidate decisions; review every candidate")
    return {"decisions": decisions, "basis": "question_and_candidate_titles_urls",
            "reason_kind": "model_declared_before_fetch"}


def validate_answer(arguments, read_documents):
    if not isinstance(arguments, dict) or not isinstance(arguments.get("claims"), list):
        raise ValueError("Provide a claims array")
    claims = arguments["claims"]
    limitations = arguments.get("limitations")
    if not isinstance(limitations, str) or (not claims and not limitations.strip()):
        raise ValueError("Provide limitations; an empty answer needs an abstention reason")
    if len(claims) > 12:
        raise ValueError("Use at most 12 concise claims")
    documents = {d["document_id"]: d for d in read_documents if d.get("status") == "read"}
    verified, seen = [], set()
    for claim in claims:
        if not isinstance(claim, dict) or not nonempty(claim.get("claim_id")) or not nonempty(claim.get("claim")):
            raise ValueError("Each claim needs claim_id and claim text")
        if claim["claim_id"] in seen:
            raise ValueError("Claim IDs must be unique")
        seen.add(claim["claim_id"])
        evidence = claim.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("Every claim needs at least one supporting quote")
        links = []
        for entry in evidence:
            if not isinstance(entry, dict) or not isinstance(entry.get("document_id"), str):
                raise ValueError("Evidence needs a document ID")
            document = documents.get(entry["document_id"])
            quote = entry.get("quote")
            if document is None:
                raise ValueError("Evidence can reference only successfully read documents")
            if not nonempty(quote) or not 12 <= len(quote.strip()) <= 1500:
                raise ValueError("Use a verbatim quote between 12 and 1500 characters")
            normalized = " ".join(quote.split())
            if normalized not in " ".join(document["text"].split()):
                raise ValueError("Quote not found in the retrieved text; copy an exact passage without ellipses")
            links.append({"document_id": entry["document_id"], "source_url": document["source_url"],
                          "quote": quote.strip(), "quote_verified": True,
                          "match_method": "whitespace_normalized_substring",
                          "claim_support_evaluated": False})
        verified.append({"claim_id": claim["claim_id"], "claim": claim["claim"].strip(), "evidence": links})
    lines = ["- " + c["claim"] + " " + " ".join(dict.fromkeys(
        "[" + e["document_id"] + "](" + e["source_url"] + ")" for e in c["evidence"])) for c in verified]
    # Only accepted evidence-linked claims become final answer prose. Scope notes
    # stay separate, since they might themselves contain unverified factual text.
    if not verified and limitations.strip():
        lines.append("Limitations: " + limitations.strip())
    return {"answer": "\n\n".join(lines), "claim_evidence": verified,
            "limitations": limitations.strip(), "quote_checks_passed": True,
            "claim_support_evaluated": False,
            "status": "answered" if verified else "abstained"}
