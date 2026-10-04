from pathlib import Path
import re
import shutil

root = Path(__file__).resolve().parents[1]
source = root / "mobile_dashboard" / "public" / "filthy-pickz-logo.jpg"
if not source.is_file():
    raise SystemExit("FILTHY PICKZ logo asset is missing")

res = root / "android" / "app" / "src" / "main" / "res"
drawable = res / "drawable"
drawable.mkdir(parents=True, exist_ok=True)
target = drawable / "filthy_pickz_logo.jpg"
shutil.copyfile(source, target)

manifest = root / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
text = manifest.read_text()
text = text.replace('android:icon="@mipmap/ic_launcher"', 'android:icon="@drawable/filthy_pickz_logo"')
if 'android:roundIcon=' in text:
    text = re.sub(r'android:roundIcon="[^"]+"', 'android:roundIcon="@drawable/filthy_pickz_logo"', text)
else:
    text = text.replace(
        'android:icon="@drawable/filthy_pickz_logo"',
        'android:icon="@drawable/filthy_pickz_logo"\n        android:roundIcon="@drawable/filthy_pickz_logo"',
        1,
    )
manifest.write_text(text)

(drawable / "launch_background.xml").write_text("""<?xml version="1.0" encoding="utf-8"?>
<layer-list xmlns:android="http://schemas.android.com/apk/res/android">
    <item android:drawable="#0C100F"/>
    <item>
        <bitmap
            android:gravity="center"
            android:src="@drawable/filthy_pickz_logo"/>
    </item>
</layer-list>
""")
