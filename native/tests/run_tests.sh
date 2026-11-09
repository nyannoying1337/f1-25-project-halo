#!/bin/sh
# Builds and runs the host tests (Windows x64, zig c++). Usage: sh tests/run_tests.sh [out-dir]
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
Z=$(ls -d "$(cygpath -u "$LOCALAPPDATA" 2>/dev/null)"/Microsoft/WinGet/Packages/zig.zig_*/zig-x86_64-windows-*/ 2>/dev/null | head -1)
ZIG=${ZIG:-${Z:+${Z}zig.exe}}
ZIG=${ZIG:-zig}
O=${1:-${TMPDIR:-/tmp}/halo_tests}
mkdir -p "$O"
"$ZIG" c++ -target x86_64-windows-gnu -std=c++20 -O1 -g -Wall -Wextra -DWIN32_LEAN_AND_MEAN -DNOMINMAX \
  -I "$HERE/include" -o "$O/test_game_state.exe" \
  "$HERE/tests/test_game_state.cpp" "$HERE/src/game_state_f1_25.cpp" "$HERE/src/hud_model.cpp" "$HERE/src/halo_track.cpp"
"$O/test_game_state.exe" "$O/leaves.txt"
echo "leaf list: $O/leaves.txt"
