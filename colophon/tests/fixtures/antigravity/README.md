# Public enum fixtures

`enums.json` independently records the fully qualified CortexStepStatus,
CortexStepType and CortexTrajectorySource definitions from the public
Antigravity language_server.
Status/type/source mapping is exercised through corpus projection; unknown
integer enum values remain valid raw facts with the documented reducer default.

The required SQLite projection uses INTEGER enum/index values, TEXT identities
and BLOB protobuf data. Dynamic TEXT/REAL/BLOB values in integer columns are
malformed facts, never coerced to integers. Optional enums explicitly retain
INTEGER, NULL/absent or invalid state; invalid enums diagnose without discarding
independent row identities or valid indexed protobuf blobs. Steps/generators
require an INTEGER `idx` to establish row identity; invalid or missing required
indexes reject the row. A NULL trajectory metadata blob ID is retained as absent.
Required column presence is checked separately from each row's dynamic value type.
