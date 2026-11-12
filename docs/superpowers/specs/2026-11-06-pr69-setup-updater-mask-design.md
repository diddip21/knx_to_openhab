# Setup Updater Mask Follow-Up

## Intent

Keep setup's file-mutation window isolated even when a finishing updater restarts
the Web UI before `knxohui-update.service` becomes inactive.

## Approaches Considered

- **Temporary systemd runtime mask (chosen):** after stopping the Web UI, runtime-mask the updater unit, wait for active work and cancel queued jobs, stop the Web UI again after the updater exits, verify idle once more, then unmask on success or from the setup exit trap. This blocks new systemd updater starts throughout setup without changing persistent enablement or the shared file-lock protocol.
- **Second Web UI stop only:** simpler, but another caller can queue an updater after the check; it does not close the start window.
- **Hold the updater lock through setup:** strong serialization, but setup's repair helper also acquires that lock and would need a new lock-transfer contract.

## Goals and Constraints

- Runtime-mask only units setup itself masks; preserve units that were already masked.
- A missing updater unit remains a successful first-install case.
- Keep the runtime mask until all setup mutations and service restarts are complete.
- Restore the owned runtime mask on both success and failure, before restoring a previously active Web UI.
- No persistent unit enablement changes, new sudoers authority, or updater-lock changes.
- Wait for a running transactional updater to finish; do not kill it.
- Re-stop the Web UI after the updater becomes inactive because the updater health check restarts that service.

## Acceptance

- Tests verify mask ownership/preservation, second Web UI stop, final quiescence, and cleanup ordering.
- A new start is systemd-blocked while setup's mutation window is open.
- If the updater cannot quiesce, setup exits before application/runtime mutations and its trap restores an owned mask and prior services.
