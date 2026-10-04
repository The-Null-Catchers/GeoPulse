# Screenshot provenance

`live-operations.png` was captured by Playwright from the real Docker Compose environment in [CI run 37240412037](https://github.com/The-Null-Catchers/GeoPulse/actions/runs/37240412037), code commit `f1fa82d`.

The test provisions an authenticated workspace/device, posts two GPS points, blocks REST device-list resync before the second update, checks WebSocket delivery and rendered MapLibre fleet features, waits for map rendering to settle, and captures the page. The source PNG is unchanged. Its single-device workspace is an integration scenario, not a fabricated fleet dataset. OpenStreetMap attribution is visible. Run the simulator to demonstrate a larger moving fleet.
