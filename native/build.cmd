@echo off
rem Runs the host tests against fake game objects, then builds native\halo_hud.dll with zig (x86_64-windows-gnu).
rem zig: winget install zig.zig, or put zig.exe on PATH. Run from anywhere.
setlocal
set "ZIG="
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\zig.zig_*") do (
  for /d %%E in ("%%D\zig-x86_64-windows-*") do if exist "%%E\zig.exe" set "ZIG=%%E\zig.exe"
)
if not defined ZIG (
  where zig >nul 2>&1 && set "ZIG=zig"
)
if not defined ZIG (
  echo build: zig not found. Install it with: winget install zig.zig
  exit /b 1
)
cd /d "%~dp0"
if not exist build mkdir build
"%ZIG%" c++ -target x86_64-windows-gnu -std=c++20 -O1 -Wall -Wextra -DWIN32_LEAN_AND_MEAN -DNOMINMAX -I include ^
  -o build\test_game_state.exe tests\test_game_state.cpp src\game_state_f1_25.cpp src\hud_model.cpp src\halo_track.cpp || exit /b 1
build\test_game_state.exe build\leaves.txt || exit /b 1
"%ZIG%" c++ -target x86_64-windows-gnu -std=c++20 -O2 -DWIN32_LEAN_AND_MEAN -DNOMINMAX -I include -shared -s ^
  -o halo_hud.dll src\halo_hud.cpp src\game_state_f1_25.cpp src\hud_model.cpp src\diag_log.cpp src\halo_track.cpp || exit /b 1
echo built %~dp0halo_hud.dll
