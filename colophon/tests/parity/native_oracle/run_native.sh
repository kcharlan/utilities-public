#!/bin/sh
# Invoked by the protected Python runner, inside its sandbox and fake HOME.
/usr/bin/xcrun xctest -XCTest ColophonNativeOracleTests.ColophonNativeOracleTests/testExportScopedSnapshot "$1" > "$HOME/native-run.stdout" 2> "$HOME/native-run.stderr"
result=$?
/bin/cat "$HOME/native-run.stdout"
/bin/cat "$HOME/native-run.stderr" >&2
exit "$result"
