"""Install/launch the exact release APK; preserve app data and record evidence.
A physical run must explicitly pass --require-physical. This is launch smoke,
not proof of live props, model accuracy, or complete interactive device testing.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--apk',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--serial')
    p.add_argument('--require-physical',action='store_true')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    adb=['adb']+(['-s',args.serial] if args.serial else [])
    def call(*cmd,binary=False,check=True):
        r=subprocess.run(adb+list(cmd),capture_output=True,timeout=90,check=check)
        return r.stdout if binary else r.stdout.decode(errors='replace').strip()
    report={'started_at':datetime.now(timezone.utc).isoformat(),'apk_sha256':hashlib.sha256(args.apk.read_bytes()).hexdigest(),
            'scope':'exact_release_install_and_launch_only','passed':False,'physical_test':False}
    try:
        call('wait-for-device')
        virtual=call('shell','getprop','ro.kernel.qemu')=='1' or call('shell','getprop','ro.boot.qemu')=='1'
        report.update(device_type='emulator' if virtual else 'physical_candidate',
                      model=call('shell','getprop','ro.product.model'),api_level=call('shell','getprop','ro.build.version.sdk'))
        if args.require_physical and virtual:raise RuntimeError('A physical device is required; this target is an emulator')
        install=call('install','-r',str(args.apk))
        if 'Success' not in install:raise RuntimeError('APK installation did not report success')
        report['install']='PASS'
        package='com.philthysports.philthysports'
        call('logcat','-c')
        launch=call('shell','am','start','-W','-n',package+'/.MainActivity')
        if 'Error' in launch:raise RuntimeError('Activity launch failed')
        time.sleep(15)
        pid=call('shell','pidof',package,check=False)
        if not pid:raise RuntimeError('App process exited after launch')
        logs=call('logcat','-d','--pid='+pid.split()[0])
        (args.output/'app-logcat.txt').write_text(logs)
        if 'FATAL EXCEPTION' in logs:raise RuntimeError('Fatal Android exception after launch')
        (args.output/'launch.png').write_bytes(call('exec-out','screencap','-p',binary=True))
        call('shell','uiautomator','dump','/sdcard/window.xml',check=False)
        xml=call('shell','cat','/sdcard/window.xml',check=False)
        (args.output/'window.xml').write_text(xml)
        report.update(launch='PASS',process_alive=True,passed=True,physical_test=args.require_physical and not virtual,
                      interactive_end_to_end_verified=False,live_props_verified=False)
    except Exception as exc:
        report['failure']=type(exc).__name__+': '+str(exc)
    finally:
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        (args.output/'device-smoke.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['passed'] else 1)

if __name__=='__main__':main()
