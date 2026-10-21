from datetime import datetime,timezone
from data_quality import validate_event,validate_quote
from freshness import parse_timestamp
NOW=datetime(2026,10,20,20,0,tzinfo=timezone.utc)
def test_timezone_required():
    try: parse_timestamp("2026-10-20T20:00:00")
    except ValueError as exc: assert "timezone" in str(exc)
    else: raise AssertionError("naive timestamp should fail")
def test_stale_quote_fails_closed():
    q={"event_id":"g1","sport":"NBA","market":"moneyline","selection":"home","odds_american":-110,"book":"b","source":"p","observed_at":"2026-10-20T19:00:00Z"}
    assert "not_fresh:stale" in validate_quote(q,max_age_seconds=300,now=NOW)
def test_valid_quote_and_invalid_event():
    q={"event_id":"g1","sport":"NBA","market":"moneyline","selection":"home","odds_american":-110,"book":"b","source":"p","observed_at":"2026-10-20T19:59:00Z"}
    assert validate_quote(q,max_age_seconds=300,now=NOW)==[]
    e={"event_id":"g1","sport":"NBA","start_time":"2026-10-20T21:00:00Z","home_team":"A","away_team":"A","source":"p","observed_at":"2026-10-20T19:59:00Z"}
    assert "same_home_and_away_team" in validate_event(e)
