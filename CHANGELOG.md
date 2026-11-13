# Changelog

## 0.2.3 beta

The halo now shows the game's suggested gear. Players who drive with the gear suggestion assist no longer lose the hint when the halo replaces the game's dial.

### New

- **Suggested gear:** with the game's assist Manual with suggested gear on, the gear the game suggests lights up on the halo's gear strip with a small pointer: green when it is higher than your gear, amber when it is lower. In the right gear, or with the assist off, nothing extra shows. Both halo layouts, 2026, 2025 and F2 cars, also with the G-force meter. The new setting Suggested gear (On) switches it off.

### Known issues

- Suggested gear: a mark shows about 0.15 seconds after the game names a gear, and a gear you just left stays dark for 0.3 seconds.
- Suggested gear: the mark shows and hides at once; it has no animation.
- Suggested gear: no mark in the spectator view.

## 0.2.2 beta

The halo now moves: a streak runs along the wings on Boost and Overtake, the gear number ticks on a shift, and the name of the car ahead rolls over when it changes. The halo also gets a second layout that sits on the car's own halo in the default camera. Two more HUD parts join in the broadcast look, the pit lane timer and the lap time card, and every part of Project Halo can now be switched off on its own.

### New

- **Halo animations:** a bright streak runs out along both wings when Boost or Overtake comes on, and repeats once a second while it stays on. The gear number ticks on every shift, and the RPM line turns white near the limiter. When the car ahead changes, its name rolls out and the new one rolls in. The active aero bars turn between their two shapes instead of jumping. The Animations setting switches all of it off.
- **Halo layout: Default camera.** A new, even-sided halo, larger, placed on the car's own halo as the default T-cam shows it, with bigger gear numbers. It is the new default. The setting Halo layout gives the earlier halo back as TV offset (the broadcast's off-centre camera angle, at the bottom of the screen).
- **Pit lane timer:** in place of the game's pit timer, in the broadcast look: position, team logo, surname, team colour line, IN PIT with the pit lane time, and the stop time under it. After the pit exit the time shows with three decimals.
- **Lap time card:** in place of the game's lap time pills: position, team logo, surname and tyre, the running lap time, and S1, S2 and S3. The bar of the current sector grows in white and takes the game's sector colour when the sector is done. The lap time turns green for 3 seconds on a personal best and purple on the session's fastest lap. Best and Previous sit below.
- **Pit speed message:** the whole message is red while you are over the pit limit and green once you are under it, with PIT LIMIT above the limit.
- **A switch for every part:** Halo dial, Timing tower, Race Control banner, Pit lane timer, Lap time card and Pit speed colour each have their own setting. Off gives that part of the game's own HUD back. The Timing tower switches at once; the others apply after a restart. Pit speed colour needs the Race Control banner on.

### Changed

- The pit lane timer and the lap time card take their team logo and tyre from the same source as the tower, and work with the Timing tower switched off.

### Fixed

- View highlights (after a race): the timing tower now shows in the highlights reel, with each clip's order, team logos, tyres and lap. It shows no gaps there, because the game does not keep them for a replayed moment.
- Replays: an instant replay no longer risks showing the game's board behind the tower.

### Known issues

- Halo layout Default camera: fitted to a 2026 car in the default T-cam at 16:9. Other cars, other cameras, ultrawide screens and changed camera settings can sit differently: move or resize the halo in HUD customisation, or use TV offset.
- Halo layout Default camera: a halo you already moved in HUD customisation ends up higher and larger. Place it again once.
- Halo layout Default camera: the game's tutorial message and the open MFD can touch the halo.
- The pit window stays the game's own.
- The running lap time shows three decimals; the game gives the HUD no shorter form.
- STOP TIME and PIT LIMIT are in English in every language.
- My Team: your own team's logo stays empty in the tower.
- Time Trial: long driver names in the tower look squeezed.
- Full field with more than 22 cars: the tower can run past the bottom of the screen. Make it smaller in HUD customisation, or use Around me or Leaders.
- With the timing tower on and Track Position switched off in HUD customisation, the game's lap counter stays hidden too. Turn the Timing tower setting off to get it back.
- Depending on the screen resolution, the scaling might be off.

## 0.2.1 beta

The validation log now stays inside the game folder. Nothing changes in the halo or the timing tower. Everything from 0.2.0 is in this release.

### Changed

- **Validation log:** the two CSV files are now written to `swofty\addons\nick.f1-2026-halo\diag` in the F1 25 game folder, through the Swofty launcher's own storage. They used to go to a folder under `%LOCALAPPDATA%`. The launcher keeps the files between sessions. The option is still off by default.

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
