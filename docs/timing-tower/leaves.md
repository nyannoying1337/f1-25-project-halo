# Timing tower: DLL leaves (contract)

Contract version: 13

Any change bumps the version above and gets a line in "Changes" at the end.

Source of every value: `native/src/tower_*.{hpp,cpp}` (provider reads, model, publisher). Evidence per field:
`field-traces.md` and `data-and-ui.md` §3. Levels: **L1** inferred, **L2** writer and reader found in code, **L3** seen
in game.

## 1. Rules for every leaf

| Rule | Detail |
|---|---|
| Prefix | `view_model_data.hud_tt_` (template form `#view_model_data.hud_tt_…`). No `[`, `]` or spaces |
| Types | exactly three: **bool**, **text** (UTF-8, ≤ 31 bytes, except `dbgtxt` ≤ 63 and `rNN_badge`: ASCII, ≤ 83), **int32**. Section 6 lists the template tag per type. A binding whose type differs from the leaf's type **crashes the game** |
| When written | only on change, plus a slow rewrite of every leaf (round robin, every leaf within about 2 s) because the game can rebuild its view model |
| Per-frame budget | the core queue holds 64 writes per frame for every addon. The halo and the tower share 56: the tower takes what the halo left this frame |
| Row updates | a row's changed leaves are written in the same frame (a row is never half old, half new) |
| Unavailable | a value the game does not give this frame is **never guessed**. Its text leaf is `""` and its `…na` bool is true: draw the dim bar (design state g). A value that is legitimately empty (no tyre letter for a retired car) has `…na` false |
| Never sent | knockout hatch, investigation `!` (no game source; Decision 6). No leaf exists for them |
| Tower off | `on` false: the template hides the standings tower. Row leaves are then all off / empty. In Time Trial (`trial`, v5) the template shows its Time Trial board instead |

## 2. Global leaves

