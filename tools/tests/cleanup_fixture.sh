#!/bin/sh
# Remove only explicitly supplied fixture paths; missing glob matches are harmless.
remove_fixture_paths() {
    for fixture_path do
        case "$fixture_path" in
            '') return 1 ;;
            *[!./]*) ;;
            *) return 1 ;;
        esac
        if [ -L "$fixture_path" ] || [ -f "$fixture_path" ]; then
            rm -- "${fixture_path:?}" || return
        elif [ -d "$fixture_path" ]; then
            rm -r -- "${fixture_path:?}" || return
        elif [ -e "$fixture_path" ]; then
            rm -- "${fixture_path:?}" || return
        fi
    done
}
