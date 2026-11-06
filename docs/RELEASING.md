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
3. Run CI and confirm the core, lint, and UI jobs pass.
4. Merge the version and changelog update to `main`.
5. From the release commit on `main`, create and push an annotated tag:

   ```bash
   VERSION=1.2.3  # Set this to the value committed in VERSION.
   git switch main
   git pull --ff-only origin main
   git tag -a "v${VERSION}" -m "Release ${VERSION}"
   git push origin "v${VERSION}"
   ```

The workflow checks that the tag version matches `VERSION`. It builds a
reproducible archive from tracked source files and publishes the archive and
its `.sha256` sidecar as GitHub release assets. Release-channel detection
checks for a prerelease suffix before any build metadata, so
`1.2.3+build-7` remains stable while `1.2.3-rc.1` is a prerelease.
For example, pushing `v1.3.0-rc.1` publishes a prerelease. Install it on a
dedicated test system with `bash install.sh --update --version 1.3.0-rc.1`.

## Test a Moving Branch

The installed Web UI updater and the top-level installer's normal update path
accept published release tags, not branch names. Use the isolated worktree
procedure in the [Developer Guide](DEVELOPER_GUIDE.md#testing-main-or-dev-in-a-separate-checkout)
to test the current `main` or `dev` source without changing an installed
release. Publish a prerelease tag when a production-like update test is needed.

## Installer version selection

The top-level installer resolves `--install` and `--update` to GitHub's
latest published stable release when no version is supplied. Use
`--version X.Y.Z` to request an exact published stable or prerelease version;
the `v` tag prefix is omitted. Prereleases are never selected by default.
`--repair` does not query GitHub or fetch a release. If no matching release
exists, the installer stops instead of falling back to the moving `main`
branch.

This installer step checks the selected GitHub release metadata and checks out
its exact tag. Downloading the release archive and verifying its checksum
before staged activation belongs to the transactional updater work in
[#26](https://github.com/diddip21/knx_to_openhab/issues/26). The Web UI exposes
the current version and update controls through its version API. Add any
release-specific migration guidance to the dated changelog section when
preparing that release.
