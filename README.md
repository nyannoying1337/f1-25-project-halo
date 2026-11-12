# Project Halo — F1 25 addon (Swofty) — beta

<img src="icons/halo.png" alt="Project Halo icon" width="160">

Project Halo puts the onboard halo graphic from the 2026 F1 world feed in place of the dial of F1 25's 2026, 2025 and F2 cars, and an animated, broadcast-style timing tower in place of the Track Position list. The game's own HUD draws both, so you move and resize them in HUD customisation like any other element, and they hide when the game hides its HUD.

Project Halo reads the running game itself and changes nothing in it: no UDP telemetry, no companion app, and the game's telemetry settings make no difference.

**Download:** install it from the Addon Browser in the Swofty Launcher, or get the zip from [Releases](https://github.com/nyannoying1337/f1-25-project-halo/releases) and import it.

![The halo on a 2026 car](https://raw.githubusercontent.com/nyannoying1337/f1-25-project-halo/v0.2.0-beta/docs/media/halo-2026.jpg)

![Timing tower: two cars pass and their rows slide into their new places](https://raw.githubusercontent.com/nyannoying1337/f1-25-project-halo/v0.2.0-beta/docs/media/tower-rows.gif)
![Timing tower: a red flag card slides out of the header and rolls back up](https://raw.githubusercontent.com/nyannoying1337/f1-25-project-halo/v0.2.0-beta/docs/media/tower-flag-card.gif)

*Preview renders. In the game, the texts use the game's own font, and the game's team logos replace the small team labels.*

## What you get

- **The halo:** your speed in km/h and mph, the battery, and the Boost and Overtake lights in the centre, between the Recharge and Deploy bars. Throttle and brake bars on either side. Gear, revs and Active Aero on the right wing. Your position and name, the car one place ahead in the classification, and the next turn's number and direction on the left wing.
- **2025 and F2 cars:** the same halo with DRS. 2025 cars also show the ERS deploy mode (NONE, MEDIUM, HOTLAP, OVERTAKE), the battery and Recharge and Deploy. F2 cars have no energy parts.
- **Timing tower:** positions, team logos and colours, driver codes, intervals or gaps to the leader, tyres, PIT, Out, DSQ and NC, and a green or red arrow when a car gains or loses a place. Its header shows the lap or the session, and the safety car, virtual safety car, yellow flag, red flag and chequered flag. Practice, qualifying, races, Time Trial, replays and the spectator view, with up to 30 cars.
- **Tower animations:** when cars change places, their rows slide into their new positions, fast at first and then settling, like the broadcast. The position arrow rides in with its row, and the position number and a new best lap time fade in. Flag cards (yellow flag, VSC, safety car, red flag, chequered flag) slide down out of the header and the rows move down with them; when the flag ends, the card rolls back up and the rows close the gap. The Animations setting switches them off.
- **Lap times in practice and qualifying:** the leader's best lap and every other car's gap to it. A new personal best flashes green for 2 seconds, a new session best purple. The header shows the session's clock, and in Q1 and Q2 (SQ1 and SQ2 in sprint qualifying) a red hatch marks the cars in the knockout zone.
- **Fastest lap in races:** a purple stopwatch beside the car with the fastest lap.
- **Race Control banner:** the game's own race messages, in the style of the broadcast's Race Control banner.
- **Spectator view:** the halo shows the car you watch, and the tower replaces the spectator board with that car highlighted. The tower follows the Spectator Menu's Gap and Detail options.
- **G-force meter (optional):** the 2026 broadcast's G-force meter in the middle of the halo.

## How to start

1. Enable **Project Halo** in the launcher and start the game.
2. Open HUD customisation (in the settings, or the pause menu during a session) and select the dial or the Track Position list.
3. Move and resize them, then go Back to save. Each HUD layout (practice, qualifying, race) keeps its own position and size.

Turn the addon off to get the stock dial and Track Position list back.

## Requirements

- F1 25 on Steam, build 25251167. After a game update Project Halo stops reading the game until a new version is out: the halo then shows only the values the game gives its own dial (battery, Overtake, Active Aero, your position).
- The official 2026 Season Pack.
- Swofty Launcher 1.8.36 or newer, with Swofty Core 0.1.1 or newer.
- Offline sessions.

## Settings

In ADDON SETTINGS on the home menu (directly under Career, or F9 / R3), or in the launcher.

| Setting | Default | What it does |
|---|---|---|
| Driver names | On | Your position and name, and the car one place ahead in the session's classification (the car in P2 when you lead), on the left wing. Practice, qualifying and races; not in Time Trial |
| Turn numbers | On | The next turn's number and direction, from 220 m before it |
| G-force meter | Off | Replaces the speed, Boost, Overtake, battery and Recharge and Deploy in the middle of the halo with the G-force meter: the cornering, braking and acceleration force in g, and a cyan arc on the side it pushes the driver |
| Halo in 2025 and F2 cars | On | The halo in 2025 and F2 cars too, in place of their dials. Off: their own dials come back. 2026 cars always show the halo |
| Timing tower | On | The timing tower in place of the Track Position list |
| Tower layout | Around me | Around me: the rows around your position. Leaders: the top of the order. Full field: every classified car |
| Tower rows | 5 | How many rows Around me and Leaders show (3 to 22) |
| Gap mode | Interval | Interval: time to the car ahead. Leader: time to the leader. Auto: switches between the two. Lapped cars show +1 LAP. The spectator view follows the Spectator Menu's Gap option instead |
| Auto switch every (s) | 10 | Seconds between Interval and Leader when Gap mode is Auto (5 to 60) |
| Tower header | On | The logo and the lap counter in races, the session name in practice and qualifying, TIME TRIAL and the lap in Time Trial, and the safety car, virtual safety car and chequered flag states |
| Tyres | On | Each car's current tyre: S, M, H, I or W |
| Position arrows | On | A green or red arrow for 3 seconds when a car gains or loses a place |
| Intervals | On | The gap column: times in races (see Gap mode), and PIT, Out, DSQ and NC. In practice and qualifying, the leader's best lap and every other car's gap to it |
| Team logos | On | Each driver's team logo next to the name |
| Highlight my row | On | Your own row a little brighter |
| Animations | On | Rows slide when cars change places, the arrow rides in with its row, the position number and a new best lap time fade in, and flag cards slide in and out of the header. Off: every change shows at once |
| Validation log | Off | Writes what the halo and the tower read from the game as CSV to `swofty\addons\nick.f1-2026-halo\diag` in the F1 25 game folder (two files, up to 64 MB each per launch) and shows a status line under the tower. Turn it on only to send a log |

## Beta status

- Driven in practice, qualifying and races with 2026, 2025 and F2 cars, in replays and in the spectator view. In the 2026 cars, speed, gear, revs, throttle, brake, the battery, Recharge, Deploy, Boost, Overtake, the car ahead and the turn numbers matched the game's own values in the validation logs.
- The tower's animations were driven in practice, qualifying and races, the flag cards with yellow flags, a VSC, a safety car and a red flag.
- **Not confirmed yet:** Active Aero, the DRS states of 2025 and F2 cars, the tower in Time Trial, the tower's animations in replays and the spectator view, the spectator view's flag message fix, and the G-force meter.

## Known issues

- My Team: your own team's logo stays empty in the tower.
- Time Trial: long driver names in the tower look squeezed.
- Full field with more than 22 cars (a My Team grid has 24): the tower can run past the bottom of the screen. Make it smaller in HUD customisation, or use Around me or Leaders.
- With the timing tower on and Track Position switched off in HUD customisation, the game's lap counter stays hidden too. Turn the Timing tower setting off to get it back.
- Depending on the screen resolution, the scaling might be off.

## Good to know

- Animations: when several cars change places within a moment, or your own place changes in Around me, those rows switch at once instead of sliding, so every row always shows its own car. A flag card that replaces another (a yellow flag becoming a VSC) also switches at once.
- Turn numbers follow the official F1 numbering on the 24 standard circuits. On reverse layouts and tracks without an official list, the halo finds the corners itself from the cars' line once a lap is covered and numbers them from the start line: those numbers are its own, not official.
- When a value cannot be read, its part stays empty. Project Halo never shows a made-up value.
- Split screen: the halo hides, because two cars are driven by players.
- Spectating offline needs a spectator addon. The spectator view was tested with Spectator/Broadcast Mode.

**Something not working?** Turn on **Validation log**, drive a few laps, then attach the newest `halo_*.csv` and `tower_*.csv` from `swofty\addons\nick.f1-2026-halo\diag` in the F1 25 game folder (zipped) and your `loader.log` (newest folder in `%LOCALAPPDATA%\Swofty\sessions`) to an [issue](https://github.com/nyannoying1337/f1-25-project-halo/issues).

## How it works

- The addon's archives rebuild the game's dials as the halo, with a copy for the HUD editor, and draw the timing tower in place of the Track Position list, in replays and in the spectator view. The game draws every part of them.
- `native/halo_hud.dll` reads your car, the session and its classification from the game's memory and writes the halo's and the tower's own values into the game's HUD data. It changes nothing else in the game.
- The reader checks the game build first and switches itself off on any other build.
- The DLL links only KERNEL32 and the C runtime: no network library.
- `docs/architecture.md` shows how the halo's parts fit together and `docs/timing-tower/leaves.md` lists every value the DLL gives the tower. `native/src/game_state_f1_25.cpp` (the halo) and `native/src/tower_reader.cpp` (the tower) do the reads, and `native/src/tower_anim.cpp` decides which rows and flag cards slide. Source comments that point to other files in `docs/` refer to research notes that are not part of this repository.

## Build

- `.\package.ps1 -NoInstall` runs the tests, builds `native\halo_hud.dll` with [zig](https://ziglang.org) (`winget install zig.zig`) and writes the zip to `dist\`. `native\build.cmd` runs the tests and builds only.
- The archives in `erp\` are built from the game's own UI archives, so they are not in this repository: take them from a release zip, or rebuild them. Set `SWOFTY_TOOLS` to the Swofty repository's `tools` folder first, then build the halo with `python -I tools/native/build_native.py <folder with the stock archives> <halo sprites dir> . <work dir>` and after it the tower with `python -I tools/tower_native/build_tower.py <folder with the stock archives> <tower sprites dir> . <work dir>`. The tower build adds to the halo's, so run it again after every halo build.
- Graphics: `tools/halo.js` and `tools/tower/tower.js` are the reference drawings. `python -I tools/native/export_sprites.py <halo sprites dir>` and `python -I tools/tower_native/export_sprites.py <tower sprites dir>` render their sprites with headless Edge or Chrome. The pages need the [Saira](https://fonts.google.com/specimen/Saira) variable font saved as `tools/saira.ttf` (halo) and `tools/tower/saira.ttf` (tower).
- Icon: `python -I tools/icon/make_icon.py icons/halo.png --chrome <path to msedge.exe or chrome.exe>` draws `icons/halo.png` from `tools/halo.js`, with `tools/tower/saira.ttf`.
- Validation log: `python -I tools/ingame/analyze_diag.py <halo_*.csv> <report.md>` checks a log field by field, with the tower's log from the same launch.

## License

[Project Halo Attribution License 1.0](LICENSE). The Swofty SDK headers in `native/include` keep their MIT license (`native/include/swofty/LICENSE`).

Official turn numbers: F1 live-timing circuit data (via the MultiViewer API), converted by `tools/corners_hpp.py`. Graphics drawn with the Saira typeface (SIL Open Font License 1.1, © 2020 The Saira Project Authors; licence text in `tools/saira-OFL.txt`). No font file is included.

Fan-made. Not affiliated with or endorsed by the FIA, Formula 1, EA or Codemasters. Their names and marks belong to their owners.
