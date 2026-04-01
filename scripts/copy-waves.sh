#!/usr/bin/env bash

# Copy/symlink generated waveforms and logs to a common simulation directory.
#
# This script:
#   1. Takes one or more waveform files as arguments (e.g., .vcd, .fst, .wlf).
#   2. Creates/uses a common directory under:
#        <repo-root>/build/sim-common
#   3. For each waveform passed as argument:
#        - Removes any existing waves.<ext> in sim-common
#        - Symlinks the given file as waves.<ext> (e.g., waves.vcd, waves.fst)
#      This provides a stable, tool-agnostic path for the "primary" waveform.
#   4. Scans the directory of the *first* waveform for additional .vcd files:
#        - For each .vcd found:
#            - Removes any existing file with the same name in sim-common
#            - Symlinks it into sim-common (keeping the original filename)
#      This is useful when the simulator emits multiple VCDs (e.g., per module).
#   5. If a sim-trace.log exists next to the first waveform:
#        - Removes any existing sim-trace.log in sim-common
#        - Symlinks it as sim-trace.log
#      This is typically an execution trace / log produced by the simulator.
#
# Usage:
#   copy-waves.sh wave_file [wave_file ...]
#
# Notes:
#   - Files are symlinked (ln -sr), not copied, so changes propagate and disk
#     usage stays minimal.
#   - Existing targets in build/sim-common are removed before linking to ensure
#     a clean, up-to-date view of the latest simulation run.

# Determine the repository root via git
ROOT_DIR=$(git rev-parse --show-toplevel)

# Ensure common simulation output directory exists
mkdir -p "$ROOT_DIR/build/sim-common"

# Link the main wave files as waves.<ext>
for file in "$@"; do
    [ ! -f "$file" ] && continue
    FILE_EXT="${file##*.}"
    rm -f "$ROOT_DIR/build/sim-common/waves.$FILE_EXT"
    ln -sr "$file" "$ROOT_DIR/build/sim-common/waves.$FILE_EXT"
done

# Additionally copy/link all .vcd wave files from the directory of the first argument
FILE_LIST=$(find "$(dirname "$1")" -name "*.vcd")
for file in $FILE_LIST; do
    rm -f "$ROOT_DIR/build/sim-common/$(basename "$file")"
    ln -sr "$file" "$ROOT_DIR/build/sim-common/"
done

# Copy/link execution trace log, if present
TRACE_FILE="$(dirname "$1")/sim-trace.log"
if [ -f "$TRACE_FILE" ]; then
    rm -f "$ROOT_DIR/build/sim-common/sim-trace.log"
    ln -sr "$TRACE_FILE" "$ROOT_DIR/build/sim-common/"
fi

exit 0
