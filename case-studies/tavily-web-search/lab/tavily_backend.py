"""Bounded Tavily Search/Extract calls; credentials never enter returned records."""
import ipaddress
import json
from urllib.parse import urlparse

import httpx

MAX_RESPONSE_BYTES = 2_000_000
MAX_TEXT = 24_000
MAX_SNIPPET = 2_000


def public_https_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (parsed.scheme != "https" or not host or parsed.username or parsed.password
                or parsed.port not in (None, 443) or "." not in host
                or host == "localhost" or host.endswith((".localhost", ".local", ".internal"))):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


class TavilyBackend:
    def __init__(self, api_key, *, max_results=5, timeout=60, transport=None):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("TAVILY_API_KEY is required")
        if not isinstance(max_results, int) or not 1 <= max_results <= 5:
            raise ValueError("This lesson supports 1-5 search results")
        self.max_results = max_results
        self.client = httpx.Client(
            base_url="https://api.tavily.com", timeout=timeout,
            headers={"Authorization": "Bearer " + api_key},
            follow_redirects=False, trust_env=False, transport=transport,
        )

    def close(self):
        self.client.close()

    def _post(self, endpoint, payload):
        # No SDK retries and no raw error body/headers in logs or model messages.
        with self.client.stream("POST", endpoint, json=payload) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ValueError("Tavily response exceeds the configured size limit")
                chunks.append(chunk)
        data = json.loads(b"".join(chunks))
        if not isinstance(data, dict):
            raise ValueError("Tavily returned an invalid response shape")
        return data

    @staticmethod
    def _metadata(data):
        return {key: data[key] for key in ("request_id", "response_time", "usage") if key in data}

    def search(self, query):
        payload = {"query": query, "search_depth": "basic", "max_results": self.max_results,
                   "topic": "general", "include_answer": False, "include_raw_content": False,
                   "include_images": False, "auto_parameters": False, "include_usage": True}
        data = self._post("/search", payload)
        results = data.get("results")
        if not isinstance(results, list):
            raise ValueError("Tavily search results must be an array")
        candidates, skipped, seen = [], [], set()
        for index, result in enumerate(results[:self.max_results], 1):
            if not isinstance(result, dict):
                skipped.append({"result_index": index, "reason": "invalid_result"})
                continue
            url = result.get("url")
            if not public_https_url(url) or url in seen:
                skipped.append({"result_index": index, "reason": "unsupported_or_duplicate_url"})
                continue
            seen.add(url)
            title, snippet = result.get("title"), result.get("content")
            snippet = snippet if isinstance(snippet, str) else ""
            candidates.append({"id": f"search-1-doc-{index}", "title": (title if isinstance(title, str) and title else url)[:500],
                               "url": url, "snippet": snippet[:MAX_SNIPPET],
                               "snippet_truncated": len(snippet) > MAX_SNIPPET,
                               "retrieval_score": result.get("score"),
                               "search_result_rank": index})
        return {"status": "searched", "query": query, "request": payload,
                "candidates": candidates, "skipped_results": skipped,
                "returned_result_count": len(results), **self._metadata(data),
                "evidence_scope": "Search snippets are selection context, not verified page reads."}

    def extract(self, candidate):
        url = candidate["url"]
        if not public_https_url(url):
            raise ValueError("Only public HTTPS search-result URLs may be extracted")
        payload = {"urls": [url], "extract_depth": "basic", "format": "markdown",
                   "include_images": False, "include_usage": True, "timeout": 20}
        data = self._post("/extract", payload)
        results, failed = data.get("results"), data.get("failed_results", [])
        if not isinstance(results, list) or not isinstance(failed, list):
            raise ValueError("Tavily extraction results must be arrays")
        base = {"document_id": candidate["id"], "source_url": url,
                "content_url": url, "backend": "tavily-extract", "request": payload,
                "failed_results": [{"url": x.get("url"),
                                    "error": str(x.get("error", "Extraction failed"))[:500]}
                                   for x in failed if isinstance(x, dict)],
                **self._metadata(data)}
        # HTTP 200 can contain only failures. Never accept an unrelated URL's text.
        match = next((r for r in results if isinstance(r, dict) and r.get("url") == url), None)
        text = match.get("raw_content") if match else None
        if not isinstance(text, str) or not text.strip():
            return {**base, "status": "failed", "error_type": "ExtractionFailed",
                    "text": "", "truncated": False}
        return {**base, "status": "read", "text": text[:MAX_TEXT],
                "returned_text_characters": len(text), "truncated": len(text) > MAX_TEXT,
                "evidence_scope": "Only the extracted text returned to the model is available as evidence."}
