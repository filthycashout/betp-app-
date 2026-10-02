"""Small-batch schema/provenance check; never promotes a model."""
import argparse
import json
from pathlib import Path
import governed_train as base


def validate(sport,path,manifest,output):
    policy=json.loads((Path(__file__).parent/'policy.json').read_text())
    report={'sport':sport,'promotion_approved':False,'passed':False,'checks':{}}
    try:
        frame,features,meta=base.load_canonical(path,policy['runtime_schema']['features'])
        source=json.loads(manifest.read_text())
        checks={'nonempty':len(frame)>0,'sport_matches':set(frame['sport'])=={sport},
                'dataset_hash':source.get('canonical_sha256')==meta['dataset_sha256'],
                'manifest_rows':source.get('rows')==len(frame),'manifest_sport':source.get('sport')==sport,
                'pregame_provenance':bool(source.get('pregame_sources')),'settlement_provenance':bool(source.get('labels_sha256'))}
        report.update(rows=len(frame),checks=checks,passed=all(checks.values()),dataset_sha256=meta['dataset_sha256'],
                      feature_schema_sha256=meta['feature_schema_sha256'],minimums=policy['sample_policy'][sport])
    except Exception as exc:report.update(error_type=type(exc).__name__,reason=str(exc))
    report['status']='PASS_SCHEMA_ONLY' if report['passed'] else 'FAIL_DATA_VALIDATION'
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--sport',choices=['NFL','NBA','MLB','NHL'],required=True)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--source-manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=validate(a.sport,a.input,a.source_manifest,a.output);print(json.dumps(r,indent=2));raise SystemExit(0 if r['passed'] else 2)
