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
import re
import xml.etree.ElementTree as ET


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
            'scope':'exact_release_install_launch_live_score_feeds_and_navigation','passed':False,'physical_test':False}
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
        time.sleep(5)
        pid=call('shell','pidof',package,check=False)
        if not pid:raise RuntimeError('App process exited after launch')
        logs=call('logcat','-d','--pid='+pid.split()[0])
        (args.output/'app-logcat.txt').write_text(logs)
        if 'FATAL EXCEPTION' in logs:raise RuntimeError('Fatal Android exception after launch')
        (args.output/'launch.png').write_bytes(call('exec-out','screencap','-p',binary=True))
        call('shell','uiautomator','dump','/sdcard/window.xml',check=False)
        xml=call('shell','cat','/sdcard/window.xml',check=False)
        (args.output/'window.xml').write_text(xml)
        def dump():
            call('shell','uiautomator','dump','/sdcard/window.xml',check=False)
            return call('shell','cat','/sdcard/window.xml',check=False)
        def exposed(value, text):
            return text.casefold() in value.casefold()
        def wait_for(text, seconds=50):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                value=dump()
                if exposed(value,text):return value
                time.sleep(2)
            raise RuntimeError('Dashboard did not expose: '+text)
        def tap_label(label):
            root=ET.fromstring(dump())
            for node in root.iter('node'):
                text=(node.attrib.get('text','') or node.attrib.get('content-desc','')).strip()
                if text.casefold()==label.casefold() or text.casefold().endswith(' '+label.casefold()):
                    b=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.attrib.get('bounds',''))
                    if b:
                        x1,y1,x2,y2=map(int,b.groups())
                        if x2>x1 and y2>y1:
                            call('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2));return
            raise RuntimeError('Dashboard control missing: '+label)
        def open_view(label, expected, evidence_name):
            # WebView accessibility can retain only the visible viewport. Retry the
            # semantic tap and reset the document scroll before asserting page text.
            last=''
            for _ in range(3):
                tap_label(label)
                time.sleep(1)
                call('shell','input','swipe','160','220','160','500','300',check=False)
                time.sleep(1)
                last=dump()
                if exposed(last,expected):
                    (args.output/(evidence_name+'.xml')).write_text(last)
                    return last
            (args.output/(evidence_name+'-failure.xml')).write_text(last)
            raise RuntimeError('Dashboard did not expose after navigation: '+expected)
        wait_for('Live')
        logs=call('logcat','-d','--pid='+pid.split()[0])
        if 'PHILTHY_DASHBOARD_READY' not in logs:raise RuntimeError('Bundled React dashboard did not signal readiness')
        report['bundled_dashboard']='PASS'
        report['sport_tabs']={}
        for sport in ['NFL','NBA','NHL','MLB']:
            call('logcat','-c')
            tap_label(sport)
            wait_for(sport+' games')
            deadline=time.monotonic()+50
            while time.monotonic()<deadline:
                logs=call('logcat','-d','--pid='+pid.split()[0])
                if 'PHILTHY_SCORES:'+sport+':' in logs:break
                time.sleep(2)
            else:raise RuntimeError('No fresh live feed received for '+sport)
            value=dump()
            (args.output/(sport.lower()+'-scoreboard.xml')).write_text(value)
            (args.output/(sport.lower()+'-scoreboard.png')).write_bytes(call('exec-out','screencap','-p',binary=True))
            report['sport_tabs'][sport]='PASS_FRESH_FEED_RECEIVED'
        open_view('Picks','Best 12 picks','picks')
        (args.output/'picks.png').write_bytes(call('exec-out','screencap','-p',binary=True))
        report['best12_navigation']='PASS'

        # Assert a stable semantic fragment; WebView accessibility may normalize
        # punctuation/casing in the full heading even when the correct view is open.
        open_view('Parlay','3 leg parlays','parlays')
        (args.output/'parlays.png').write_bytes(call('exec-out','screencap','-p',binary=True))
        report['best3_navigation']='PASS'

        open_view('Settings','Settings','settings')
        (args.output/'settings.png').write_bytes(call('exec-out','screencap','-p',binary=True))

        open_view('Live','Live','live-return')
        (args.output/'app-logcat.txt').write_text(call('logcat','-d','--pid='+pid.split()[0]))
        report.update(launch='PASS',process_alive=True,passed=True,physical_test=args.require_physical and not virtual,
                      interactive_end_to_end_verified=False,scoreboard_navigation_verified=True,live_props_verified=False)
    except Exception as exc:
        report['failure']=type(exc).__name__+': '+str(exc)
    finally:
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        (args.output/'device-smoke.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['passed'] else 1)

if __name__=='__main__':main()
