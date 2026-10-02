from fastapi.testclient import TestClient
import app as runtime

client = TestClient(runtime.app)

def test_health_and_compatibility_aliases():
    for path in ['/', '/health', '/v1/health', '/api/health']:
        assert client.get(path).status_code == 200
    assert client.get('/health').json()['version'] == runtime.APP_VERSION

def test_four_sport_model_runtime_contract():
    data = client.get('/v1/models/status').json()
    assert set(data) == {'NFL', 'NBA', 'MLB', 'NHL'}
    assert all(len(v['sha256']) == 64 for v in data.values())
    for sport, row in data.items():
        passed = row['promotion_gate']['passed'] is True
        if passed:
            assert row['promoted_artifact_loaded'] is True
            assert row['runtime_mode'] == 'PROMOTED_TRAINED_MODEL'
        else:
            assert row['runtime_mode'] == 'EVIDENCE_GATED_HYBRID_MARKET_FORM_FALLBACK'

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


def test_generated_prediction_bundle_without_moneyline():
    game = {'home': 'Test Home', 'away': 'Test Away'}
    market = {
        'home_probability': None,
        'away_probability': None,
        'home_spread': -2.5,
        'away_spread': 2.5,
        'spread_pick': None,
        'spread_pick_probability': None,
        'total': 44.5,
        'total_pick': None,
        'total_pick_probability': None,
    }
    score = {'home': 24.0, 'away': 20.0, 'method': 'recent_completed_games_scoring_blend'}
    form = {
        'source': 'keyless_recent_form_heuristic',
        'calibrated': False,
        'home_win_probability': 0.62,
        'projected_score': score,
    }
    generated = runtime._prediction_bundle(
        game,
        market,
        score,
        0.62,
        'keyless_recent_form_heuristic',
        'chronological recent-form fallback',
        form,
    )
    assert generated['generated'] is True
    assert generated['moneyline']['pick'] == 'Test Home'
    assert generated['spread']['pick'] == 'Test Home'
    assert generated['total']['pick'] == 'UNDER'


def test_keyless_four_sport_live_gateway_contracts():
    response = client.get('/v1/live/sources')
    assert response.status_code == 200
    payload = response.json()
    assert payload['credential_required'] is False
    assert set(payload['sports']) == {'NFL', 'NBA', 'MLB', 'NHL'}
    assert all(
        sport_payload['credential_required'] is False
        for sport_payload in payload['sports'].values()
    )

    paths = {route.path for route in runtime.app.routes}
    assert '/v1/live/{sport}/scoreboard' in paths
    assert '/v1/live/{sport}/game/{event_id}' in paths
    assert '/api/v1/live/{sport}/scoreboard' in paths
    assert '/api/v1/live/{sport}/game/{event_id}' in paths


def test_governed_model_registry_exposes_candidates_without_fake_promotion():
    response = client.get('/v1/models/registry')
    assert response.status_code == 200
    payload = response.json()
    assert set(payload['sports']) == {'NFL', 'NBA', 'MLB', 'NHL'}
    for sport, row in payload['sports'].items():
        if row['promotion_gate_passed']:
            assert row['runtime_mode'] == 'PROMOTED_TRAINED_MODEL'
        else:
            assert row['runtime_mode'] == 'EVIDENCE_GATED_HYBRID_MARKET_FORM_FALLBACK'
    assert payload['sports']['NFL']['candidate_roles']
    assert payload['sports']['MLB']['candidate_roles']


def test_game_detail_without_date_resolves_nearby_schedule(monkeypatch):
    today = runtime._pacific_today()
    target_date = (today + runtime.timedelta(days=2)).isoformat()
    calls = []

    def fake_search(q='', sport=None, date=None, include_props=False, props_limit=3):
        calls.append(date)
        if date != target_date:
            return {'games': []}
        return {
            'games': [{
                'event_id': 'target-event',
                'sport': 'NFL',
                'home': 'Home',
                'away': 'Away',
                'date': target_date,
                'market': {
                    'home_probability': None,
                    'away_probability': None,
                    'home_spread': None,
                    'away_spread': None,
                    'spread_pick': None,
                    'spread_pick_probability': None,
                    'total': None,
                    'total_pick': None,
                    'total_pick_probability': None,
                },
                'projected_score': {'home': 24.0, 'away': 20.0, 'method': 'test'},
                'predictions': {
                    'generated': True,
                    'moneyline': {
                        'pick': 'Home',
                        'home_win_probability': 0.6,
                        'source': 'keyless_recent_form_heuristic',
                    },
                    'spread': {},
                    'total': {'projected_total': 44.0},
                    'fallback': {
                        'note': 'completed games before matchup only',
                    },
                },
                'pick': 'Home',
                'home_win_probability': 0.6,
                'probability_source': 'keyless_recent_form_heuristic',
                'prediction_reasoning': 'test fallback',
            }]
        }

    monkeypatch.setattr(runtime, '_search', fake_search)
    game = runtime.game_detail('NFL', 'target-event')
    assert game['event_id'] == 'target-event'
    assert game['prediction_status'] == 'GENERATED'
    assert target_date in calls


def test_search_query_matches_team_matchup_sport_and_date():
    d = runtime.date_cls(2026, 10, 4)
    game = {
        'home': 'Las Vegas Raiders',
        'away': 'Kansas City Chiefs',
        'matchup': 'Kansas City Chiefs @ Las Vegas Raiders',
    }
    assert runtime._matches_search_query('chiefs', game, 'NFL', d)
    assert runtime._matches_search_query('chiefs raiders', game, 'NFL', d)
    assert runtime._matches_search_query('NFL', game, 'NFL', d)
    assert runtime._matches_search_query('2026-10-04', game, 'NFL', d)
    assert runtime._matches_search_query('10/04/2026', game, 'NFL', d)
    assert not runtime._matches_search_query('Dodgers', game, 'NFL', d)
