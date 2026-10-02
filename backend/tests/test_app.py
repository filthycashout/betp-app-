from fastapi.testclient import TestClient
import app as runtime

client = TestClient(runtime.app)

def test_health_and_compatibility_aliases():
    for path in ['/', '/health', '/v1/health', '/api/health']:
        assert client.get(path).status_code == 200
    assert client.get('/health').json()['version'] == '1.4.5'

def test_four_sport_model_baseline():
    data = client.get('/v1/models/status').json()
    assert set(data) == {'NFL', 'NBA', 'MLB', 'NHL'}
    assert all(len(v['sha256']) == 64 for v in data.values())
    assert all(v['promotion_gate']['passed'] is False for v in data.values())

def test_drive_reconstruction_manifest():
    data = client.get('/v1/training/reconstruction').json()
    assert data['sports']['MLB']['status'] == 'PARTIALLY_RECONSTRUCTABLE_NOT_PROMOTION_READY'
    assert data['sports']['NFL']['status'] == 'ARTIFACT_AND_SCHEMA_RECONSTRUCTABLE_TRAINING_ROWS_MISSING'
    assert data['sports']['MLB']['settled_evaluation']['resolved_games'] == 7

def test_api_prefix_compatibility():
    assert client.get('/api/v1/system/status').status_code == 200
    assert client.get('/api/v1/models/status').status_code == 200
    props = client.get('/api/v1/system/props')
    assert props.status_code == 200
    assert set(props.json()['sports']) == {'NFL', 'NBA', 'MLB', 'NHL'}

    paths = {route.path for route in runtime.app.routes}
    for path in {
        '/api/v1/games/{sport}',
        '/api/v1/predictions/{sport}',
        '/api/v1/odds/{sport}',
        '/api/v1/games/{sport}/{event_id}',
        '/api/v1/games/{sport}/{event_id}/props',
        '/api/v1/games/{sport}/{event_id}/parlays',
        '/api/v1/parlays/multisport',
    }:
        assert path in paths

    latest = client.get('/v1/predictions/latest')
    assert latest.status_code == 200
    assert latest.json()['verified_live_run'] is False

def test_all_four_sports_have_prop_contracts():
    payload = client.get('/v1/system/props').json()
    data = payload['sports']
    assert payload['status'] == 'CONTRACT_READY_LIVE_KEY_REQUIRED'
    assert set(data) == {'NFL', 'NBA', 'MLB', 'NHL'}

    assert 'player_pass_rush_reception_yds' in data['NFL']['markets']
    assert 'player_first_basket' in data['NBA']['markets']
    assert 'batter_first_home_run' in data['MLB']['markets']
    assert 'batter_singles' in data['MLB']['markets']
    assert 'batter_doubles' in data['MLB']['markets']
    assert 'batter_triples' in data['MLB']['markets']
    assert 'pitcher_record_a_win' in data['MLB']['markets']
    assert 'player_goal_scorer_first' in data['NHL']['markets']
    assert 'player_goal_scorer_last' in data['NHL']['markets']
    assert 'player_pass_yds_alternate' in data['NFL']['alternate_markets']
    assert 'player_points_alternate' in data['NBA']['alternate_markets']
    assert 'pitcher_outs_alternate' in data['MLB']['alternate_markets']
    assert 'player_shots_on_goal_alternate' in data['NHL']['alternate_markets']

    assert 'pitcher_strikeouts' in data['MLB']['default_live_markets']
    assert 'player_shots_on_goal' in data['NHL']['default_live_markets']


def test_unrotated_key_never_falls_through_to_live_props(monkeypatch):
    monkeypatch.setenv('ODDS_API_KEY', 'test-only-placeholder')
    monkeypatch.delenv('CREDENTIAL_ROTATION_CONFIRMED', raising=False)
    response = client.get('/v1/games/MLB/test-event/props?odds_event_id=test-odds-event')
    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'CONTRACT_READY_LIVE_KEY_REQUIRED'
    assert payload['props'] == []
