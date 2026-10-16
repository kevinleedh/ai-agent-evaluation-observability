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

    if (
        isinstance(output, dict)
        and output.get("backend") == "tavily-search-extract"
        and output.get("status") == "failed"
    ):
        raise ValueError(
            "Execution failed; leave answer-quality scoring unassigned."
        )

    required = (
        "search_result", "candidates", "candidate_review",
        "read_documents", "claim_evidence",
        "search_attempts", "read_attempts", "status",
    )

    if (
        not isinstance(inputs, dict)
        or not isinstance(output, dict)
        or output.get("backend") != "tavily-search-extract"
        or not isinstance(inputs.get("budgets"), dict)
        or any(key not in output for key in required)
    ):
        raise ValueError(
            "Select the original terminal-tavily-web-search root."
        )

    search = output["search_result"]

    if output["status"] == "failed" or (
        isinstance(search, dict) and search.get("status") == "failed"
    ):
        raise ValueError(
            "Execution/search failed; leave answer-quality scoring unassigned."
        )

    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    def rows(value, label):
        if not isinstance(value, list) or not all(
            isinstance(x, dict) for x in value
        ):
            errors.append(label + " must be an array of objects.")
            return []
        return value

    def count(value):
        return type(value) is int and value >= 0

    # 1. Check configured search/read budgets.
    budgets = inputs["budgets"]
    search_limit = budgets.get("max_search_attempts")
    result_limit = budgets.get("max_results")
    read_limit = budgets.get("max_read_attempts")

    if not (
        type(search_limit) is int and search_limit == 1
        and type(result_limit) is int and 1 <= result_limit <= 5
        and type(read_limit) is int and 1 <= read_limit <= 2
    ):
        raise ValueError(
            "Unsupported budgets: expected one search, 1-5 results, 1-2 reads."
        )

    check(nonempty(inputs.get("question")), "Question is empty.")

    # 2. Check the recorded search request and result.
    search = search if isinstance(search, dict) else {}

    check(
        search.get("status") == "searched",
        "No successful search snapshot.",
    )
    check(
        all(
            nonempty(search.get(k))
            for k in ("query", "search_reason", "information_needed")
        ),
        "Search query, reason or intended information is missing.",
    )
    check(
        count(output["search_attempts"])
        and output["search_attempts"] == search_limit,
        "Search attempt count is invalid.",
    )

    request = search.get("request")
    request = request if isinstance(request, dict) else {}

    check(
        request.get("query") == search.get("query")
        and request.get("max_results") == result_limit,
        "Search request does not match the recorded query/budget.",
    )

    candidates = rows(output["candidates"], "Candidates")

    check(
        search.get("candidates") == output["candidates"],
        "Candidate snapshots differ.",
    )
    check(len(candidates) <= result_limit, "Too many candidates.")

    raw_count = search.get("returned_result_count")
    check(
        count(raw_count) and len(candidates) <= raw_count <= result_limit,
        "Returned result count is inconsistent.",
    )

    candidate_ids = [c.get("id") for c in candidates]

    check(
        all(nonempty(x) for x in candidate_ids)
        and len(set(map(str, candidate_ids))) == len(candidate_ids),
        "Candidate IDs are missing or duplicated.",
    )

    urls = {
        c["id"]: c.get("url")
        for c in candidates
        if nonempty(c.get("id"))
    }

    check(
        all(
            nonempty(c.get("title")) and nonempty(c.get("url"))
            for c in candidates
        ),
        "Candidate title or URL is empty.",
    )

    # 3. Every candidate needs exactly one select/exclude decision.
    review = output["candidate_review"]
    review = review if isinstance(review, dict) else {}
    decisions = rows(review.get("decisions"), "Decisions")
    decision_ids = [d.get("document_id") for d in decisions]

    check(
        all(nonempty(x) for x in decision_ids)
        and len(decision_ids) == len(candidate_ids)
        and sorted(map(str, decision_ids)) == sorted(map(str, candidate_ids)),
        "Every candidate needs exactly one decision.",
    )

    selected = set()

    for decision in decisions:
        check(
            decision.get("decision") in ("select", "exclude")
            and nonempty(decision.get("reason")),
            "Invalid decision or missing selection/exclusion reason.",
        )

        if decision.get("decision") == "select":
            check(
                nonempty(decision.get("information_needed")),
                "Selected document lacks intended information.",
            )
            if nonempty(decision.get("document_id")):
                selected.add(decision["document_id"])

    check(len(selected) <= read_limit, "Too many selected documents.")

    # 4. Read records must refer to selected search-result documents.
    reads = rows(output["read_documents"], "Reads")

    check(
        count(output["read_attempts"])
        and output["read_attempts"] == len(reads) <= read_limit,
        "Read attempt count or budget is invalid.",
    )

    documents = {}
    seen_reads = set()

    for read in reads:
        doc_id = read.get("document_id")

        if not nonempty(doc_id):
            errors.append("Read document ID is missing.")
            continue

        check(
            doc_id in selected and doc_id in urls,
            "Read source was not selected from search results.",
        )
        check(doc_id not in seen_reads, "Duplicate extraction attempt.")
        seen_reads.add(doc_id)

        check(
            nonempty(read.get("selection_reason"))
            and nonempty(read.get("information_needed")),
            "Read reason or intended information is missing.",
        )
        check(
            read.get("source_url") == urls.get(doc_id),
            "Read source URL mismatch.",
        )
        check(
            read.get("status") in ("read", "failed"),
            "Invalid read status.",
        )

        # Failed reads are allowed as records, but cannot become evidence.
        if read.get("status") == "read":
            check(
                nonempty(read.get("text")),
                "Successful read has no text.",
            )

            extraction = read.get("request")
            check(
                isinstance(extraction, dict)
                and extraction.get("urls") == [urls.get(doc_id)],
                "Extraction request URL mismatch.",
            )

            if nonempty(read.get("text")):
                documents[doc_id] = (
                    normalize(read["text"]),
                    read.get("source_url"),
                )

    # 5. Check final status and claim structure.
    claims = rows(output["claim_evidence"], "Claims")

    check(
        output["status"] in ("answered", "abstained"),
        "Invalid final status.",
    )
    check(nonempty(output.get("answer")), "Final answer is empty.")
    check(len(claims) <= 12, "Too many claims.")

    if output["status"] == "answered":
        check(bool(claims), "Answered result has no claims.")
    else:
        check(
            not claims and nonempty(output.get("limitations")),
            "Abstention needs no claims and an explanation.",
        )

    # 6. Recheck quote presence instead of trusting validation flags.
    seen_claims = set()
    quotes_checked = 0
    rendered = []

    for claim in claims:
        claim_id = claim.get("claim_id")

        check(
            nonempty(claim_id) and str(claim_id) not in seen_claims,
            "Claim ID is missing or duplicated.",
        )
        seen_claims.add(str(claim_id))

        check(nonempty(claim.get("claim")), "Claim text is empty.")

        evidence = rows(claim.get("evidence"), "Evidence")
        check(bool(evidence), f"{claim_id}: no evidence.")
        links = []

        for entry in evidence:
            doc_id = entry.get("document_id")
            quote = entry.get("quote")
            document = (
                documents.get(doc_id)
                if isinstance(doc_id, str)
                else None
            )

            check(
                document is not None,
                f"{claim_id}: evidence references an unread/failed source.",
            )
            check(
                nonempty(quote) and 12 <= len(quote.strip()) <= 1500,
                f"{claim_id}: quote must be 12-1500 characters.",
            )

            if document is not None:
                check(
                    nonempty(quote) and normalize(quote) in document[0],
                    f"{claim_id}: quote not found in returned text.",
                )
                check(
                    entry.get("source_url") == document[1],
                    f"{claim_id}: evidence URL mismatch.",
                )
                quotes_checked += 1

            links.append(f"[{doc_id}]({entry.get('source_url')})")

        if nonempty(claim.get("claim")):
            rendered.append(
                "- " + claim["claim"].strip()
                + " " + " ".join(dict.fromkeys(links))
            )

    # 7. Check consistency with this runner's final-answer renderer.
    if output["status"] == "answered" and nonempty(output.get("answer")):
        check(
            normalize(output["answer"])
            == normalize("\n\n".join(rendered)),
            "Final answer differs from the accepted claims/source links.",
        )

    if errors:
        comment = "; ".join(dict.fromkeys(errors))
    else:
        comment = (
            f"Root snapshot checks passed: {len(candidates)} candidates, "
            f"{len(decisions)} decisions, {len(reads)} read attempts, "
            f"{len(claims)} claims, {quotes_checked} quotes. "
            f"Status: {output['status']}. "
            "Semantic support, model-call count, action order and "
            "sibling execution records were not evaluated."
        )

    return EvaluationResult(scores=[
        Score(
            name="code_tavily_trace_integrity",
            value=not errors,
            data_type="BOOLEAN",
            comment=comment,
        )
    ])