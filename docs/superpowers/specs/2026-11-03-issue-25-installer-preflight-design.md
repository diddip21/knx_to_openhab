# Issue #25: Installer preflight checks

## Intent

Make installer failures easier to diagnose and avoid starting system-changing work when the host cannot complete installation. This is the first focused PR toward #25, not a claim that installation or `installer/setup.sh` is fully idempotent.

## Scope and acceptance

- Validate the host OS, Python/venv capability, required disk space, and required network access before the corresponding package, checkout, or setup operations.
- Preserve existing install/update/repair/cancel behavior and make release-network checks mode-aware: only install/update fetch releases. Repair still uses the existing apt dependency step, so this PR does not promise a fully offline repair.
- On a failed preflight, print a specific actionable message and return nonzero before changing packages, files, or services.
- Add automated tests proving both the passing path and that failed checks precede side effects.

## Non-goals

- Making all setup operations idempotent, adding reinstall semantics, or guaranteeing recovery from mid-setup failure.
- Replacing the isolated installer lifecycle work tracked by #31.
- Changing release selection or the installed application/runtime configuration.

## Approaches considered

1. Add named preflight functions directly to `install.sh`, retaining the standalone `curl | bash` bootstrap behavior while testing the functions by sourcing the guarded script; **chosen** because the bootstrap cannot assume another local file exists before it clones the project.
2. Add a separate local preflight helper and fetch/source it remotely during bootstrap. This complicates bootstrap integrity and creates another network dependency before the check; rejected.
3. Build the full lifecycle harness first. This would exercise more real-world behavior but is larger and overlaps #31; defer it.

## Implementation decisions

- Keep the existing mode selection and cancel path ahead of system checks so `--help`/`--cancel` remain side-effect-free.
- Perform host/runtime/disk checks before installing dependencies. Perform the GitHub release/network checks only for modes that need a release; do not imply that `--repair` is fully offline while it still runs `apt-get update`.
- Use injectable command seams only where needed for deterministic tests; do not add a runtime dependency or require a second bootstrap file.
- Treat the disk threshold as an explicit documented constant based on the checkout and install workflow, rather than pretending to predict all package sizes; test exact-boundary and insufficient-space behavior.
- Preserve clear diagnostics and stable nonzero exit behavior for failed checks.

## Review and delivery

Use regression-first tests, run focused then full applicable checks, open one PR linked to #25, and run the configured review loop. Address valid findings and re-run checks until the PR is clean and ready to merge; do not merge without separate confirmation.
