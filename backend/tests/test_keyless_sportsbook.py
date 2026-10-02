import keyless_sportsbook as ks


def test_draftkings_game_markets_are_normalized(monkeypatch):
    ks._CACHE.clear()
    sample = {
        'events': [{
            'id': 'dk-1',
            'name': 'Rangers @ Red Wings',
            'startEventDate': '2026-10-03T00:30:00Z',
        }],
        'markets': [
            {'id': 'm1', 'eventId': 'dk-1', 'name': 'Moneyline'},
            {'id': 'm2', 'eventId': 'dk-1', 'name': 'Spread'},
            {'id': 'm3', 'eventId': 'dk-1', 'name': 'Total'},
        ],
        'selections': [
            {'marketId': 'm1', 'label': 'Rangers', 'displayOdds': {'american': '+105'}},
            {'marketId': 'm1', 'label': 'Red Wings', 'displayOdds': {'american': '-125'}},
            {'marketId': 'm2', 'label': 'Rangers +1.5', 'points': 1.5, 'displayOdds': {'american': '-170'}},
            {'marketId': 'm2', 'label': 'Red Wings -1.5', 'points': -1.5, 'displayOdds': {'american': '+145'}},
            {'marketId': 'm3', 'label': 'Over 6.5', 'points': 6.5, 'displayOdds': {'american': '-110'}},
            {'marketId': 'm3', 'label': 'Under 6.5', 'points': 6.5, 'displayOdds': {'american': '-110'}},
        ],
    }
    monkeypatch.setattr(ks, '_game_payload', lambda sport: sample)
    events = ks.draftkings_game_events('NHL')
    assert len(events) == 1
    event = events[0]
    assert event['market_source'] == 'DRAFTKINGS_KEYLESS_DIRECT'
    assert event['home_team'] == 'Red Wings'
    assert event['away_team'] == 'Rangers'
    markets = {row['key']: row for row in event['bookmakers'][0]['markets']}
    assert set(markets) == {'h2h', 'spreads', 'totals'}
    assert markets['h2h']['outcomes'][0]['price'] == 105
    assert event['bookmakers'][0]['observed_at']


def test_prop_name_mapping_covers_all_four_sports():
    assert ks._prop_key('NFL', 'Passing Props', 'Passing Yards O/U') == 'player_pass_yds'
    assert ks._prop_key('NBA', 'Player Props', 'Points + Rebounds + Assists') == 'player_points_rebounds_assists'
    assert ks._prop_key('MLB', 'Pitcher Props', 'Strikeouts O/U') == 'pitcher_strikeouts'
    assert ks._prop_key('NHL', 'Player Props', 'Shots on Goal O/U') == 'player_shots_on_goal'


def test_keyless_prop_events_group_by_event(monkeypatch):
    ks._CACHE.clear()
    monkeypatch.setattr(
        ks,
        '_prop_catalog',
        lambda sport: [{
            'category_id': '1',
            'subcategory_id': '2',
            'category_name': 'Player Props',
            'subcategory_name': 'Shots on Goal O/U',
            'market_key': 'player_shots_on_goal',
        }],
    )
    monkeypatch.setattr(
        ks,
        '_fetch_prop_subcategory',
        lambda sport, row: [{
            'event_id': 'dk-1',
            'home_team': 'Red Wings',
            'away_team': 'Rangers',
            'commence_time': '2026-10-03T00:30:00Z',
            'market_key': 'player_shots_on_goal',
            'observed_at': '2026-10-02T23:00:00+00:00',
            'outcomes': [
                {
                    'name': 'Over',
                    'description': 'Artemi Panarin',
                    'point': 2.5,
                    'price': -115,
                },
                {
                    'name': 'Under',
                    'description': 'Artemi Panarin',
                    'point': 2.5,
                    'price': -105,
                },
            ],
        }],
    )
    events = ks.draftkings_prop_events('NHL', ['player_shots_on_goal'])
    assert len(events) == 1
    market = events[0]['bookmakers'][0]['markets'][0]
    assert market['key'] == 'player_shots_on_goal'
    assert market['outcomes'][0]['description'] == 'Artemi Panarin'
