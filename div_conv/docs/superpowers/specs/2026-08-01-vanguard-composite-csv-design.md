# Vanguard Composite CSV Support

## Problem

Vanguard can export one CSV containing multiple blank-record-separated tables. A
holdings table appears first, the supported investment transaction table appears
later, and a separate account-activity table may follow it. `div_conv` currently
uses the first nonblank record as the only possible CSV header, so it rejects this
export before reaching the valid Vanguard transaction contract.

## Scope

Support Vanguard composite exports without changing the Fidelity contracts, the
Vanguard transaction fields, supported actions, configuration schema, cooked CSV
shape, QIF rendering, or all-artifact transaction guarantees.

The known-working local Fidelity History export is an explicit compatibility
baseline. Its automatic detection and conversion behavior must be unchanged by
the Vanguard repair.

The converter must:

- search the CSV records for declared headers matching registered brokerage
  contracts rather than inspecting only the first nonblank record;
- select Vanguard when exactly one embedded Vanguard transaction table is found;
- retain the existing ambiguous-contract error if contracts for multiple
  brokerages occur in the same file;
- reject multiple matching transaction tables rather than silently choosing one;
- parse only the selected Vanguard transaction table;
- ignore Vanguard tables before and after that selected table;
- preserve physical source row numbers in diagnostics and transaction summaries;
- preserve the selected transaction header, including extra declared columns, and
  selected transaction rows in the cooked CSV; and
- continue validating every row in the selected transaction table before any
  output is committed.

## Design

Header discovery will read normalized CSV records and record every row whose
fields satisfy one of the adapter's required header variants. Detection will use
the set of brokerages represented by those matches. No match remains an unknown
contract; matches for multiple brokerages remain ambiguous; more than one match
for a selected brokerage is rejected as multiple transaction tables.

`read_source` will advance to the uniquely selected adapter header instead of
assuming that the first declared record is the header. For an embedded Vanguard
table, blank records mark a possible section boundary. The next recognized
Vanguard non-transaction section header ends the selected transaction table.
Ordinary blank records inside a standalone transaction export remain ignorable.
Unexpected rows that are not a recognized section boundary continue through the
normal width, action, date, amount, and output-safety validation, preventing a
malformed transaction from being hidden as ignored trailer content.

The initial Vanguard holdings table and following account-activity table headers
will be represented as adapter-owned surrounding-section contracts. Their rows are
not transaction input and will not be copied into either output artifact.

## Error Handling

CSV decoding and parsing errors retain their existing actionable wrapping. A
composite export lacking the Vanguard transaction header remains an unknown
contract. Duplicate Vanguard transaction sections receive a specific error so
the user is not left with silently incomplete output. Rows inside the selected
table retain their physical file line numbers in all failures.

## Testing and Verification

Add an end-to-end CLI regression test using conspicuously synthetic data with the
same three-table topology as the Vanguard export. The test must first reproduce
the current unknown-contract failure. After implementation it must assert:

- automatic Vanguard detection succeeds;
- only the investment transaction rows enter the cooked CSV and QIF;
- extra transaction-header columns are preserved;
- source row numbers refer to the original composite file; and
- the surrounding tables do not appear in generated output.

Add focused coverage for duplicate embedded transaction tables and for malformed
rows within the selected table if existing tests do not already exercise those
invariants. Run the complete `pytest tests -v` suite, the repository's uv-header
drift guard because the launcher changes, and a controlled conversion of the
reported local Vanguard export into a temporary output directory with console
output kept private. Repeat that controlled conversion with the reported
known-working Fidelity History export and compare its artifact count and success
status with a pre-change baseline. Temporary generated artifacts must be removed
after validation.
