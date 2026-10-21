from datetime import datetime,timezone
from orchestrator import analyze_payload
NOW=datetime(2026,10,20,20,0,tzinfo=timezone.utc)
def test_empty_input_no_fake_picks():
    r=analyze_payload({"events":[],"quotes":[]},now=NOW)
    assert r["eligible_events"]==r["eligible_quotes"]==0
    assert r["mode"]=="evidence_validation_only"
    assert r["prediction_status"].startswith("not_generated")
def test_valid_event_and_quote():
    e={"event_id":"nba-1","sport":"NBA","start_time":"2026-10-20T21:00:00Z","home_team":"A","away_team":"B","source":"fixture","observed_at":"2026-10-20T19:59:00Z"}
    q={"event_id":"nba-1","sport":"NBA","market":"moneyline","selection":"A","odds_american":-110,"book":"b","source":"fixture","observed_at":"2026-10-20T19:59:00Z"}
    r=analyze_payload({"events":[e],"quotes":[q]},now=NOW)
    assert r["eligible_events"]==r["eligible_quotes"]==1
    assert r["quotes"][0]["normalized"]["raw_implied_probability"]>.5
