from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest
import requests

import app
from market_validation import parse_props
from training import evidence_pipeline as ep
from training import governed_train as train

NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)


def prop_response(books):
    return {'id':'event', 'commence_time': (NOW + timedelta(hours=2)).isoformat(), 'bookmakers': books}


def book(sides, updated=NOW, name='book_a'):
    return {'key': name, 'markets': [{'key':'batter_hits', 'last_update': updated.isoformat() if updated else None,
      'outcomes':[{'name':side,'description':'Test Player','point':1.5,'price':price} for side,price in sides]}]}


def test_props_require_same_book_pair():
    raw=prop_response([book([('Over',-120)]),book([('Under',100)],name='book_b')])
    result=parse_props(raw,'MLB',['batter_hits'],NOW)
    assert all(p['recommended_side'] is None for p in result['props'])
    paired=parse_props(prop_response([book([('Over',-120),('Under',100)])]),'MLB',['batter_hits'],NOW)['props'][0]
    assert paired['recommended_side']=='OVER'
    assert paired['market_probability']==pytest.approx((120/220)/((120/220)+.5))\n    assert paired['contributing_books']==['book_a']\n    assert paired['best_available_book']=='book_a'\n    assert paired['best_available_price']==-120\n    assert paired['best_price_last_update']==NOW.isoformat()


@pytest.mark.parametrize('updated', [None, NOW-timedelta(minutes=6), NOW+timedelta(minutes=1)])
def test_props_reject_stale_missing_future_quote_time(updated):
    r=parse_props(prop_response([book([('Over',-110),('Under',-110)],updated)]),'MLB',['batter_hits'],NOW)
    assert r['props']==[] and r['status']=='NO_FRESH_MARKETS'


@pytest.mark.parametrize('price',[0,99,float('nan'),float('inf'),'not-a-price'])
def test_props_reject_invalid_prices(price):
    r=parse_props(prop_response([book([('Over',price)])]),'MLB',['batter_hits'],NOW)
    assert r['props']==[]


def test_props_no_post_start_recommendations():
    raw=prop_response([book([('Over',-110),('Under',-110)])]);raw['commence_time']=NOW.isoformat()
    assert parse_props(raw,'MLB',['batter_hits'],NOW)['status']=='NO_VERIFIED_PREGAME_EVENT'


def test_yes_no_props_require_complementary_prices():
    b=book([('Yes',150),('No',-180)])
    for o in b['markets'][0]['outcomes']: o.pop('point')
    p=parse_props(prop_response([b]),'MLB',['batter_hits'],NOW)['props'][0]
    assert p['recommended_side']=='NO' and p['line'] is None


def test_wrong_provider_event_rejected(monkeypatch):
    monkeypatch.setattr(app,'_odds_key',lambda:'test-only-placeholder')
    monkeypatch.setattr(app,'_json',lambda *a,**k:{'id':'different'})
    with pytest.raises(app.ProviderError): app._prop_payload('MLB','expected')


def test_provider_errors_do_not_expose_urls_or_credentials(monkeypatch):
    secret='sentinel-test-credential'
    def fail(*args,**kwargs):
        raise requests.RequestException('https://provider.invalid?apiKey='+secret)
    monkeypatch.setattr(app.SESSION,'get',fail)
    with pytest.raises(app.ProviderError) as e:
        app._timed('test.provider',lambda:app._json('https://provider.invalid',params={'apiKey':secret}))
    assert secret not in str(e.value)+json.dumps(app._SOURCE)
    assert 'apiKey' not in str(e.value)+json.dumps(app._SOURCE)


def test_provider_retries_transient_errors_only(monkeypatch):
    responses=iter([503,502,200]);calls=[]
    def get(*a,**k):
        r=requests.Response();r.status_code=next(responses);r._content=b'{"ok":true}';calls.append(1);return r
    monkeypatch.setattr(app.SESSION,'get',get);monkeypatch.setattr(app.time,'sleep',lambda _:None)
    assert app._json('https://provider.invalid')['ok'] and len(calls)==3


def test_doubleheader_event_mapping_uses_time():
    game={'home':'Home','away':'Away','event_time':NOW.isoformat()}
    e={'home_team':'Home','away_team':'Away','commence_time':NOW.isoformat(),'id':'first'}
    late={**e,'commence_time':(NOW+timedelta(hours=4)).isoformat(),'id':'second'}
    assert app._match_odds(game,[late,e])['id']=='first'
    assert app._match_odds(game,[e,copy.deepcopy(e)]) is None


def frame(n=600):
    times=pd.date_range('2020-01-01',periods=n,freq='D',tz='UTC')
    return pd.DataFrame({'sport':['NFL']*n,'home_team':['Home']*n,'away_team':['Away']*n,'event_id':[str(i) for i in range(n)],
        'as_of':times,'event_time':times+pd.Timedelta(hours=2),
        'label_available_at':times+pd.Timedelta(hours=6),'target_home_win':np.arange(n)%2,
        'market_home_probability':np.full(n,.5), 'feature_input':np.arange(n)%7})


@pytest.mark.parametrize('column,value',[('target_home_win',.5),('event_id',None),('feature_input',float('inf')),('label_available_at','2019-01-01T00:00:00Z')])
def test_canonical_rejects_invalid_training_rows(tmp_path,column,value):
    df=frame();df[column]=df[column].astype(object);df.loc[0,column]=value
    p=tmp_path/'data.csv';df.to_csv(p,index=False)
    with pytest.raises(ValueError):train.load_canonical(p,['feature_input'])


