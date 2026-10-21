"""Hermetic spider tests: mock responses, no external website calls."""
from __future__ import annotations

import asyncio
import csv
import json

import pytest

from sports_ai.crawling import SpiderRunner, SpiderSpec
from sports_ai.crawling.engine import FetchResponse
from sports_ai.crawling.spec import SpiderPolicyError, normalize_link


ROOT = "https://example.org"


def spec(**overrides):
    payload = {
        "name": "test_spider",
        "start_urls": [f"{ROOT}/blog"],
        "allowed_hosts": ["example.org"],
        "item_selector": "article",
        "follow_selector": "a[href]",
        "fields": {
            "title": "h2",
            "author": ".author",
            "published_at": {"selector": "time", "attribute": "datetime"},
            "tags": {"selector": ".tag", "multiple": True},
        },
        "required_fields": ["title"],
        "max_pages": 10,
        "max_depth": 3,
        "max_items": 10,
        "concurrency": 4,
        "request_delay_seconds": 0,
        "retries": 1,
    }
    payload.update(overrides)
    return SpiderSpec.from_dict(payload)


class FakeFetcher:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    async def fetch(self, url, max_bytes):
        self.calls.append(url)
        item = self.mapping.get(url)
        if isinstance(item, list):
            response = item.pop(0)
        else:
            response = item
        if response is None:
            return FetchResponse(status=404, body=b"")
        if isinstance(response, FetchResponse):
            return response
        return FetchResponse(status=200, body=str(response).encode(), content_type="text/html")


HTML1 = """<html><body><article><h2>First story</h2><span class='author'>Jane Doe</span>
<time datetime='2026-10-21'>today</time><b class='tag'>NBA</b><b class='tag'>injuries</b></article>
<a href='/blog/2#top'>Next</a><a href='https://other.net/secret'>Foreign</a>
<a href='http://example.org/insecure'>Insecure</a><a href='/blog'>Self</a></body></html>"""
HTML2 = "<article><h2>Second story</h2><span class='author'>Sam</span></article>"


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("fmt,extension", [("jsonl", "jsonl"), ("json", "json"), ("csv", "csv")])
def test_two_pages_follow_links_and_export(tmp_path, fmt, extension):
    fetcher = FakeFetcher({f"{ROOT}/blog": HTML1, f"{ROOT}/blog/2": HTML2})
    output = tmp_path / f"out.{extension}"
    stats = run(SpiderRunner(spec(), fetcher=fetcher).run(output, fmt))
    assert stats.extracted == 2
    assert stats.visited == 2
    assert f"{ROOT}/blog/2" in fetcher.calls
    assert all("other.net" not in url and "insecure" not in url for url in fetcher.calls)
    if fmt == "jsonl":
        records = [json.loads(line) for line in output.read_text().splitlines()]
    elif fmt == "json":
        records = json.loads(output.read_text())
    else:
        with output.open(newline="") as f:
            records = list(csv.DictReader(f))
    assert {item["title"] for item in records} == {"First story", "Second story"}
    first = next(item for item in records if item["title"] == "First story")
    assert first["author"] == "Jane Doe"
    assert first["historical_training_eligible"] in (False, "False")
    assert first["used_in_prediction"] in (False, "False")
    assert len(first["content_sha256"]) == 64
    if fmt == "csv":
        assert json.loads(first["tags"]) == ["NBA", "injuries"]
    else:
        assert first["tags"] == ["NBA", "injuries"]


def test_robots_disallow_blocks_pages(tmp_path):
    fetcher = FakeFetcher({f"{ROOT}/robots.txt": "User-agent: *\nDisallow: /blog\n", f"{ROOT}/blog": HTML1})
    stats = run(SpiderRunner(spec(), fetcher=fetcher).run(tmp_path / "blocked.jsonl"))
    assert stats.extracted == 0
    assert stats.refused_by_robots == 1
    assert f"{ROOT}/blog" not in fetcher.calls


def test_robots_retrieval_fails_closed(tmp_path):
    fetcher = FakeFetcher({f"{ROOT}/robots.txt": FetchResponse(status=403, body=b"")})
    stats = run(SpiderRunner(spec(), fetcher=fetcher).run(tmp_path / "blocked.jsonl"))
    assert stats.refused_by_robots == 1
    assert stats.visited == 0


def test_page_cap_prevents_unbounded_traversal(tmp_path):
    fetcher = FakeFetcher({f"{ROOT}/blog": HTML1, f"{ROOT}/blog/2": HTML2})
    stats = run(SpiderRunner(spec(max_pages=1), fetcher=fetcher).run(tmp_path / "capped.jsonl"))
    assert stats.queued == 1
    assert stats.visited == 1
    assert stats.extracted == 1


