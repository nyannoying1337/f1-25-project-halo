# Project Halo — F1 25 addon (Swofty) — beta

<img src="icons/halo.png" alt="Project Halo icon" width="160">

Project Halo puts the onboard halo graphic from the 2026 F1 world feed in place of the 2026 dial of F1 25's 2026 Season Pack. The game's own HUD draws it, so you move and resize it in HUD customisation like any other element, and it hides when the game hides its HUD.

The halo reads the running game itself and changes nothing in it: no UDP telemetry, no companion app, and the game's telemetry settings make no difference.

**Download:** install it from the Addon Browser in the Swofty Launcher, or get the zip from [Releases](https://github.com/nyannoying1337/f1-25-project-halo/releases) and import it.

## What you get

- **Centre:** your speed in km/h and mph, the battery, and the Boost and Overtake lights, between the Recharge and Deploy bars.
- **Pedals:** throttle and brake bars on either side of the centre.
- **Right wing:** gear, revs and Active Aero.
- **Left wing:** your position and name, the car one place ahead in the classification, and the next turn's number and direction.
- **F1 2026 cars:** the halo replaces their 2026 dial. Other cars keep their own dials.

## How to start

1. Enable **Project Halo** in the launcher and start the game.
2. Open HUD customisation (in the settings, or the pause menu during a session) and select the dial.
3. Move and resize it, then go Back to save. Each HUD layout (practice, qualifying, race) keeps its own position and size.

Turn the addon off to get the stock dial back.

## Requirements

- F1 25 on Steam, build 25251167. After a game update the halo stops reading your car until a new version is out: it then shows only the values the game gives its own dial (battery, Overtake, Active Aero, your position).
- The official 2026 Season Pack, for the F1 2026 cars and their dial.
- Swofty Launcher 1.8.19 or newer, with Swofty Core 0.1.1 or newer.
- Offline sessions with the F1 2026 cars.

## Settings

In ADDON SETTINGS on the home menu (directly under Career, or F9 / R3), or in the launcher.

| Setting | Default | What it does |
|---|---|---|
| Driver names | On | Your position and name, and the car one place ahead in the session's classification (the car in P2 when you lead), on the left wing. Practice, qualifying and races; not in Time Trial |
| Turn numbers | On | The next turn's number and direction, from 220 m before it |
| Validation log | Off | Writes what the halo reads from the game, 30 times a second, as CSV to `%LOCALAPPDATA%\nick.f1-2026-halo\diag` (up to 64 MB per launch). Turn it on only to send a log |

## Beta status

- Driven so far: practice at Bahrain. Gear, revs, throttle, brake, battery, turn numbers, Overtake and the car ahead matched the game there.
- **Not confirmed yet:** Recharge and Deploy, Boost (pressed only once so far) and Active Aero.
- Qualifying and races have not been driven with the halo yet, and neither have cars with other dials (the halo should leave their dials as they are).

## Good to know

- Turn numbers follow the official F1 numbering on the 24 standard circuits. On reverse layouts and tracks without an official list, the halo finds the corners itself from the cars' line once a lap is covered and numbers them from the start line: those numbers are its own, not official.
- When a value cannot be read, its part of the halo stays empty. It never shows a made-up value.
- Split screen: the halo hides, because two cars are driven by players.
- When you spectate, the 2026 dial in the spectator HUD can show every part of the halo at once, with no live values.

**Something not working?** Turn on **Validation log**, drive a few laps, then attach the newest `halo_*.csv` from `%LOCALAPPDATA%\nick.f1-2026-halo\diag` (zipped) and your `loader.log` (newest folder in `%LOCALAPPDATA%\Swofty\sessions`) to an [issue](https://github.com/nyannoying1337/f1-25-project-halo/issues).

## How it works

- The addon's archives rebuild the game's 2026 dial as the halo, with a copy for the HUD editor. The game draws every part of it.
- `native/halo_hud.dll` reads your car, the session and its classification from the game's memory and writes the halo's own values into the game's HUD data. It changes nothing else in the game.
- The reader checks the game build first and switches itself off on any other build.
- The DLL links only KERNEL32 and the C runtime: no network library.
- `docs/architecture.md` shows how the parts fit together, and `native/src/game_state_f1_25.cpp` names the source of every value next to its read.

## Build

- `.\package.ps1 -NoInstall` runs the tests, builds `native\halo_hud.dll` with [zig](https://ziglang.org) (`winget install zig.zig`) and writes the zip to `dist\`. `native\build.cmd` runs the tests and builds only.
- The archives in `erp\` are built from the game's own UI archives, so they are not in this repository: take them from a release zip, or rebuild them with `python -I tools/native/build_native.py <folder with the stock archives> <sprites dir> . <work dir>`. Set `SWOFTY_TOOLS` to the Swofty repository's `tools` folder first.
- Graphics: `tools/halo.js` is the reference drawing. `tools/export_native.html` renders it into the sprites: dump its DOM with headless Chrome (`--dump-dom`) to `<sprites dir>/dom.html`, then run `python -I tools/native/textures.py <sprites dir>/dom.html <sprites dir>`. The page needs the [Saira](https://fonts.google.com/specimen/Saira) variable font saved as `tools/saira.ttf`.
- Validation log: `python -I tools/ingame/analyze_diag.py <halo_*.csv> <report.md>` checks a log field by field.

## License

[Project Halo Attribution License 1.0](LICENSE). The Swofty SDK headers in `native/include` keep their MIT license.

Official turn numbers: F1 live-timing circuit data (via the MultiViewer API), converted by `tools/corners_hpp.py`. Graphics drawn with the Saira typeface (SIL Open Font License).

Fan-made. Not affiliated with or endorsed by the FIA, Formula 1, EA or Codemasters.
