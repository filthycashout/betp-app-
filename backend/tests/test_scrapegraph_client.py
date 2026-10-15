from __future__ import annotations

import json

import pytest

import scrapegraph_client as sg


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.content = json.dumps(payload).encode()
        self.is_redirect = 300 <= status_code < 400
        self.text = self.content.decode()

    def json(self):
        return self._payload

    def close(self):
        pass


def test_unconfigured_is_explicit(monkeypatch):
    monkeypatch.delenv("SGAI_API_KEY", raising=False)
    assert sg.configured() is False
    with pytest.raises(sg.ScrapeGraphUnavailable, match="not configured"):
        sg.search("NFL injuries", "Extract factual injuries")


def test_public_url_allowlist_and_ssrf_guards():
    assert sg.validate_public_url("https://www.nfl.com/news/test") == "https://www.nfl.com/news/test"
    assert sg.validate_public_url("https://espn.com/nfl/") == "https://espn.com/nfl/"
    for url in (
        "http://www.nfl.com/news",
        "https://localhost/admin",
        "https://127.0.0.1/admin",
        "https://10.0.0.1/internal",
        "https://example.com/sports",
        "file:///etc/passwd",
    ):
        with pytest.raises(sg.ScrapeGraphPolicyError):
            sg.validate_public_url(url)


def test_search_uses_fixed_api_host_and_returns_evidence_only(monkeypatch):
    monkeypatch.setenv("SGAI_API_KEY", "secret-test-key")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse({"result": [{"title": "Injury report", "url": "https://www.nfl.com/"}]})

    monkeypatch.setattr(sg.requests, "post", fake_post)
    result = sg.search("NFL team injury report", "Extract confirmed pregame availability", num_results=3)
    assert calls[0][0] == "https://v2-api.scrapegraphai.com/api/search"
    assert calls[0][1]["allow_redirects"] is False
    assert calls[0][1]["headers"]["SGAI-APIKEY"] == "secret-test-key"
    assert "secret-test-key" not in json.dumps(calls[0][1]["json"])
    assert result["zero_trust"]["trusted_for_instructions"] is False
    assert result["zero_trust"]["authority"] == "EVIDENCE_ONLY"
    assert result["zero_trust"]["used_in_prediction"] is False
    assert result["zero_trust"]["historical_training_eligible"] is False
    assert len(result["response_sha256"]) == 64


def test_extract_rejects_unapproved_domain_before_network(monkeypatch):
    monkeypatch.setenv("SGAI_API_KEY", "secret-test-key")

    def fail(*args, **kwargs):
        raise AssertionError("network must not be reached")

    monkeypatch.setattr(sg.requests, "post", fail)
    with pytest.raises(sg.ScrapeGraphPolicyError):
        sg.extract("https://evil.example/path", "Extract injuries")


def test_persistent_scrapegraph_operations_are_not_exposed():
    status = sg.status()
    assert status["operations_enabled"] == ["search", "extract", "scrape"]
    assert status["operations_disabled"] == ["crawl", "monitor"]
    assert status["trusted_for_instructions"] is False
