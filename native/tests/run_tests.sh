#!/bin/sh
# Builds and runs the host tests (Windows x64, zig c++). Usage: sh tests/run_tests.sh [out-dir]
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
Z=$(ls -d "$(cygpath -u "$LOCALAPPDATA" 2>/dev/null)"/Microsoft/WinGet/Packages/zig.zig_*/zig-x86_64-windows-*/ 2>/dev/null | head -1)
ZIG=${ZIG:-${Z:+${Z}zig.exe}}
O=${1:-${TMPDIR:-/tmp}/halo_tests}
mkdir -p "$O"
"$ZIG" c++ -target x86_64-windows-gnu -std=c++20 -O1 -g -Wall -Wextra -DWIN32_LEAN_AND_MEAN -DNOMINMAX \
  -I "$HERE/include" -o "$O/test_game_state.exe" \
  "$HERE/tests/test_game_state.cpp" "$HERE/src/game_state_f1_25.cpp" "$HERE/src/hud_model.cpp" "$HERE/src/halo_track.cpp" \
  "$HERE/src/gmeter.cpp"
"$O/test_game_state.exe" "$O/leaves.txt"
echo "leaf list: $O/leaves.txt"
# timing tower: reader, model, leaf publisher, bench (writes $O/tower_leaves.txt)
"$ZIG" c++ -target x86_64-windows-gnu -std=c++20 -O1 -g -Wall -Wextra -DWIN32_LEAN_AND_MEAN -DNOMINMAX \
  -I "$HERE/include" -o "$O/test_tower.exe" \
  "$HERE/tests/test_tower.cpp" "$HERE/src/tower_reader.cpp" "$HERE/src/tower_model.cpp" "$HERE/src/tower_leaves.cpp" \
  "$HERE/src/tower_state.cpp" "$HERE/src/diag_log.cpp" "$HERE/src/tower_anim.cpp"
"$O/test_tower.exe" "$O"
echo "tower leaf list: $O/tower_leaves.txt"
# G-force meter: filter, indicator rules, flash, model wiring, leaves
"$ZIG" c++ -target x86_64-windows-gnu -std=c++20 -O1 -g -Wall -Wextra -DWIN32_LEAN_AND_MEAN -DNOMINMAX \
  -I "$HERE/include" -o "$O/test_gmeter.exe" \
  "$HERE/tests/test_gmeter.cpp" "$HERE/src/gmeter.cpp" "$HERE/src/hud_model.cpp" "$HERE/src/halo_track.cpp"
"$O/test_gmeter.exe"
# the halo's animations: triggers, snap rules, pulse rules, Animations off, cost
"$ZIG" c++ -target x86_64-windows-gnu -std=c++20 -O1 -g -Wall -Wextra -DWIN32_LEAN_AND_MEAN -DNOMINMAX \
  -I "$HERE/include" -o "$O/test_halo_anim.exe" "$HERE/tests/test_halo_anim.cpp"
"$O/test_halo_anim.exe"
# the broadcast cards' leaves: rules, fail-closed inputs, write rules (writes $O/cards_leaves.txt)
"$ZIG" c++ -target x86_64-windows-gnu -std=c++20 -O1 -g -Wall -Wextra -DWIN32_LEAN_AND_MEAN -DNOMINMAX \
  -I "$HERE/include" -o "$O/test_cards.exe" "$HERE/tests/test_cards.cpp" "$HERE/src/tower_reader.cpp" \
  "$HERE/src/tower_state.cpp"
"$O/test_cards.exe" "$O"
# the element switches: what runs for every combination, and the highlights clip rule
"$ZIG" c++ -target x86_64-windows-gnu -std=c++20 -O1 -g -Wall -Wextra -I "$HERE/include" -o "$O/test_elements.exe" \
  "$HERE/tests/test_elements.cpp"
"$O/test_elements.exe"
