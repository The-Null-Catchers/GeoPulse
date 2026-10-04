from pathlib import Path

root = Path(__file__).resolve().parent.parent / "apps/mobile"
manifest = root / "android/app/src/main/AndroidManifest.xml"
if manifest.exists():
    text = manifest.read_text()
    additions = "".join(
        f'    <uses-permission android:name="android.permission.{p}"/>\n'
        for p in ["INTERNET", "ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION"]
        if f"android.permission.{p}" not in text
    )
    text = text.replace("    <application", additions + "    <application", 1)
    manifest.write_text(text)
plist = root / "ios/Runner/Info.plist"
if plist.exists():
    text = plist.read_text()
    if "NSLocationWhenInUseUsageDescription" not in text:
        text = text.replace(
            "</dict>",
            "<key>NSLocationWhenInUseUsageDescription</key><string>GeoPulse shares your location only when you explicitly start tracking.</string></dict>",
            1,
        )
        plist.write_text(text)
