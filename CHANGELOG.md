# Changelog

Notable changes to KNX to OpenHAB are documented here in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Release versions are maintained in `VERSION` and published as Git tags.

## [Unreleased]

### Added

- HomeKit output can now be forced on/off from **Settings → General → HomeKit (Apple Home)** via the tri-state `general.homekit_enabled` override; ETS detection remains the default for CLI, Web UI jobs and previews. Independent optional `stop`/`stopSameDirection` switches remain disabled by default.
- Semantic versioning metadata and deterministic source release artifacts.
- A path-by-path audit of `dev` in `docs/AUDIT_dev.md`.

### Changed

- HomeKit blinds emit `sendUpDownForExtents="true"` on `WindowCovering` equipment metadata by default, including existing projects without the new key. An explicit `false` opts out of this intentional default change.
- Documentation now distinguishes CLI and Web UI defaults, the actual test commands, and safe uninstallation behavior.

### Removed

- Twelve superseded internal planning and design drafts after maintainer approval and an internal reference check; no runtime code or tests depended on them.
