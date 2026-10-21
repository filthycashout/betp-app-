# Configurable Web Spiders — Sports Omni research ingestion

## Purpose

Sports Omni is a **machine-versus-market sports ML tracking project**. This Python crawler lets you define one spider per approved website, starting from its URL, following matching internal links and extracting HTML fields with CSS selectors. It streams structured JSONL, JSON arrays, or CSV without accumulating every item in memory.

This capability also works on authorized blogs and online catalogs. It is **separate from** the prediction/training system. A crawl is raw evidence, not a verified sports feature, and odds scraped from any site must remain outside the independent ML model inputs.

## Install and run

From the repository root:

~~~bash
python -m pip install -r backend/requirements-crawling.txt
PYTHONPATH=backend python -m sports_ai.crawling.cli \
  --config examples/blog_spider.json \
  --output output/blog.jsonl --format jsonl
PYTHONPATH=backend python -m sports_ai.crawling.cli \
  --config examples/products_spider.json \
  --output output/products.csv --format csv
PYTHONPATH=backend python -m sports_ai.crawling.cli \
  --config examples/sports_context_spider.json \
  --output output/sports.json --format json
~~~

**The example.org URLs and selectors are placeholders**, not validated websites or evidence of live scraping. Replace each site's start URLs, allowed hosts, and field CSS selectors before use, and check the site's rules and your data access rights. Add an appropriate identifying --user-agent if desired.

## Spider configuration

~~~json
{
  "name": "site_articles",
  "start_urls": ["https://example.org/blog/"],
  "allowed_hosts": ["example.org"],
  "item_selector": "article",
  "follow_selector": "a[href]",
  "fields": {
    "title": "h2",
    "author": ".byline",
    "published_at": {"selector": "time[datetime]", "attribute": "datetime"},
    "tags": {"selector": ".tag", "multiple": true}
  },
  "required_fields": ["title"],
  "max_pages": 5000,
  "max_depth": 8,
  "max_items": 50000,
  "concurrency": 6,
  "request_delay_seconds": 0.5,
  "retries": 2,
  "timeout_seconds": 15,
  "max_response_bytes": 1048576,
  "source_kind": "sports_context"
}
~~~

Each CSS item selector identifies one article/product per page. Field selectors apply within each selected item. The follow selector controls which links are traversed. For simple pages containing one object, use an item selector of body. Multi-valued fields become arrays in JSON and JSON-encoded cells in CSV.

For special extraction rules, **subclass SpiderRunner** in Python and override parse_item(node) or discover_links(soup, url). All discovered URLs are still checked against the domain policy.

## Safety and efficiency

- Asynchronous requests (aiohttp), bounded concurrency (up to 32 workers), deduplication, maximum depth/page/item counts and bounded HTML response size. JSON/CSV records are streamed directly to disk.
- Honors site robots.txt disallow rules and supported crawl delay; non-404 robots errors fail closed. Per-host request spacing avoids uncontrolled request bursts. HTTP 429 and transient 5xx responses receive capped retries/backoff.
- Only HTTPS and exact explicitly allowed public DNS hostnames. Local/private addresses and DNS responses, credentials in URLs, redirects, nonstandard ports, and off-host links are blocked. No login, paywall, anti-bot, or CAPTCHA evasion.
- Permission to crawl must come from the site and applicable legal/contractual terms; robots.txt alone is not authorization.
- HTML only, with no JavaScript browser execution. For dynamically rendered or API-driven websites, use a separately reviewed API adapter. No checkpoint/resume or distributed queues are implemented yet.
- The output contains source_url, fetched_at, content_sha256, and source_kind. trusted_for_instructions, used_in_prediction, and historical_training_eligible are **false**. canonical_admission_required is **true**.

## Sports Machine data flow

~~~text
Per-site spider -> timestamped evidence sidecar -> sport/event/entity normalization
                                                   -> validate source and pregame observation
                                                   -> exclude market-derived inputs
                                                   -> sport-only ML feature admission (separate future stage)
                                                   -> freeze independent prediction
                                                   -> compare actual result with machine and market
~~~

The spider has **not** implemented the required sports-specific normalization, training admission, sports model, scheduler or durable prediction ledger. Keep market benchmark data in a separate evaluation track.

## Test

~~~bash
python -m pip install -r backend/requirements-validation.txt
PYTHONPATH=backend pytest -q backend/tests/test_configurable_spiders.py
~~~

Tests use local synthetic HTML and mocked HTTP, including a 1,000-page crawl. They do not establish permission or compatibility with any real website.
