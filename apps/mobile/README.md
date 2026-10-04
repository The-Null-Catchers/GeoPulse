# GeoPulse mobile foundation

This milestone includes an operator map with polling, secure token storage, refresh rotation, explicit foreground tracking consent, SQLite buffering and batch acknowledgements. It is **not a completed mobile release**. Background services, realtime operator subscriptions, historical replay and full platform integration tests are pending.

Flutter SDK is required. Bootstrap platform directories:

```sh
flutter create --platforms=android,ios --org org.geopulse .
flutter pub get
flutter analyze
flutter test
```

Add Android `INTERNET`, `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION` permissions and an iOS `NSLocationWhenInUseUsageDescription` before device testing. The bootstrap script in `scripts/mobile-bootstrap.py` automates these steps after `flutter create`. Do not add background permissions until the corresponding visible foreground-service/background lifecycle is implemented and reviewed.

Run with `flutter run --dart-define=API_URL=https://YOUR_DOMAIN`. The operator mode currently polls every 5 seconds; this is explicit, rather than presented as WebSocket realtime. Tracker mode rejects plain HTTP and stops when the app leaves the foreground. Queue retry resumes only while tracking is explicitly enabled. Pending records retain UUIDs and original timestamps.

A malformed/rejected batch remains queued; retry/quarantine tooling and hardware battery measurements remain release blockers. Platform folders are generated rather than checked in for this initial source milestone. The Flutter analyzer and tests have not been executed in the current environment.