| Leaf | Type | Values | Meaning |
|---|---|---|---|
| `on` | bool | | tower shown: setting on, provider valid, classification valid (held ≤ 0.3 s over a torn read), not Time Trial (`trial` false) |
| `trial` | bool | | Time Trial (v5): setting on and the game mode label, read within 1 s, is `time_trial`. `on` is false then (whatever the session type reads: 0 in Time Trial, the last race's after one). The template shows its Time Trial board: the header and up to five rows from the game's own board (`#view_model_data.hud.content.lap_times.pill_0` … `pill_4`), no DLL row leaf | game mode object `[GMC+0x88]`, label `char *` at `+0x278` (L3: loader.log 2026-11-10 03:04, `time_trial` for an F2 Time Trial, `none` in the menus, `grand_prix_23` for a Grand Prix) |
| `show` | bool | | `on` or `trial`: the tower's host shows; the stock board and the game's lap counter hide. `on`, `trial` and `show` are the first three leaves of the table, so they change in the same frame |
| `dbg` | bool | | debug: the "Validation log" option is on. The template may show debug texts (e.g. `#session.dropzone`) while true |
| `dbgtxt` | text | e.g. `cls22 gap+ pit+ sc0 pen++ tyre+ lap+ yel0 red0 bdg22` | debug view only, `""` while `dbg` is false. `clsN` classified cars (`h` held, `!` holes); per system `+` read, `?` found but unreadable, `-` not found; `scN` the SC byte (−1 unreadable); `pen` log then drive-through / stop-go vectors; `yelN` yellow zones in the last flags read (`-` no zone system, `?` list unreadable, 9 = 9 or more); `redN` the red flag byte (`-` no system, `?` unreadable; `z` when only the zones raise the red flag); `bdgN` classified cars whose team badge is known |
| `mode` | int32 | 0 full, 1 compact, 2 top N | display mode (setting) |
| `full` / `compact` / `top` | bool | exactly one true | same as `mode`, as bools |
| `rows` | int32 | 0…30 | rows shown (= number of `rNN_on` true) |
| `trunc` | bool | | the classification has more than 30 entries; full mode shows the first 30 (22 before v9) |
| `hdr` | bool | | header shown (setting "Header") |
| `tyres` | bool | | tyre column shown (setting) |
| `arrows` | bool | | position arrows on (setting). When false the DLL also sends every `rNN_up` / `rNN_dn` false |
| `ints` | bool | | gap / interval column shown (setting "Intervals"). When false every `rNN_gap` is `""` and `rNN_gna` false |
| `teamcol` | bool | | team colours on (setting) |
| `hl` | bool | | player-row highlight on (setting). When false every `rNN_me` is false |
| `anim` | bool | | the Animations option (`tower_animations`, v11); always true before v11. Nothing binds it: the rows' motion runs from the row anim leaves (section 3b), which the DLL never writes while the option is off |
| `bg` | int32 | always 100 | fixed in v2: no player option. The HUD editor's own opacity slider applies to the whole element (the tower replaces Track Position in place, `data-and-ui.md` §2) |
| `lead` | bool | | gap column shows gaps to the leader (false: intervals). Follows the setting; in Auto it flips every period |

### Session and header

| Leaf | Type | Values | Meaning | Source, level |
|---|---|---|---|---|
| `race` | bool | | race header layout (`LAP x / y`): session types 15–17 | `g_Sess_TyreRulesSessionType` (L2) |
| `timed` | bool | | timed layout (`Q2 1:46`): session types 1–14 | same |
| `sess` | text | `P1` `P2` `P3` `P` `Q1` `Q2` `Q3` `Q` `OSQ` `SQ1` `SQ2` `SQ3` `SQ` `OSQ` `R` `R2` `R3` | session label. The type numbers are L2; the labels are ours (types 4/8/13: short sessions, 9/14: one-shot). The tower is off when the session type is unreadable, so there is no "unavailable" form | |
| `lap` | text | `1`…`999`, `""` outside races | the **leader's** current lap (broadcast convention): the leader's game lap counter + 1 (the counter is 0 on lap 1); the counter itself once the leader has finished | progress lap counter (L2; base L3 for the player car) |
| `lapna` | bool | | races only: the leader or its lap counter unreadable: dim bar. False outside races |
| — | — | — | total laps (`/ 71`): **not a DLL leaf**. Bind the game's `#session.number_of_laps` (ui32, as the stock `hud_lap_counter`) | L2 binding |
| — | — | — | session clock (`1:46`): **not a DLL leaf**. Bind the game's `#session.time_remaining_str` (type: check against a stock binding) | L2 binding |
| `hs` | int32 | 0 none, 1 safety car, 2 virtual safety car, 3 red flag, 4 chequered, 5 yellow flag | header status block, one at a time. Priority 4 > 3 > 1 > 2 > 5 > 0 (chequered on top as in v2, then red > SC > VSC > yellow). SC, VSC and chequered: races only; red and yellow: every tower session (races and timed sessions) | see bools |
| `sc` | bool | | full safety car: SC byte = 1 **and no red flag** (the game's SC byte also reads 1 during a red flag: in-game log 2026-11-09 16:39) | SafetyCarLogicSystem `+0x108`: location L2; value 1 seen in game with the SC block (L3, 16:39 log) |
| `vsc` | bool | | virtual safety car: SC byte = 2 and no red flag | same (value 2: L1) |
| `chq` | bool | | chequered: the leader's result status is 3 (finished) | results `P+0x18` (L2) |
| `red` | bool | | red flag: the red flag system's byte is 1 (deployed) or 2 (suspended), or every marshal zone reads 4 (held over one other read, dropped at once on an unreadable list). Set in every tower session, also under the chequered flag (`hs` then stays 4) | `RedFlagSystem` (registry key image + 0x60fde00) byte `+0x40`: L2, stayed 0 in game; every zone at 4: L3 (in-game log 2026-11-09 17:44), `field-traces.md` §7 |
| `yel` | bool | | yellow flag: a marshal zone's flag is 3. Kept over one non-yellow read (the game's writer sets 0 then 3 on each zone update, §7.2); an unreadable zone list clears it at once. Stays true under SC / VSC / red (the template may show both); `hs` gives the block on top | `MarshalZoneMonitor` (image + 0x60fdde0) zones, flag i32 `Z+0x14`: L2 |
| `ysec` | text | `1`…`8`, several in track order: `2`, `1 3`; `""` | the yellow zones' sectors, for the line under YELLOW FLAG (the game's `lng_sector` + this text, as the stock box). `""` when `yel` is false or a yellow zone has no sector (then `ysna` is true). Sector of a zone: the game's own rule, the first sector whose end ≥ track length × zone start (§7.3); the sector table is read once per session | zone start f32 `[[Z]+0x10]`, sector table at image + 0x6ce6660 (L2) |
| `laps` | bool | | the gap column holds each car's lap time: spectating with the game's menu on Gap Fastest Lap (`docs/spectator-ui.md` 10.4). P1's time then shows at the number size, not the label size of `Interval` / `Leader`. Written after `ysna`. Since 6.1 also true in a timed session (best laps, section 5) |
| `ysna` | bool | | `yel` true but a yellow zone has no sector (start unreadable, outside 0…1, past the last sector end, or no sector table): hide the sector line or draw the dim bar | |
| `clock` | text | `""`, or the game's own clock text | the header clock's node (v7). The DLL writes `""` while the header is not timed (`timed` false, also while the tower is off), so the node exists, and never writes it while `timed` is true: then the HUD template's copy of the game's own session clock formatter writes the clock text into it (`database_output`, absolute, as the stock pit lane timer writes `#session.current_car.pit_lane_timer_str`) and the header's clock text reads it. Never written by a refresh while timed. Written after `laps` |
| `flap` | bool | | Since v10: spectating with the game's menu on Gap Fastest Lap (director `+0xe4` = 3), every session: every row's gap text is a lap time (section 5). The template sets every lap time of the timed gap column at its lap time size then (at the number size the three-decimal times do not fit the box); races keep their one-decimal times under `laps`. Written after `clock`, the last global |

Formation lap (SC byte 3) and an unreadable SC system show the normal header (`hs` 0). An unreadable zone list or red
flag byte raises nothing: the header falls back to the next state; nothing is guessed.

For a template that binds bools: `red` comes with `sc` false, so the SC and red blocks never show together. `yel`
can be true with `sc`, `vsc`, `red` or `chq`: give the yellow block the lowest place (show it only while those four are
false) unless the design shows a yellow line under them. `hs` = 5 exactly when `yel` is true and the other four are
false.

