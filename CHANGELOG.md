# Changelog

## 0.1.2 beta

A broadcast-style timing tower joins the halo, and the halo now also works in F1 25's 2025 and F2 cars and in the spectator view.

### New

- **Timing tower:** in place of the Track Position list, from the game's own classification. Positions, team logos and colours, driver codes, intervals or gaps to the leader, tyres, PIT, Out, DSQ and NC, and a green or red arrow when a car gains or loses a place. Its header shows the lap or the session, and the safety car, virtual safety car, yellow flag, red flag and chequered flag. Practice, qualifying, races, Time Trial, replays and the spectator view. Move, resize or hide it in HUD customisation.
- **Race Control banner:** the game's own race messages, in the style of the broadcast's Race Control banner.
- **2025 and F2 cars:** the halo replaces their dials too. 2025 cars show DRS, the ERS deploy mode, the battery and Recharge and Deploy. F2 cars show DRS, without the energy parts. The setting Halo in 2025 and F2 cars gives them their own dials back.
- **Spectator view:** the halo shows the car you watch, and the tower replaces the spectator board with that car highlighted.
- **G-force meter:** optional, off by default. The 2026 broadcast's G-force meter in the middle of the halo.

### Fixed

- Four turn arrows pointed the wrong way: Sakhir T5, Silverstone T10 and Mexico City T15 now point left, Baku T9 right.
- The turn number moved on to the next turn about 35 m early at some circuits. After a lap the halo now lines its turn list up with the track.
- The spectator HUD's dial no longer shows every part of the halo at once.

### Known issues

- Spectator view: the tower does not follow the Spectator Menu's Gap (None, Leader, Fastest Lap) and Detail (Position Change, Stops, Tyre, Penalties) options yet. It keeps its own Gap mode.
- Spectator view: the tower's top five rows look a little different from the rest, and its header shows the FIA logo twice.
- Depending on the screen resolution, the scaling might be off.
- Practice and qualifying: the tower shows no lap times yet.

## 0.1.1 beta

The addon's Swofty manifest now says that it supports the Steam version of F1 25 only and needs Swofty Launcher 1.8.36 or newer. Nothing changes in the game. Everything from 0.1.0 is in this release.

## 0.1.0 beta

First public release.

- **The 2026 halo:** the onboard halo graphic from the 2026 F1 world feed, in place of the 2026 dial: speed in km/h and mph, gear and revs, throttle and brake, the battery, Recharge and Deploy, Boost, Overtake and Active Aero, your position and the car ahead, and the next turn.
- **Drawn by the game:** the game's own HUD draws it, so you move and resize it in HUD customisation like any other element, and it hides when the game hides its HUD.
- **No telemetry:** the halo reads the running game itself and changes nothing in it. No UDP telemetry, no companion app.
- **Settings:** driver names and turn numbers can be switched off. A validation log, off by default, records what the halo reads.
