# Immutable Claude codec decoder inputs

`synthetic-v1.rec` is a conspicuously invented CLCD1 input. Its paths, aliases,
IDs, clocks, sizes and rates are fictional. It contains two duplicate raw rows,
including a zero recorded cost and a distinct loser-row price snapshot.

Keep this file unchanged when adding codec versions. Tests copy it to private
scratch before decoding and keep every old decoder. Generated runtime records
remain outside the checkout. Version 1 is the first Claude codec; the unrelated
Codex native codec keeps its own existing format.
