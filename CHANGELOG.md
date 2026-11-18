# Changelog

Notable changes to KNX to OpenHAB are documented here in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Release versions are maintained in `VERSION` and published as Git tags.

## [Unreleased]

### Added

- Semantic versioning metadata and deterministic source release artifacts.
- A path-by-path audit of `dev` in `docs/AUDIT_dev.md`.
- HomeKit rollershutter settings in the Web UI and `general.homekit_*` configuration keys.

### Changed

- Documentation now distinguishes CLI and Web UI defaults, the actual test commands, and safe uninstallation behavior.
- HomeKit rollershutters now send `sendUpDownForExtents=true` on the `WindowCovering` group by default; existing configurations without the key inherit the new default, and an explicit `false` opts out.

### Removed

- Twelve superseded internal planning and design drafts after maintainer approval and an internal reference check; no runtime code or tests depended on them.
