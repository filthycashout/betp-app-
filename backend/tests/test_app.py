from fastapi.testclient import TestClient
import app as runtime

client = TestClient(runtime.app)

def test_health():
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['version'] == '1.3.1'

def test_four_sport_model_baseline():
    data = client.get('/v1/models/status').json()
    assert set(data) == {'NFL', 'NBA', 'MLB', 'NHL'}
    assert all(v['status'] == 'PRODUCTION_BASELINE' and v['trained_weights'] is False for v in data.values())
    assert all(len(v['sha256']) == 64 and v['artifact_path'].endswith('production.json') for v in data.values())

def test_all_four_sports_have_prop_contracts():
    data = client.get('/v1/system/props').json()['sports']
    assert set(data) == {'NFL', 'NBA', 'MLB', 'NHL'}
    assert all(data[s]['supported'] and data[s]['markets'] for s in data)
    assert 'player_shots_on_goal' in data['NHL']['markets']
    assert 'pitcher_strikeouts' in data['MLB']['markets']

def test_props_contract_is_visible_without_server_credential(monkeypatch):
    monkeypatch.delenv('ODDS_API_KEY', raising=False)
    r = client.get('/v1/games/NHL/123/props')
    assert r.status_code == 200
    data = r.json()
    assert data['status'] == 'CONTRACT_READY_LIVE_KEY_REQUIRED'
    assert 'player_shots_on_goal' in data['configured_markets']
    assert data['props'] == []
