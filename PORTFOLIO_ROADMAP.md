# GeoPulse portfolio roadmap

Baseline reviewed on November 17, 2026. Repository roadmap published on November 18, 2026.

This roadmap applies to this repository and follows the shared Null Catchers portfolio plan. Verify the documented state against the current code and runs before starting work.

**Estimated initial demo effort** 40–65 hours for a developer familiar with the project. The estimate excludes external reviews, store accounts, target environment setup, and later milestones.

## Project priorities

**Documented state** GPS data flows through PostGIS, an outbox, and Redis/WebSocket. The project includes a simulator, geofences, trips, and replay. The registry searches across the workspace by name. Physical devices still need to verify background tracking.

**P0 — Demo** Build a reproducible route from GPS ingestion through geofence crossing, stop detection, and trip replay.

**P1 — Validation and depth** Confirm whether durable cursors and resync are needed. Test reconnect, duplicates, and out-of-order points, and document the event recomputation policy. Validate authentication for demo and operator accounts.

**P2 — Later** Measure background tracking battery use and permissions on physical devices before expanding it. Consider OSRM and route editing after preparing data. Document what the route heuristics optimize.

**Acceptance criteria** Stored GPS points drive replay at the recorded times. Search covers the workspace, and a qualifying geofence crossing creates one event. The simulator is identified as synthetic.

**Demo scenario** Twenty simulated devices → vehicle crosses a geofence → alert → trip replay. [README](https://github.com/The-Null-Catchers/GeoPulse/blob/main/README.md), [Validation](https://github.com/The-Null-Catchers/GeoPulse/blob/main/docs/VALIDATION.md).

## Next milestones

[PR #12](https://github.com/The-Null-Catchers/GeoPulse/pull/12) verified that the paged and filtered device registry can open a device outside the loaded list. The live map displays up to 1,000 loaded devices.

1. [ ] Prepare a synthetic route with expected UTC times for crossing, stopping, and resuming. Confirm those timestamps in a new workspace.
2. [ ] Resend the same GPS batch and replay the trip. Check for one crossing event and matching start, end, and stop times.
3. [ ] Capture the map, alert, and replay from the same run. Record the SHA, data source, registry search scope, and map display scope.

## Portfolio acceptance checklist

- [ ] Another person can reproduce the primary workflow from a clean checkout using the README and test credentials or fixtures.
- [ ] The demo tells one complete story with a defined user, problem, and saved result.
- [ ] Tests cover the main flow, an important failure, and access boundaries when multiple accounts are involved.
- [ ] Demo data is labeled synthetic and reproducible. Review screenshots and recordings for secrets and customer data.
- [ ] Include four to six real screenshots where appropriate, a 60–120 second recording, and working links. Identify the revision used for capture.
- [ ] The README describes implemented capabilities, setup, architecture, limits, tests, and the demo.
- [ ] A short case study explains two engineering decisions, a considered alternative, and how the system handles an actual failure.
- [ ] Release evidence records the commit SHA, CI, prerequisites, and limits. Performance data includes workload, hardware, and method.
- [ ] Licensing and contributor attribution are settled before distribution. Choose the license for each repository individually.

A hosted demo is optional. Code execution, server administration, and secret management can be demonstrated through a recording and a reproducible isolated environment. Keep public demo access scoped to the activities it needs.

## Implementation and follow-up

- Break P0 into tasks with expected behavior, acceptance criteria, and a suitable test.
- Verify existing functionality first. Update this plan when evidence tied to a commit or PR closes a milestone.
- Record the fixture source, the revision used for evidence, and the tested limits.
- Review the final diff and verify required checks for its exact SHA before merging. Follow branch protection.
- For documentation-only changes with no applicable workflow, verify content and links and record the checks actually performed.
- Tie performance, security, and readiness claims to supporting evidence.
