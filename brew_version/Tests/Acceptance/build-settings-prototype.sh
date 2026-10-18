#!/bin/zsh
set -euo pipefail
exec "${0:A:h}/build.sh" --settings-prototype
