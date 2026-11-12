# Changelog

## 0.2.0 beta

The timing tower now moves like the broadcast: rows slide into their new places when cars change positions, and flag cards slide in and out of the header. It also shows lap times in practice and qualifying and the fastest lap in races, follows the Spectator Menu and takes fields of up to 30 cars. The halo looks closer to the broadcast.

### New

- **Tower animations:** when cars change places, their rows slide into their new positions, fast at first and then settling, like the broadcast. The position arrow rides in with its row, and the position number and a new best lap time fade in. Flag cards (yellow flag, VSC, safety car, red flag, chequered flag) slide down out of the header and the rows move down with them; when the flag ends, the card rolls back up and the rows close the gap. The new Animations setting (On) switches them off: then every change shows at once, as before.
- **Lap times in practice and qualifying:** the tower shows the leader's best lap and every other car's gap to it. A new personal best flashes green for 2 seconds, a new session best purple. The header shows the session's clock.
- **Knockout zone:** in Q1 and Q2 (SQ1 and SQ2 in sprint qualifying), a red hatch marks the cars in the knockout zone.
- **Fastest lap in races:** a purple stopwatch beside the car with the fastest lap.
- **Spectator view:** the tower follows the Spectator Menu's Gap (None, Interval, Leader, Fastest Lap) and Detail (None, Position Change, Stops, Tyre, Best, Penalties) options. Fastest Lap shows thousandths in practice and qualifying, tenths in races.
- **Up to 30 cars:** Full field shows every car on bigger grids, such as the 24 cars of a My Team career.

### Changed

- **Halo look:** closer to the broadcast in every copy (2026, 2025 and F2 cars, the HUD editor and the spectator view): the collar fades out towards the top, and the face is see-through with a fine grid. The TURN label shows only with a turn number, and BRAKE stands upright.
- **Timing tower:** the position arrows show for 3 seconds (was 4), and P1's red box steps aside while an arrow shows. The virtual safety car card is taller and easier to read.
- **Icon:** the addon icon shows the whole dial.

### Fixed

- Practice and qualifying: no empty lap counter box or flag box above the tower any more.
- Spectator view: the tower's top five rows look like the rest, and its header shows the FIA logo once.
- Spectator view: the game's own flag message (LAP, CAUTION, SECTOR) no longer draws over the tower's yellow flag card; it hides while the tower shows.
- Qualifying: at the end of a session, cars with a lap time keep their row and time instead of showing Out for a few seconds.

### Known issues

- My Team: your own team's logo stays empty in the tower.
- Time Trial: long driver names in the tower look squeezed.
- Full field with more than 22 cars: the tower can run past the bottom of the screen. Make it smaller in HUD customisation, or use Around me or Leaders.
- With the timing tower on and Track Position switched off in HUD customisation, the game's lap counter stays hidden too. Turn the Timing tower setting off to get it back.
- Depending on the screen resolution, the scaling might be off.

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
