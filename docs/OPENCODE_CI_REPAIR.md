# Generic approved-task CI repair

See [AI_AUTOMATION.md](AI_AUTOMATION.md). The repair controller is no longer
bound to a particular issue or plan version. It derives both from the verified
AI branch and binds them to the original live owner command and explicit scope.

Only a failed, explicitly dispatched CI for the exact current SHA of a same-repo
bot Draft PR against `dev` is eligible. The publisher independently rechecks
all evidence and files. At most two attempts, existing approved files only,
fast-forward updates only, no main/dev writes and no auto-merge.

An old pilot PR without scoped authorization is not silently adopted.
