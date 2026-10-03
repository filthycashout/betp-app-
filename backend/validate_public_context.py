"""Read-only, real-provider canaries for the public context routes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
from fastapi.testclient import TestClient
import app as runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--check-noncommercial-open-meteo', action='store_true')
    args = parser.parse_args()
    if args.check_noncommercial_open_meteo:
        os.environ['OPEN_METEO_ACCESS'] = 'noncommercial'
    client = TestClient(runtime.app)
    paths = ['/v1/context/weather?lat=32.7073&lon=-117.1566']
    paths += [f'/v1/context/news/{sport}?limit=3' for sport in runtime.SPORTS]
    if args.check_noncommercial_open_meteo:
        paths += ['/v1/context/weather?lat=51.5&lon=-0.1&provider=open_meteo']
    def check(path):
        response = client.get(path)
        payload = response.json()
        row = {'path': path, 'http_status': response.status_code,
               'available': payload.get('available'), 'provider': payload.get('provider'),
               'retrieved_at': payload.get('retrieved_at'), 'reason': payload.get('reason'),
               'context_used_in_prediction': payload.get('used_in_prediction')}
        if 'articles' in payload:
            row['article_count'] = len(payload['articles'])
            row['publication_times'] = [x['published_at'] for x in payload['articles']]
        else:
            row.update({k:payload.get(k) for k in ['provider_issued_at','valid_from','valid_until','temperature_c','wind_kmh_max','precipitation_probability_pct']})
        row['passed'] = response.status_code == 200 and payload.get('available') is True and payload.get('used_in_prediction') is False
        return row
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(check, paths))
    result = {'checked_at':datetime.now(timezone.utc).isoformat(), 'backend_version':runtime.APP_VERSION,
              'scope':'Local backend routes making real public-provider requests; not deployed-backend verification.',
              'passed':all(r['passed'] for r in rows), 'checks':rows}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['passed'] else 1)

if __name__ == '__main__':
    main()