## 3. Rows

`NN` = `00`…`29` (v9; `00`…`21` before): the row's index from the top of the visible window (row `00` is the first row under the header).
Rows show content **in place**: when the order changes, a row gets another car's content; rows never move (the stock
board does the same, `data-and-ui.md` §6). Since v11 the content can slide in from the car's old row and come to rest
in its own (section 3b): the leaves below always hold the row's own car. Every row has the same leaves:

| Leaf | Type | Values | Meaning |
|---|---|---|---|
| `rNN_on` | bool | | row shown |
| `rNN_vid` | int32 | −1 none, 0…29 | the vehicle id the row shows |
| `rNN_cVV` | bool | `VV` = `00`…`29` (v9; `00`…`23` before) | row `NN` shows the car with vehicle id `VV`. Exactly one is true on a shown row, none on a hidden row. Use it to show per-car game leaves (section 4) |
| `rNN_pos` | text | `1`…`30` | classification position (the game's results, the halo's source) |
| `rNN_p1` | bool | | position 1: the red position box |
| `rNN_up` / `rNN_dn` | bool | at most one true | position-change arrow; it replaces the number while true (green ▲ / red ▼) |
| `rNN_gap` | text | see section 5 | gap / interval column |
| `rNN_gna` | bool | | gap unavailable: dim bar |
| `rNN_tyre` | text | `S` `M` `H` `I` `W` or `""` | tyre letter |
| `rNN_tS` `rNN_tM` `rNN_tH` `rNN_tI` `rNN_tW` | bool | at most one true | the same letter as one bool per compound (for one text node per colour) |
| `rNN_tna` | bool | | tyre unavailable: dim bar in the tyre slot |
| `rNN_pit` | bool | | white `P` box: the car is in the pit lane or garage (pit state 2…15, the game's own `lng_pit` rule) |
| `rNN_pen` | bool | | red `!` box: an unserved drive-through or stop-go, or a time-penalty total above 0 |
| `rNN_out` | bool | | retired / DNF / DSQ / NC: the row at 50 %, tyre hidden. Since v8, in timed sessions only a car without a best lap (an in-game test: every car still on track went to status 7 when Q1 ended; a car with a lap keeps its row and time) |
| `rNN_me` | bool | | the player's row (only while `hl` is on) |
| `rNN_badge` | text | `#overrides.osd.timing_tower.team_badges_hud.<key>` or `""` | the row's car's team logo: exactly the string the game's own standings pill writes into its `team_badge_texture` leaf for that car (`field-traces.md` §10). Bind it like the stock pill's image: `textureOverride=:stri@…rNN_badge`. `""` when the row is hidden or the badge is unknown (the pill's own initial value: the game writes nothing then). Written whatever `teamcol` says. Since v8 (same leaf): for a custom-badge team (record `+0x58d`) the game's render-badge path instead, `eaid://ui_package/art/textures/render_badge_<source> <id>` or `…render_badge_default.tga`, built as the game builds it (`field-traces.md` §10.6) |
| `rNN_bdg` | bool | | `rNN_badge` holds a badge. False for My Team (the game takes its badge word from code not followed; earlier builds also for custom badges, which are now built, `field-traces.md` §10.6), and while a car's badge is not read yet (up to 0.4 s after a new car set) or could not be read |
| `rNN_det` | text | `5s`, `10s`, `DT`, `SG`; `1`…`29`; `-`; or `""` | the spectator's Detail cell (in the tyre cell, shown while `tyres`), from the game's spectator menu (`docs/spectator-ui.md` 10.4): Detail Penalties the car's penalty; since v10 Detail Position Change the places gained or lost since the grid (`3`, with `rNN_dup` or `rNN_ddn`) or `-` for none, and Detail Stops the game's own pit stop count or `-` for none (the game's board writes its dash for 0); `""` otherwise. The dim bar (`rNN_tna`) when the value is not read: Position Change outside races, without a grid slot, or when two classified cars share one; Stops without the count. Written after `rNN_bdg` |
| `rNN_ko` | bool | | the knockout zone (v7): the session is Q1, Q2, SQ1 or SQ2 (session types 5, 6, 10, 11) and the row's car is classified below the last position that goes through (Q1 / SQ1: 10 + (n − 10) / 2 of n classified cars, 16 of 22; Q2 / SQ2: 10), and it is not out. The template hatches the position strip. The game's own rule (`field-traces.md` §5.1: a 0-based position index above the session's cut; the knockout segments {5, 6, 10, 11} of `Sess_PQRuleset_FinaliseResults`); the cut is not readable through plain pointers, so its value is **inferred** from the code with the qualifying rules' inputs (seen: a 22-car Q1 left 16 cars in Q2). Written after `rNN_det`. Since v8 the field size is the most cars classified since the session type changed (or since the tower came back after more than 5 s off): the next segment's smaller field read while the type still says the last one moves no cut |
| `rNN_pb` | bool | | the lap time flash, green (v8): Practice and Qualifying, the HUD tower's best laps or any spectator Gap mode with a column (Interval, Leader, Fastest Lap; not None); the row's car set a new personal best that is not below every other car's best within the last 2 s; `rNN_gap` holds that lap time (`1:27.470`) meanwhile. The template shows a green copy of the timed gap text and hides the white one. Never with `rNN_ob`. Written after `rNN_ko` |
| `rNN_ob` | bool | | the lap time flash, purple (v8): as `rNN_pb`, the new time below every other classified car's best (a tie is green). Written after `rNN_pb` |
| `rNN_dup` / `rNN_ddn` | bool | at most one true | v10: Detail Position Change, the car gained (`dup`) or lost (`ddn`) the `rNN_det` places since the grid: the game's own rule (`[P+0x90]^[P+0x98]` + 1 minus the position, `0x141778b8f`; L2; that the field is the grid slot is L1, from the UDP naming). The template shows a green ▲ and green count, or a red ▼ and red count; neither: the white text. Written after `rNN_fl`, before `rNN_c00` |
| `rNN_fl` | bool | | the race's fastest lap (v8): races only; the row's car is the game's own fastest car (VehicleLapTimes `+0xb8`, `field-traces.md` §11), when classified; shown for a retired car too; no car while the game names none. An earlier build took the lowest results-entry lap time, which a race log showed to be the last lap in races. The source is **inferred** until a race log checks it (the log's `lfc`, `lbest` and `fl` columns check it). The template shows a purple side box with a stopwatch after the `!` and `P` boxes. Written after `rNN_ob`, before `rNN_c00` |

Window rule (`mode`): full: every classified car, in order, up to 30 rows (22 before v9). Compact: `N` rows with
`start = clamp(pos − floor(N/2), 0, count − N)` (0-based `pos` of the player; equals the game's own 5-pill rule for
N = 5: P12 → P10–P14, P1 → P1–P5, last → last five). Top N: `start = 0`, `min(N, count)` rows. Without a player car
(spectating, replays without one) compact falls back to top N. Rows below `rows` are off.

### 3b. Row motion (v12; v11)

The DLL's `tower::Anim` (`native/src/tower_anim.{hpp,cpp}`) decides
per frame, from the published rows, which rows move; each row then holds a **packet**: one bit per code leaf below.
A code **starts** when its leaf goes false → true: the template's decision node on that leaf (registered) fires its
event `1` and plays the motion. The leaf goes back to false 0.1 s (and at least 2 frames) later; false starts nothing
(no event `0`). A new packet's codes are written after the row's data in the same publish call, each only from a
false written at least 2 frames before (a code still true waits for its false, then goes true again), so every start
is a change and a true is never written twice. `rNN_xrs` never shares a packet with another code. A row that slid gets
a rest packet (`xrs` alone) 0.85 s later, once its play is over; 0.3 s after a fade; at once when the row snaps. All
bool; 11 per row, after every older leaf (ids `kAnimBase` = 1806 onwards, row by row).

| Leaf | Type | At rest | Meaning (going true) |
|---|---|---|---|
| `rNN_xu1`, `rNN_xu2`, `rNN_xu3` | bool | false | the row's car gained 1, 2 or 3 places: its content starts that many rows lower and slides up |
| `rNN_xd1`, `rNN_xd2`, `rNN_xd3` | bool | false | lost 1, 2 or 3 places: starts higher, slides down |
| `rNN_xeu`, `rNN_xed` | bool | false | the ▲ (with an `xu` code) or ▼ (with an `xd` code) eases in from 0.43 row below or above its place; only when the arrow shows and the row it comes from is not the window's last (▲) or first (▼) |
| `rNN_xnf` | bool | false | the position number fades in: sent when the arrow ends within the next two frames (`rNN_up` / `rNN_dn` going false on the same car) |
| `rNN_xff` | bool | false | the lap time flash texts fade in: the car's flash starts (`rNN_pb` / `rNN_ob`), by vehicle id |
| `rNN_xrs` | bool | false | every motion of the row to rest (the clips at fraction 1, the fades off) |

Every name here shares no djb2 hash with any other view-model name the templates or the DLL use (the build checks it:
`tower_native.check_vm_hashes`). v11's `rNN_u2` and `rNN_st` shared v10's `rNN_tS` hash ("u2" = "st" = "tS" as a
two-character suffix), so the three were one node in game.

The Animations option off: no anim leaf is written at all (a row still moving when it goes off gets its rest packet
first), and every older leaf is written as in v10. On: every anim leaf is written false when the table is built; after
that an anim leaf is written only to start a code or to end its pulse (no refresh: a false starts nothing). A packet
waits with its row when the frame's budget runs out; a newer packet before the last one went out replaces it (fades
still waiting are kept).

### 3c. Header card motion (v13)

The DLL's `tower::Anim` also decides per frame whether the header's
flag card moves: from no card to a card (in), from a card to no card (out), else at once. The card shown is the one the
template shows (chequered > red > SC > VSC > yellow, behind `on` and `hdr`). The header holds one **packet** at a time,
one code: `kin1`-`kin3` or `kout1`-`kout3` (1: the chequered card, one row high; 2: red, SC or yellow, two rows; 3:
VSC, 2.5 rows) or `krs`. The pulse rules are the rows' (section 3b): a code starts when its leaf goes false → true and
goes back to false 0.1 s (and at least 2 frames) later; false starts nothing. While the motion leaves are live, the
header's state leaves (`hs` … `ysna`) and the motion leaves below go out as one unit in one frame (whole, or all the
next frame): the card's new state, the copy and the code together. The rest packet (`krs` alone) follows 0.85 s after a
motion, or at once when a snap cuts it. An exit shows the old card's copy (`gh_<card>`) for 0.85 s; the copy's yellow
line reads `gh_ysec` / `gh_ysna`, the sectors the template showed as the card went (the yellow's own `ysec` may clear
in that very frame). No motion: on a snap frame (the rows' reasons: the tower or the option off, the first frame, a
session or car-set change, a replay jump, the 2 s after either, a followed-car change), with the Tower header setting
off, within 0.85 s of the last motion, or one card for another. All after every older leaf (ids `kHeadBase` = 2136
onwards).

| Leaf | Type | At rest | Meaning (going true) |
|---|---|---|---|
| `kin1`, `kin2`, `kin3` | bool | false | a card of size 1, 2 or 3 comes in: the cards and rows start that card's height up (the new card under the header band) and ease down to their places |
| `kout1`, `kout2`, `kout3` | bool | false | the card of that size goes: the rows start that height down (where they were), the card's copy above them, and ease up |
| `krs` | bool | false | the header's motion to rest (both clips at fraction 1) |
| `gh_chq`, `gh_red`, `gh_sc`, `gh_vsc`, `gh_yel` | bool | false | the exit's copy of that card shows (with its `kout` code, for 0.85 s; gone at once on a snap) |
| `gh_ysec` | text | `""` | the yellow copy's sectors: the `ysec` last written before the exit's frame |
| `gh_ysna` | bool | false | the yellow copy's dim bar: the `ysna` last written before the exit's frame |

The Animations option off: none of these is written (a motion in flight gets its rest packet first, the copy goes),
and every older leaf is written exactly as in v12. On: written false when the table is built; after that only to
start a code, end its pulse, show or hide a copy, or freeze the copy's line. The names share no djb2 hash with any
other view-model name (`tower_native.check_vm_hashes`).

## 4. Per-car leaves

| Leaf | Type | Values | Meaning |
|---|---|---|---|
| `cVV_row` | int32 | −1 hidden, 0…29 | the row the car with vehicle id `VV` is shown on (the inverse of `rNN_vid`) |

There is **no DLL source** for the driver code or the team colour: the DLL does not read names
(`docs/internal-state/re-findings.md` §4c: bind the game's own per-car leaves, do not rebuild names natively). The
template shows them from the game's per-car leaves, selected per row by `rNN_cVV`, exactly like the halo's rival lane
(`rvNN`, L3). The team badge is the exception: no per-car game leaf holds it, so the DLL reads the team key the way the
game's pill does and writes the pill's string per row (`rNN_badge`, section 3; v4):

| What | Game leaf (by vehicle id) | Level |
|---|---|---|
| Three-letter code | `#session.cars.car<VV>.driver.name_code` | L2 (row builder `0x1424be430`) |
| Team colour | `#session.cars.car<VV>.nub_colour` | L2 binding (spectator row `colourOverride@car.nub_colour`) |
| Team badge | none per car in the game; the DLL's `rNN_badge` (`#overrides.osd.timing_tower.team_badges_hud.<team key>`, the HUD pill's array, not `team_badges_broadcast`) | chain and string L2, runtime L1 (`field-traces.md` §10) |

## 5. Gap column texts (`rNN_gap`)

| Case | Text | Rule | Mark |
|---|---|---|---|
| Race, P1, interval mode | `Interval` | | [2026] |
| Race, P1, leader mode | `Leader` | | design (Decision 3) |
| Race, valid time | `+5.1`; `+1:05.3` from 60 s | T record `+0x70` (interval) or `+0x58` (leader), shown only while its valid flag is set **and** the car's result status is 2 or 3 (`field-traces.md` §6). One decimal, cut (not rounded) | one decimal [2026]; the minutes form and cutting are display choices |
| Race, lapped | `+1 LAP`, `+2 LAPS` | the game cleared the flag, the car is running (status 2) and not in the pits, and the game's lap counters differ by N ≥ 1 (leader mode: to the leader; interval mode: to the car ahead) | **inferred format** (no 2026 frame) |
| Race, pit lane / garage | `PIT` | flag cleared and pit state 2–7 or 14–15 (the game's own reason) | the word is the game's (`lng_pit`); its look on F1 TV is not seen |
| Retired / DNF | `Out` | status 4 or 7 | [2026] (`full` row 22) |
| Disqualified | `DSQ` | status 5 | inferred |
| Not classified | `NC` | status 6 | inferred |
| Anything else (flag cleared for no known reason, status 0/1, the race start before the first timing point) | `""` + `rNN_gna` | | unavailable |
| Practice, qualifying, sprint shootout (since 6.1; not spectating) | P1: its best lap `1:27.470`, `58.123`; the others: the gap to it, `+0.293`, `+1:02.345`; `""` + `rNN_gna` without a time, or for a time below a time classified ahead of it; `Out` / `DSQ` / `NC` as in a race | results `f32 [P+0xe8]^[P+0xf0]` s (the Fastest Lap field above), shown unless 0 or the none byte is 0xff; ms as the game's board makes them (`s * 1000.0f` in single precision, cut: `0x14177a59d`); three decimals. `laps` true (P1's time at the number size). Spectating: the director's Gap as before | value: the game's board's (code); that it is the best lap is **inferred** (the mode is named Fastest Lap); the log's `blap` column settles it: a best lap only falls during a session |
| Gap column off (`ints` false) or row hidden | `""`, `rNN_gna` false | | |
| Spectating, the game's menu on Gap Fastest Lap (director `+0xe4` = 3, `docs/spectator-ui.md` 10.4) | `1:32.4`, `58.7`; `""` + `rNN_gna` without one | every row (P1 too) and session: results `f32 [P+0xe8]^[P+0xf0]` s, shown unless 0 or `u8 [P+0x108]^[P+0x110]` = 0xff (the game's own rule for its board in that mode). Races: one decimal, cut (`1:32.4`). Timed sessions: three decimals as the best laps (`1:06.506`, the game's own conversion `game_lap_ms`; one decimal tied real times, an in-game Q1: P1-P3 all 1:06.5), with `flap` | value: the game's board's (code); the decimals are a display choice. Races: each car's best valid lap from its lap table (`field-traces.md` §11), the dim bar without one; earlier builds showed the results-entry time (the last lap) |

## 6. Template type tags

| Leaf type | DLL call | Template property type | Proven in game |
|---|---|---|---|
| bool | `swofty::hud::set(path, bool)` | `bool` | yes (every halo visibility leaf) |
| text | `swofty::hud::set(path, text)` | `stri` | yes (halo `kmh`, `mph`, `tnum`) |
| int32 | `swofty::hud::set(path, int32_t)` | `si32` (the builder's tag for int32, as `eLayer.layer`) | **no**: no int32 leaf has been bound in game yet. Prefer the bool form where both exist; the first int32 binding needs its own in-game check |

The DLL's tower leaf list is written by the host tests (`sh native/tests/run_tests.sh <out>`) to
`<out>/tower_leaves.txt`: 2150 lines (v13; 2136 in v12, 2166 in v11, 1806 in v10), `view_model_data.hud_tt_… <tag>` with the tag from the table above (`bool`,
`stri`, `si32`). It is **not** added to the halo's `<out>/leaves.txt`: `tools/native/check_leaves.py` checks only
`hud_halo_` leaves and stays the halo's check. For the tower, `tools/tower_re/check_tower_leaves.py` compares the
template's bindings with `tower_leaves.txt`: every bound `hud_tt_` leaf must exist, and a text binding must be a
`stri` leaf, a visibility binding a `bool` leaf (`python -I tools/tower_re/check_tower_leaves.py <out>/tower_leaves.txt
<info.json>`). An image's `textureOverride` binding of `rNN_badge` goes in the info's `bindings` list as
`["#view_model_data.hud_tt_rNN_badge", "stri"]`, so the check types it too.

## 7. Timing and animation the DLL decides

| What | Rule | Mark |
|---|---|---|
| Arrow | shown for 3 s (the reference clip; 4 s before) after the car's classification position changes (better: `up`, worse: `dn`; a newer change restarts it). Tracked by vehicle id within one car set: a new session, a restart or a car joining or leaving the table clears every arrow. Never derived from road order | duration is a display choice (F1 TV: "for a while", `research.md` §6, §9) |
| Auto gap mode | Interval → Leader → Interval … every `Auto period` s (5–60, default 10) | design (Decision 3) |
| Tyre letter | read at 2 Hz. Shown only when the visual byte agrees with the compound enum (16 S, 17 M, 18 H, 7 I, 8 W). While the game's cache is stale the last shown letter is kept for at most 1 s, then the dim bar | `field-traces.md` §1 |
| Penalties | read at 4 Hz | `field-traces.md` §3 |
| Gaps, classification, pit state | read at 10 Hz. A torn classification read (two cars on one position) keeps the last valid one for 0.3 s, then `on` goes false | |
| SC / VSC | read at 10 Hz | |
| Flags | the zone list and the red flag byte at 4 Hz; a new red flag or yellow shows within 0.25 s plus a frame. The yellow is kept over one non-yellow read (0.25 s). A flags read older than 1 s raises nothing | `field-traces.md` §7.6 |
| Game mode (Time Trial) | read at 4 Hz, kept over a new car set and read again in its first frame; a read older than 1 s is no Time Trial | |
| Row motion (v11) | per frame from the published rows: a slide when a row's car was on another row of the window 1 to 3 rows away in the last frame; none on the first frame, within 2 s of a session or car-set change or a replay jump (the followed car's lap distance moving more than 100 m in a frame, not across the line), on a followed-car or window change, when more than 4 cars move 2 or more rows, for a car entering the window, moving more than 3 rows or back on a position it left less than 1 s ago. No slide on a row within 0.85 s of its last slide (the car snaps), nor for the other cars of that move (v12). Rest packets 0.85 s / 0.3 s after a motion | design, from the broadcast references (private) |
| Team badges | read once per car per car set with the classification, six cars per 10 Hz run (a 22-car grid within 0.4 s), then kept until the car set changes (new session, restart, a car joining or leaving). A failed read is tried again once a second. A badge never changes while its car stays in the session; it moves with its car from row to row in the same frame as the car | `field-traces.md` §10.4 |

## 8. Player settings (swofty.json)

| Option id | Player label | Type, default | Leaf |
|---|---|---|---|
| `tower_on` | Timing tower | toggle, on | `on`, `trial`, `show` |
| `tower_mode` | Tower layout | choice: `compact` Around me (default), `top` Leaders, `full` Full field | `mode`, `full`, `compact`, `top` |
| `tower_rows` | Tower rows | slider 3–22, step 1, default 5 | `rows` (Around me / Leaders) |
| `tower_header` | Tower header | toggle, on | `hdr` |
| `tower_tyres` | Tyres | toggle, on | `tyres` |
| `tower_arrows` | Position arrows | toggle, on | `arrows` |
| `tower_gaps` | Intervals | toggle, on | `ints` |
| `tower_gap_mode` | Gap mode | choice: `interval` (default), `leader`, `auto` | `lead` |
| `tower_auto_s` | Auto switch every (s) | slider 5–60, step 5, default 10 | `lead` timing |
| `tower_team_colours` | Team logos (label until 2026-11-09: Team colours) | toggle, on | `teamcol` |
| `tower_highlight` | Highlight my row | toggle, on | `hl` |
| `tower_animations` | Animations (v11) | toggle, on | `anim`; off: no row anim leaf (section 3b) is written |
| `validation_log` | Validation log (halo option) | toggle, off | `dbg` |

Settings are read 4 times a second; a change shows within about 0.3 s.

## Changes

| Version | Date | Change |
|---|---|---|
| 1 | 2026-11-09 | first contract |
| 2 | 2026-11-09 | `sessna` removed (never written: the tower is off without a session type). `bg` fixed at 100 and `anim` fixed at true (no player options; HUD editor opacity applies). `dbgtxt` format documented. `tower_leaves.txt` is separate from the halo's `leaves.txt`; new tower check `tools/tower_re/check_tower_leaves.py`. Section 8 (player settings) added. Timed sessions: P1's gap cell is unavailable too. No type changed |
| 3 | 2026-11-09 | Flags (`field-traces.md` §7.8): `hs` adds 3 red flag and 5 yellow flag, priority 4 > 3 > 1 > 2 > 5; new `red` (bool), `yel` (bool), `ysec` (text), `ysna` (bool). `sc` and `vsc` are now false while `red` is true (the SC byte reads 1 under a red flag in game). Yellow and red headers removed from "Never sent". `dbgtxt` gains `yelN redN`. 1001 leaves. No existing leaf renamed or retyped |
| 3.1 | 2026-11-09 | `red` also comes from every marshal zone at 4: in game the red flag byte stayed 0 through a red flag while every zone read 4 (`field-traces.md` §7). `dbgtxt` shows `redz` then. No leaf added, renamed or retyped |
| 4 | 2026-11-09 | Team badges (`field-traces.md` §10): new row leaves `rNN_badge` (text: the stock pill's own `team_badge_texture` string, `#overrides.osd.timing_tower.team_badges_hud.<key>`, up to 83 bytes) and `rNN_bdg` (bool), written whatever `teamcol` says. In each row they follow `rNN_me` and come before `rNN_c00`. `dbgtxt` gains `bdgN` (classified cars with a badge). 1045 leaves. No existing leaf renamed or retyped |
| 6 | 2026-11-10 | The spectator menu (`docs/spectator-ui.md` 10.4): new row leaf `rNN_det` (text) after `rNN_bdg`, before `rNN_c00`. While spectating, the director's Gap and Detail replace the settings: `ints` and `tyres` follow them, `lead` is Gap 2, Gap 3 writes each car's lap time into `rNN_gap` and sets the new global `laps` (bool, after `ysna`), Detail 1 / 2 set `rNN_tna`, Detail 5 writes `rNN_det`. `dbgtxt` gains ` sG<gap>D<detail>` while spectating. 1070 leaves. No existing leaf renamed or retyped |
| 7 | 2026-11-10 | New global `clock` (text, after `laps`): the header clock's node, `""` while not timed, never written while timed (the template's clock formatter owns it then). New row leaf `rNN_ko` (bool, after `rNN_det`, before `rNN_c00`): the knockout zone in Q1, Q2, SQ1, SQ2. The tower log gains a last column `ko` (the last position through, `-` none). 1093 leaves. No existing leaf renamed or retyped |
| 8 | 2026-11-11 | New row leaves `rNN_pb`, `rNN_ob`, `rNN_fl` (bool, after `rNN_ko`, before `rNN_c00`): the lap time flash (green, purple) and the race's fastest lap. `rNN_out` in timed sessions only without a best lap; the knockout field held per session type. The tower log gains two last columns `fx` (the flashes by vehicle id, `3p 7g`) and `fl` (the fastest lap's `vid:ms`), 73 columns. The reader's long results copy also in races. 1159 leaves. No existing leaf renamed or retyped. Addendum (same leaves, same version): while spectating a timed session the director's Interval and Leader write best-lap values into `rNN_gap` (P1 its best lap; Leader the gap to P1's best; Interval the gap to the best lap of the car directly ahead; the dim bar without a time or out of order), and `rNN_pb` / `rNN_ob` flash in Interval, Leader and Fastest Lap (in Fastest Lap the cell keeps its one-decimal lap time). Second addendum (same leaves, same version): `rNN_fl` from the game's fastest car (VehicleLapTimes `+0xb8`); the spectator Fastest Lap in races from the lap tables; `rNN_badge` may carry the game's render-badge path (custom-badge teams); the tower log gains `lbest`, `lfc` and `mtb`, 76 columns |
| 9 | 2026-11-11 | Towers up to 30 cars (a My Team grid has 24): rows `r22`…`r29` (the same leaves as every row), every row's `rNN_cVV` and the car leaves `cVV_row` for vehicle ids `24`…`29`; `rows` up to 30, `trunc` above 30. Order unchanged: the globals (`c00_row`…`c29_row` among them), then the rows. 1745 leaves (65 globals, 30 rows of 56). The settings' row slider (3-22) is unchanged. No existing leaf renamed or retyped |
| 10 | 2026-11-11 | The spectator's Detail cell from the game's own values: new row leaves `rNN_dup`, `rNN_ddn` (bool, after `rNN_fl`, before `rNN_c00`). Detail 1 Position Change: `rNN_det` the places gained or lost since the grid (`3`) with `rNN_dup` / `rNN_ddn`, or `-`; races only (the menu offers it there), the dim bar without a grid slot or when two classified cars share one. Detail 2 Stops: `rNN_det` the game's pit stop count (u32 pit entry `+0x14`, read with the state in one copy), `-` for none, the dim bar unread. Detail 4 Best: the tyre letter (`rNN_tyre`, `rNN_tS`…`rNN_tW`) of the set the car's best lap was on (the game's rule: the first stint whose end lap `+0x74` is at least the best lap's number `[P+0x108]^[P+0x110]`, else the last); the DLL reads the current set's compound only, so the letter shows when the best lap was on the current set and the dim bar otherwise (the stints are read at the tyre job's 2 Hz only while the menu is on Best). Detail 1, 2 and 4 showed the dim bar (1, 2) or the current tyre (4) before. The tower log gains `grid`, `stops` and `bst`, 79 columns. New global `flap` (bool, after `clock`): the menu's Gap Fastest Lap, where timed sessions now show three decimals (`1:06.506`, was `1:06.5`) and the template sets every timed lap time at its lap time size. 1806 leaves (66 globals, 30 rows of 58). No existing leaf renamed or retyped |
| 11 | 2026-11-11 | The rows' motion: 12 new bool leaves per row after every older leaf, `rNN_u1` `u2` `u3` `d1` `d2` `d3` `eu` `ed` `nf` `ff` `rs` `st` (section 3b), written only with the new option `tower_animations` (Animations, default on). `anim` follows the option (always true before). The tower log gains `anim` (the packets so far and the snaps since the last record), 80 columns. 2166 leaves (66 globals, 30 rows of 58, 30 rows of 12). No existing leaf renamed, retyped or moved |
| 12 | 2026-11-11 | The 12 row motion leaves become 11, renamed `rNN_xu1` `xu2` `xu3` `xd1` `xd2` `xd3` `xeu` `xed` `xnf` `xff` `xrs` (section 3b): v11's `rNN_st` and `rNN_u2` shared `rNN_tS`'s djb2 hash, so the three were one node and rows moved by themselves. No trigger: each code starts by going false → true and goes back to false 0.1 s later. No slide within 0.85 s of the row's last, nor for the other cars of that move. The tower log gains `apk` (every row's started codes and row snaps with their time), 81 columns. 2136 leaves (66 globals, 30 rows of 58, 30 rows of 11). No older leaf renamed, retyped or moved |
| 13 | 2026-11-12 | The header's flag cards slide in and out: 14 new leaves after every older leaf (section 3c): the codes `kin1` `kin2` `kin3` `kout1` `kout2` `kout3` `krs` (bool), the exit's copies `gh_chq` `gh_red` `gh_sc` `gh_vsc` `gh_yel` (bool) and the copy's yellow line `gh_ysec` (text), `gh_ysna` (bool). Written only with the Animations option on; then the header's state leaves and these go out as one unit. The tower log gains `hdk` (the header's card, codes, copies and snaps, each with its time and frame), 82 columns. 2150 leaves. No older leaf renamed, retyped or moved |
| 6.1 | 2026-11-10 | Best laps in timed sessions (section 5): `rNN_gap` holds P1's best lap and the others' gap to it while not spectating; `laps` is also true then. No leaf added, renamed or retyped (1070 leaves) |
| 5 | 2026-11-10 | Time Trial: new globals `trial` and `show` (bool), right after `on` (every later global moves two places; no name or type changes). `on` is now false in Time Trial even when the session type still reads the last race's. `dbgtxt` reads `time trial` then. The tower log gains `gmode` (the mode label, `?N` a failed step) and `trial`. 1047 leaves |