def test_split_never_uses_unavailable_results_or_splits_simultaneous_predictions():
    df=frame();df['as_of']=df['as_of'].dt.floor('2D')
    df.loc[0,'label_available_at']=df.iloc[-1]['event_time']+pd.Timedelta(days=1)
    for tr,va in train.walk_forward_splits(df,5):
        assert 0 not in tr
        assert df.iloc[tr]['label_available_at'].max()<df.iloc[va]['as_of'].min()
        assert not set(df.iloc[tr]['as_of']) & set(df.iloc[va]['as_of'])
    dev,holdout=train.chronological_holdout(df,.2)
    assert dev['label_available_at'].max()<holdout['as_of'].min()
    assert not set(dev['as_of']) & set(holdout['as_of'])


def test_imputer_preserves_empty_runtime_feature():
    pipeline=train.make_pipeline();x=pd.DataFrame({'a':[0,1,2,3],'b':[np.nan]*4})
    pipeline.fit(x,[0,1,0,1])
    assert len(pipeline.named_steps['imputer'].statistics_)==2
    assert len(pipeline.named_steps['clf'].coef_[0])==2


def test_settlement_retains_old_labels_and_first_availability(tmp_path,monkeypatch):
    settled=tmp_path/'settled';settled.mkdir()
    old={'sport':'NFL','event_id':'old','event_date':'2020-01-01','target_home_win':1,'settled_at':'2020-01-02T00:00:00Z'}
    today=datetime.now(timezone.utc).date().isoformat()
    recent={**old,'event_id':'recent','event_date':today}
    path=settled/'labels.jsonl';path.write_text(json.dumps(old)+'\n'+json.dumps(recent)+'\n')
    monkeypatch.setattr(ep,'_all_pregame_rows',lambda _:[{'sport':'NFL','event_id':'recent','schedule_date':today}])
    monkeypatch.setattr(ep,'_espn_results',lambda *a:{'recent':1})
    ep.settle(tmp_path)
    result=[json.loads(x) for x in path.read_text().splitlines()]
    assert {x['event_id'] for x in result}=={'old','recent'}
    assert next(x for x in result if x['event_id']=='recent')['settled_at']==recent['settled_at']


def test_schedule_date_preserves_local_game_day():
    assert str(ep._schedule_date({'event_time':'2026-10-03T02:00:00Z'}))=='2026-10-02'


def test_capture_checksums_verified_before_build(tmp_path,monkeypatch):
    monkeypatch.setattr(ep,'_json',lambda _:{'games':[]})
    ep.capture('https://example.invalid',tmp_path/'pregame')
    assert ep._all_pregame_rows(tmp_path)==[]
    p=next((tmp_path/'pregame').glob('pregame_*.jsonl'));p.write_text('{"tampered":true}\n')
    with pytest.raises(ValueError,match='checksum'):ep._all_pregame_rows(tmp_path)


def test_malformed_promoted_artifact_falls_back(tmp_path,monkeypatch):
    import model_runtime
    (tmp_path/'nfl.json').write_text('{"promotion_evidence":{"sample_sufficiency":{"rows":"broken"}}}')
    monkeypatch.setattr(model_runtime,'PROMOTED_DIR',tmp_path)
    assert model_runtime.load_promoted('NFL') is None


def test_game_markets_keep_actual_line_and_same_book_pairs():
    from market_validation import parse_game_market
    def spread(line,price):
        return {'key':str(line),'last_update':NOW.isoformat(),'markets':[{'key':'spreads','outcomes':[
            {'name':'Home','point':line,'price':price},{'name':'Away','point':-line,'price':-110}]}]}
    raw={**prop_response([spread(-3.5,-120),spread(-4.5,-110)]),'home_team':'Home','away_team':'Away'}
    market=parse_game_market(raw,NOW)
    assert market['home_spread'] in {-3.5,-4.5}  # -4.0 was never offered.
    assert market['spread_pick_probability'] is not None
    raw['bookmakers'][0]['last_update']=None;raw['bookmakers'][1]['last_update']=None
    market=parse_game_market(raw,NOW)
    assert market['spread_pick_probability'] is None and not market['freshness_verified']


def test_training_export_retains_oof_and_rejects_insufficient_samples(tmp_path):
    import argparse
    import hashlib
    sys.path.insert(0,str(Path(train.__file__).parent))
    import strict_promote
    df=frame();df['consensus_de_vig_home_probability']=.5
    df['home_spread']=(np.arange(len(df))%7)-3.;df['consensus_total']=45.
    dataset=tmp_path/'nfl.csv';df.to_csv(dataset,index=False)
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'sport':'NFL','rows':len(df),
        'canonical_sha256':hashlib.sha256(dataset.read_bytes()).hexdigest(),
        'labels_sha256':'0'*64,'pregame_sources':[{'test_fixture_only':True}]}))
    args=argparse.Namespace(sport='NFL',input=str(dataset),source_manifest=str(manifest),output_dir=str(tmp_path/'out'),
        features='consensus_de_vig_home_probability,home_spread,consensus_total',splits=5,holdout_fraction=.2,min_rows=None,logloss_margin=0.)
    report=strict_promote.enforce(args)
    assert not report['strict_policy_pass'] and report['status']=='CANDIDATE_REJECTED'
    assert not report['strict_checks']['minimum_total_rows']
    assert Path(report['oof_file']).exists() and report['oof_rows']>=100
    assert report['mobile_parity_max_abs_error']<=1e-10
