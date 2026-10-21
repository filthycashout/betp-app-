from __future__ import annotations

from sports_data_sources import (
    CONTEXT_ONLY,
    MARKET,
    WEB_RESEARCH,
    source_inventory,
    sources_for,
)


def test_all_sources_are_untrusted_for_instructions_and_no_default_model_influence():
    inventory = source_inventory()
    assert set(inventory["sports"]) == {"NFL", "NBA", "MLB", "NHL"}
    assert inventory["sources"]
    for source in inventory["sources"]:
        assert source["trusted_for_instructions"] is False
        assert source["model_influence_default"] is False


def test_scrapegraph_is_context_only_and_not_training_authority():
    sources = [source for source in source_inventory()["sources"] if source["source_id"] == "scrapegraphai"]
    assert len(sources) == 1
    source = sources[0]
    assert WEB_RESEARCH in source["roles"]
    assert source["training_admission"] == CONTEXT_ONLY
    assert source["runtime_env"] == "SGAI_API_KEY"


def test_every_sport_has_market_source():
    for sport in ("NFL", "NBA", "MLB", "NHL"):
        assert sources_for(sport, MARKET)
