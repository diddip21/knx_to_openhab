# Releasing

The release workflow publishes a deterministic source archive and its SHA-256
checksum when a version tag is pushed.

## Release channels

Stable releases use a SemVer version without a prerelease suffix, for example
`1.2.3`. Beta and release-candidate versions use SemVer prerelease identifiers
such as `1.3.0-beta.1` and `1.3.0-rc.1`. Both are published as GitHub
prereleases. Build metadata after `+` does not make a version a prerelease.

## Prepare a release

1. Set `VERSION` to the release's SemVer version, without a `v` prefix.
2. Move the corresponding notes from `[Unreleased]` into a dated
   `[x.y.z] - YYYY-MM-DD` section in `CHANGELOG.md`. Include any migration
   instructions users need for that version.
3. Merge the version and changelog update to `main`.
4. Push an annotated tag named `v<version>` at that commit.

The workflow checks that the tag version matches `VERSION`. It builds a
reproducible archive from tracked source files and publishes the archive and
its `.sha256` sidecar as GitHub release assets. Release-channel detection
checks for a prerelease suffix before any build metadata, so
`1.2.3+build-7` remains stable while `1.2.3-rc.1` is a prerelease.

## Installer version selection

The top-level installer resolves `--install` and `--update` to GitHub's
latest published stable release when no version is supplied. Use
`--version X.Y.Z` to request an exact published stable or prerelease version;
the `v` tag prefix is omitted. Prereleases are never selected by default.
`--repair` does not query GitHub or fetch a release. If no matching release
exists, the installer stops instead of falling back to the moving `main`
branch.

The installer checks selected GitHub release metadata and checks out its exact
tag. The Web UI updater downloads the matching source archive and `.sha256`
asset, verifies the digest, builds a separate Python environment, and only then
atomically switches the `current` release link. If the service health endpoint
fails, it restores the prior link (or the legacy installation) and restarts the
previous version. External configuration and runtime data stay in their
existing paths; this project currently has no release-specific data migrations.
After a successful health check, the updater keeps the active and immediately
previous release and removes older release environments. A rejected release is
removed after rollback succeeds.

CLI and Web UI version display and release-specific migration notes remain open
work for [#30](https://github.com/diddip21/knx_to_openhab/issues/30).
