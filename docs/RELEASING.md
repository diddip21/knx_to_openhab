# Releasing

The release workflow publishes a source archive and its SHA-256 checksum when a
version tag is pushed.

## Prepare a release

1. Set `VERSION` to the release's SemVer version, without a `v` prefix.
2. Move the corresponding notes from `[Unreleased]` into a dated
   `[x.y.z] - YYYY-MM-DD` section in `CHANGELOG.md`. Include any migration
   instructions users need for that version.
3. Merge the version and changelog update to `main`.
4. Push an annotated tag named `v<version>` at that commit.

The workflow checks that the tag version matches `VERSION`. It builds a
deterministic archive from tracked source files and publishes the archive and
its `.sha256` sidecar as GitHub release assets. Tags such as
`v0.2.0-rc.1` are published as prereleases; tags without a prerelease suffix
are published as stable releases.

The release workflow establishes tagged releases and prerelease marking. It
does not yet provide separate beta channels or make the installer, CLI, or Web
UI select or display a release version.
