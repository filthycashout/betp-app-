"""Record one fresh live prop canary per sport through the deployed server.
Credentials are configured only on the server; this command never accepts keys.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import requests

MARKETS={'NFL':'player_pass_yds','NBA':'player_points','MLB':'pitcher_strikeouts','NHL':'player_shots_on_goal'}


def run(base,output):
    output.mkdir(parents=True,exist_ok=True)
    def get(path,params=None):
        response=requests.get(base.rstrip('/')+path,params=params,timeout=45)
        if response.status_code!=200:raise RuntimeError('Backend HTTP '+str(response.status_code))
        return response.json()
    try:capabilities=get('/v1/system/props')
    except Exception:capabilities={}
    reports=[]
    for sport,market in MARKETS.items():
        report={'sport':sport,'checked_at':datetime.now(timezone.utc).isoformat(),'requested_market':market,
                'status':'BLOCKED_FRESH_ROTATED_KEY_REQUIRED','passed':False,'provider_revocation_proven':False}
        if capabilities.get('credential_configured') and capabilities.get('credential_rotation_confirmed'):
            try:
                games=get('/v1/search',{'sport':sport,'include_props':'false'}).get('games',[])
                games=[g for g in games if g.get('odds_event_id')]
                if not games:report['status']='NOT_EVALUATED_NO_MAPPED_EVENT'
                else:
                    game=games[0]
                    payload=get(f"/v1/games/{sport}/{game['event_id']}/props",{'odds_event_id':game['odds_event_id'],'markets':market})
                    props=payload.get('props') or []
                    checks={'provider_status_ok':payload.get('status')=='OK',
                            'nonempty':bool(props),'expected_market':bool(props) and all(p.get('market')==market for p in props),
                            'complementary_price':any(p.get('probability_method')=='same_book_two_sided_devig' for p in props),
                            'timestamps_present':bool(props) and all(p.get('last_update') for p in props)}
                    report.update(event_id=game['event_id'],checks=checks,accepted_quotes=len(props),passed=all(checks.values()))
                    report['status']='PASS_LIVE_MARKET_CANARY' if report['passed'] else 'FAIL_OR_NO_FRESH_MARKETS'
            except Exception as exc:
                report.update(status='FAIL_CONNECTOR',error_type=type(exc).__name__)
        (output/f'{sport.lower()}_live_connector.json').write_text(json.dumps(report,indent=2)+'\n')
        reports.append(report)
    return reports

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-url',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=run(a.base_url,a.output);print(json.dumps(r,indent=2));raise SystemExit(0 if all(x['passed'] for x in r) else 2)
