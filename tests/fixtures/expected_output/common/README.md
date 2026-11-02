# Shared Golden Output

`influxdb.persist` is the reference persistence output shared by Charne, Mini, and UploadJson because all three generated files are byte-for-byte identical.

The integration test uses a project-specific `influxdb.persist` when one exists and falls back to this shared file otherwise. Golden regeneration keeps a local copy only when a project's persistence output differs from the shared reference.
