# Immutable Claude codec decoder inputs

`synthetic-v1.rec` is a conspicuously invented CLCD1 input. Its paths, aliases,
IDs, clocks, sizes and rates are fictional. It contains two duplicate raw rows,
including a zero recorded cost and a distinct loser-row price snapshot.

Keep this file unchanged when adding codec versions. Tests copy it to private
scratch before decoding and keep every old decoder. Generated runtime records
remain outside the checkout. Version 1 is the first Claude codec; the unrelated
Codex native codec keeps its own existing format.

`synthetic-v2.rec` was exported once by the unchanged CLCD2 encoder from the
synthetic successful-handback unit transcript. Its file identity, timestamps,
paths and IDs are invented; its config provenance is empty. The turn was reset
to open with no end or answer clock before encoding. Keep these bytes immutable.

`synthetic-v3.rec` retains the same invented CLCD2 facts with a synthetic parser
revision appended in CLCD3 format. Keep these bytes immutable to exercise the
CLCD3 decoder after the encoder moves to CLCD4.

`synthetic-v4.rec` uses the same invented zero-usage facts in CLCD4 format;
there are no per-row ownership values to append. Keep it immutable for the
CLCD4 decoder.
