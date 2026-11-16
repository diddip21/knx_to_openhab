# Changelog

All notable changes to KNX to OpenHAB are documented here.

## [Unreleased]

- HomeKit blinds: emit `sendUpDownForExtents="true"` on `WindowCovering` equipment metadata by default (including existing projects without the new key); add explicit opt-out plus independent optional `stop`/`stopSameDirection` switches.
- HomeKit output can now be forced on/off from **Settings → General → HomeKit (Apple Home)** via the tri-state `general.homekit_enabled` override; ETS detection remains the default for CLI, Web UI jobs and previews.
- Introduce semantic versioning and automated source release artifacts.