def test_retries_503_then_succeeds(tmp_path):
    fetcher = FakeFetcher({f"{ROOT}/blog": [FetchResponse(status=503, body=b""),
                                          FetchResponse(status=200, body=HTML2.encode(), content_type="text/html")]})
    stats = run(SpiderRunner(spec(), fetcher=fetcher, sleep=lambda _: asyncio.sleep(0)).run(tmp_path / "retry.jsonl"))
    assert stats.extracted == 1
    assert fetcher.calls.count(f"{ROOT}/blog") == 2


def test_non_html_not_parsed(tmp_path):
    fetcher = FakeFetcher({f"{ROOT}/blog": FetchResponse(status=200, body=b"<article><h2>x</h2></article>", content_type="application/pdf")})
    stats = run(SpiderRunner(spec(), fetcher=fetcher).run(tmp_path / "out.jsonl"))
    assert stats.non_html_pages == 1
    assert stats.extracted == 0


@pytest.mark.parametrize("url", [
    "http://example.org/", "https://localhost/", "https://127.0.0.1/",
    "https://169.254.169.254/", "https://example.org:8080/",
    "https://user:pass@example.org/", "file:///etc/passwd", "https://evil.example/path",
])
def test_disallowed_urls_are_rejected(url):
    with pytest.raises(SpiderPolicyError):
        SpiderSpec.from_dict({
            "name": "bad", "start_urls": [url], "allowed_hosts": ["example.org", "localhost", "127.0.0.1", "169.254.169.254"],
            "item_selector": "article", "fields": {"title": "h1"},
        })


def test_link_normalization_rejects_fragments_external_hosts_and_scripts():
    hosts = frozenset({"example.org"})
    assert normalize_link(f"{ROOT}/a", "/b#top", hosts) == f"{ROOT}/b"
    assert normalize_link(f"{ROOT}/a", "javascript:alert(1)", hosts) is None
    assert normalize_link(f"{ROOT}/a", "https://other.net/x", hosts) is None


def test_invalid_css_selector_rejected():
    with pytest.raises(SpiderPolicyError, match="invalid CSS"):
        spec(item_selector="article[")


def test_required_field_name_must_exist():
    with pytest.raises(SpiderPolicyError):
        spec(required_fields=["nonexistent"])


def test_domain_approved_explicitly_no_suffix_wildcards():
    with pytest.raises(SpiderPolicyError):
        spec(start_urls=["https://blog.example.org/blog"])


def test_empty_output_still_valid_json(tmp_path):
    fetcher = FakeFetcher({f"{ROOT}/blog": "<html><body>No articles</body></html>"})
    dest = tmp_path / "empty.json"
    stats = run(SpiderRunner(spec(), fetcher=fetcher).run(dest, "json"))
    assert stats.extracted == 0
    assert json.loads(dest.read_text()) == []


def test_python_spider_can_override_custom_parser(tmp_path):
    class CustomSpider(SpiderRunner):
        def parse_item(self, node):
            data = super().parse_item(node)
            if data["title"]:
                data["title"] = data["title"].upper()
            return data

    dest = tmp_path / "custom.jsonl"
    run(CustomSpider(spec(max_depth=0), fetcher=FakeFetcher({f"{ROOT}/blog": HTML1})).run(dest))
    assert json.loads(dest.read_text().splitlines()[0])["title"] == "FIRST STORY"


def test_thousand_pages_bounded_and_streamed(tmp_path):
    count = 1000
    pages = {f"{ROOT}/blog": "".join(f"<a href='/item/{i}'>Open {i}</a>" for i in range(count))}
    pages.update({f"{ROOT}/item/{i}": f"<article><h2>Story {i}</h2></article>" for i in range(count)})
    dest = tmp_path / "thousand.jsonl"
    stats = run(SpiderRunner(spec(max_pages=count + 1, max_depth=1, max_items=count),
                             fetcher=FakeFetcher(pages)).run(dest))
    assert stats.visited == count + 1
    assert stats.extracted == count
    assert len(dest.read_text().splitlines()) == count


def test_provenance_field_override_rejected():
    with pytest.raises(SpiderPolicyError, match="reserved"):
        spec(fields={"used_in_prediction": "h1"})


def test_network_error_retried(tmp_path):
    class FailOnce(FakeFetcher):
        async def fetch(self, url, max_bytes):
            if url.endswith("/blog") and self.calls.count(url) == 0:
                self.calls.append(url)
                raise OSError("temporary failure")
            return await super().fetch(url, max_bytes)

    fetcher = FailOnce({f"{ROOT}/blog": HTML2})
    stats = run(SpiderRunner(spec(), fetcher=fetcher, sleep=lambda _: asyncio.sleep(0)).run(tmp_path / "retry.jsonl"))
    assert stats.extracted == 1
    assert fetcher.calls.count(f"{ROOT}/blog") == 2
