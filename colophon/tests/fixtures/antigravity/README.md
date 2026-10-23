# Public schema projection

`schema.json` records public `FileDescriptorProto` message fields extracted from
`/Applications/Antigravity.app/Contents/Resources/bin/language_server`, SHA-256
`060ebf79719024f1b3acb52a21c7a182cb6466b2ac4ac25e93391169b1c1bb46`.
No conversations, identifiers, database rows or credentials were consulted.
`src/antigravity/schema.inc` projects the same field numbers, protobuf types and
repeated labels into the bounded wire validator. Only the explicitly named
message types are traversed with their qualified schemas; other declared message
fields get structural wire validation without guessing their content type.
Unknown fields remain opaque according to protobuf wire semantics.

Names must resolve through the owning file's package and typed references.
In particular `.exa.jetski_cortex_pb.CascadeTrajectorySummary.annotations` is
field 15 and refers to `.exa.jetski_cortex_pb.ConversationAnnotations`, whose
`archived` is field 4. `.exa.cortex_pb.ConversationAnnotations` is a different
message. `.exa.cortex_pb.RetryInfo` has `usage` at field 2 and `wait_time` at
field 7; a different `RetryInfo` contains a field-1 retry delay. Steps use
`.gemini_coder.Step`, not a fictitious `CortexStep`.

Field `type` and `label` retain their standard protobuf descriptor numeric
values. Enums remain raw wire integers here; usage/model normalization belongs
to a later provider deliverable. Every mutable fixture remains fresh synthetic
external scratch, constructed by unit helpers or the stdlib integration encoder.

The required SQLite projection uses INTEGER enum/index values, TEXT identities
and BLOB protobuf data. Dynamic TEXT/REAL/BLOB values in integer columns are
malformed facts, never coerced to integers. Optional enums explicitly retain
INTEGER, NULL/absent or invalid state; invalid enums diagnose without discarding
independent row identities or valid indexed protobuf blobs. Steps/generators
require an INTEGER `idx` to establish row identity; invalid or missing required
indexes reject the row. A NULL trajectory metadata blob ID is retained as absent.
Required column presence is checked separately from each row's dynamic value type.
