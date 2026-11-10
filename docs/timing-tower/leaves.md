# Timing tower: DLL leaves (contract)

Contract version: 5

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
| `rows` | int32 | 0…22 | rows shown (= number of `rNN_on` true) |
| `trunc` | bool | | the classification has more than 22 entries; full mode shows the first 22 |
| `hdr` | bool | | header shown (setting "Header") |
| `tyres` | bool | | tyre column shown (setting) |
| `arrows` | bool | | position arrows on (setting). When false the DLL also sends every `rNN_up` / `rNN_dn` false |
| `ints` | bool | | gap / interval column shown (setting "Intervals"). When false every `rNN_gap` is `""` and `rNN_gna` false |
| `teamcol` | bool | | team colours on (setting) |
| `hl` | bool | | player-row highlight on (setting). When false every `rNN_me` is false |
| `anim` | bool | always true | fixed in v2: no player option yet |
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
| `ysna` | bool | | `yel` true but a yellow zone has no sector (start unreadable, outside 0…1, past the last sector end, or no sector table): hide the sector line or draw the dim bar | |

Formation lap (SC byte 3) and an unreadable SC system show the normal header (`hs` 0). An unreadable zone list or red
flag byte raises nothing: the header falls back to the next state; nothing is guessed.

For a template that binds bools (D5): `red` comes with `sc` false, so the SC and red blocks never show together. `yel`
can be true with `sc`, `vsc`, `red` or `chq`: give the yellow block the lowest place (show it only while those four are
false) unless the design shows a yellow line under them. `hs` = 5 exactly when `yel` is true and the other four are
false.

## 3. Rows

`NN` = `00`…`21`: the row's index from the top of the visible window (row `00` is the first row under the header).
Rows show content **in place**: when the order changes, a row gets another car's content; rows never move (the stock
board does the same, `data-and-ui.md` §6). Every row has the same leaves:

| Leaf | Type | Values | Meaning |
|---|---|---|---|
| `rNN_on` | bool | | row shown |
| `rNN_vid` | int32 | −1 none, 0…23 | the vehicle id the row shows |
| `rNN_cVV` | bool | `VV` = `00`…`23` | row `NN` shows the car with vehicle id `VV`. Exactly one is true on a shown row, none on a hidden row. Use it to show per-car game leaves (section 4) |
| `rNN_pos` | text | `1`…`24` | classification position (the game's results, the halo's source) |
| `rNN_p1` | bool | | position 1: the red position box |
| `rNN_up` / `rNN_dn` | bool | at most one true | position-change arrow; it replaces the number while true (green ▲ / red ▼) |
| `rNN_gap` | text | see section 5 | gap / interval column |
| `rNN_gna` | bool | | gap unavailable: dim bar |
| `rNN_tyre` | text | `S` `M` `H` `I` `W` or `""` | tyre letter |
| `rNN_tS` `rNN_tM` `rNN_tH` `rNN_tI` `rNN_tW` | bool | at most one true | the same letter as one bool per compound (for one text node per colour) |
| `rNN_tna` | bool | | tyre unavailable: dim bar in the tyre slot |
| `rNN_pit` | bool | | white `P` box: the car is in the pit lane or garage (pit state 2…15, the game's own `lng_pit` rule) |
| `rNN_pen` | bool | | red `!` box: an unserved drive-through or stop-go, or a time-penalty total above 0 |
| `rNN_out` | bool | | retired / DNF / DSQ / NC: the row at 50 %, tyre hidden |
| `rNN_me` | bool | | the player's row (only while `hl` is on) |
| `rNN_badge` | text | `#overrides.osd.timing_tower.team_badges_hud.<key>` or `""` | the row's car's team logo: exactly the string the game's own standings pill writes into its `team_badge_texture` leaf for that car (`field-traces.md` §10). Bind it like the stock pill's image: `textureOverride=:stri@…rNN_badge`. `""` when the row is hidden or the badge is unknown (the pill's own initial value: the game writes nothing then). Written whatever `teamcol` says |
| `rNN_bdg` | bool | | `rNN_badge` holds a badge. False for My Team and custom badges (the game builds those in protected code), and while a car's badge is not read yet (up to 0.4 s after a new car set) or could not be read |

Window rule (`mode`): full: every classified car, in order, up to 22 rows. Compact: `N` rows with
`start = clamp(pos − floor(N/2), 0, count − N)` (0-based `pos` of the player; equals the game's own 5-pill rule for
N = 5: P12 → P10–P14, P1 → P1–P5, last → last five). Top N: `start = 0`, `min(N, count)` rows. Without a player car
(spectating, replays without one) compact falls back to top N. Rows below `rows` are off.

## 4. Per-car leaves

| Leaf | Type | Values | Meaning |
|---|---|---|---|
| `cVV_row` | int32 | −1 hidden, 0…21 | the row the car with vehicle id `VV` is shown on (the inverse of `rNN_vid`) |

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
| Practice, qualifying, sprint shootout | `""` + `rNN_gna` on every row, P1 included, except `Out` / `DSQ` / `NC` | no verified best-lap source yet (VehicleLapTimes layout is KB-only); the race gap system is not shown in timed sessions | unavailable |
| Gap column off (`ints` false) or row hidden | `""`, `rNN_gna` false | | |

## 6. Template type tags

| Leaf type | DLL call | Template property type | Proven in game |
|---|---|---|---|
| bool | `swofty::hud::set(path, bool)` | `bool` | yes (every halo visibility leaf) |
| text | `swofty::hud::set(path, text)` | `stri` | yes (halo `kmh`, `mph`, `tnum`) |
| int32 | `swofty::hud::set(path, int32_t)` | `si32` (the builder's tag for int32, as `eLayer.layer`) | **no**: no int32 leaf has been bound in game yet. Prefer the bool form where both exist; the first int32 binding needs its own in-game check |

The DLL's tower leaf list is written by the host tests (`sh native/tests/run_tests.sh <out>`) to
`<out>/tower_leaves.txt`: 1047 lines, `view_model_data.hud_tt_… <tag>` with the tag from the table above (`bool`,
`stri`, `si32`). It is **not** added to the halo's `<out>/leaves.txt`: `tools/native/check_leaves.py` checks only
`hud_halo_` leaves and stays the halo's check. For the tower, `tools/tower_re/check_tower_leaves.py` compares the
template's bindings with `tower_leaves.txt`: every bound `hud_tt_` leaf must exist, and a text binding must be a
`stri` leaf, a visibility binding a `bool` leaf (`python -I tools/tower_re/check_tower_leaves.py <out>/tower_leaves.txt
<info.json>`). An image's `textureOverride` binding of `rNN_badge` goes in the info's `bindings` list as
`["#view_model_data.hud_tt_rNN_badge", "stri"]`, so the check types it too.

## 7. Timing and animation the DLL decides

| What | Rule | Mark |
|---|---|---|
| Arrow | shown for 4 s after the car's classification position changes (better: `up`, worse: `dn`; a newer change restarts it). Tracked by vehicle id within one car set: a new session, a restart or a car joining or leaving the table clears every arrow. Never derived from road order | duration is a display choice (F1 TV: "for a while", `research.md` §6, §9) |
| Auto gap mode | Interval → Leader → Interval … every `Auto period` s (5–60, default 10) | design (Decision 3) |
| Tyre letter | read at 2 Hz. Shown only when the visual byte agrees with the compound enum (16 S, 17 M, 18 H, 7 I, 8 W). While the game's cache is stale the last shown letter is kept for at most 1 s, then the dim bar | `field-traces.md` §1 |
| Penalties | read at 4 Hz | `field-traces.md` §3 |
| Gaps, classification, pit state | read at 10 Hz. A torn classification read (two cars on one position) keeps the last valid one for 0.3 s, then `on` goes false | |
| SC / VSC | read at 10 Hz | |
| Flags | the zone list and the red flag byte at 4 Hz; a new red flag or yellow shows within 0.25 s plus a frame. The yellow is kept over one non-yellow read (0.25 s). A flags read older than 1 s raises nothing | `field-traces.md` §7.6 |
| Game mode (Time Trial) | read at 4 Hz, kept over a new car set and read again in its first frame; a read older than 1 s is no Time Trial | |
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
| `validation_log` | Validation log (halo option) | toggle, on | `dbg` |

Settings are read 4 times a second; a change shows within about 0.3 s.

## Changes

| Version | Date | Change |
|---|---|---|
| 1 | 2026-11-09 | first contract |
| 2 | 2026-11-09 | `sessna` removed (never written: the tower is off without a session type). `bg` fixed at 100 and `anim` fixed at true (no player options; HUD editor opacity applies). `dbgtxt` format documented. `tower_leaves.txt` is separate from the halo's `leaves.txt`; new tower check `tools/tower_re/check_tower_leaves.py`. Section 8 (player settings) added. Timed sessions: P1's gap cell is unavailable too. No type changed |
| 3 | 2026-11-09 | Flags (`field-traces.md` §7.8): `hs` adds 3 red flag and 5 yellow flag, priority 4 > 3 > 1 > 2 > 5; new `red` (bool), `yel` (bool), `ysec` (text), `ysna` (bool). `sc` and `vsc` are now false while `red` is true (the SC byte reads 1 under a red flag in game). Yellow and red headers removed from "Never sent". `dbgtxt` gains `yelN redN`. 1001 leaves. No existing leaf renamed or retyped |
| 3.1 | 2026-11-09 | `red` also comes from every marshal zone at 4: in game the red flag byte stayed 0 through a red flag while every zone read 4 (`field-traces.md` §7). `dbgtxt` shows `redz` then. No leaf added, renamed or retyped |
| 4 | 2026-11-09 | Team badges (`field-traces.md` §10): new row leaves `rNN_badge` (text: the stock pill's own `team_badge_texture` string, `#overrides.osd.timing_tower.team_badges_hud.<key>`, up to 83 bytes) and `rNN_bdg` (bool), written whatever `teamcol` says. In each row they follow `rNN_me` and come before `rNN_c00`. `dbgtxt` gains `bdgN` (classified cars with a badge). 1045 leaves. No existing leaf renamed or retyped |
| 5 | 2026-11-10 | Time Trial: new globals `trial` and `show` (bool), right after `on` (every later global moves two places; no name or type changes). `on` is now false in Time Trial even when the session type still reads the last race's. `dbgtxt` reads `time trial` then. The tower log gains `gmode` (the mode label, `?N` a failed step) and `trial`. 1047 leaves |
