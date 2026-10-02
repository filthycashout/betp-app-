from fastapi.testclient import TestClient
import app as runtime

client = TestClient(runtime.app)

def test_health_and_compatibility_aliases():
    for path in ['/', '/health', '/v1/health', '/api/health']:
        assert client.get(path).status_code == 200
    assert client.get('/health').json()['version'] == '1.4.3'

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
    data = client.get('/v1/system/props').json()['sports']
    assert set(data) == {'NFL', 'NBA', 'MLB', 'NHL'}
    assert 'player_shots_on_goal' in data['NHL']['markets']
    assert 'pitcher_strikeouts' in data['MLB']['markets']
