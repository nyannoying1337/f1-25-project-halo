# Suggested gear on the gear strip (0.2.3)

Tags: [code] read in the stock UI files, the game binary on disk or this project's build checks (static), [game] seen
in game, [design], [sim] the build's own simulation. Seen in game: the marks show on the strip in green and amber
with the game's gear assist on.

## 1. What it does

With the game's suggested gear assist on, the stock dial shows the gear the game suggests whenever it differs from the
current gear. The halo replaces that dial, so it shows the same suggestion on its gear strip:

- the suggested digit in the hint colour at the lit digit's size and weight, with a soft glow, and a small triangle
  beside it on the side away from the RPM line, its tip toward the digit [design];
- green `#4BE37A` when the suggestion is above the current gear, amber `#FFB42E` when below;
- nothing when the suggestion equals the current gear, when the assist is off, when the option **Suggested gear**
  (`suggested_gear`, default on) is off, and while spectating. The lit current digit never changes.

It is the game's own suggestion. Nothing is worked out from speed, revs or track position.

## 2. The game's side [code]

Stock template (`hud_dynamic_templates.ui`, `hud_spectator_2.ui`; every dial's `[F1HD]`):

- Group `desired_gear`: two labels bound to `desired_gear_display` (string), two UIXA, and two DBCD nodes that
  compare `desired_gear` with `current_gear` (higher: show the upper set; lower: the lower set; equal: hide all).
- Its command `registerDesiredGear` (sent by the `[F1HD]`'s `use_dial`) registers and queries the first DBCD. It is
  template wiring only: the values do not depend on it.

Game binary (PE timestamp 1789118616, the build the DLL checks for):

- The dial view model creates `current_gear`, `desired_gear`, `last_gear` (integers), `current_gear_display`,
  `desired_gear_display`, `last_gear_display` (strings; the creator `dial_type`, `drs_pit_state` and `speed_str`
  use), `showing_desired_gear` (bool) in its bind function 0x1414e2d00.
- Its gear update 0x1414e9f30 runs while the dial has a car. Current gear: the gearbox index the DLL reads too
  (0 R, 1 N, 2 = 1st). When the profile's gear assist setting, clamped by the session's restriction, is 2, the
  suggestion is read from the game's own per-player record; a value of 11 or more, or any other assist setting,
  gives the current gear. It then writes `desired_gear` and `desired_gear_display` on every call, the string from
  the table "R", "N", "1" ... "9" ("?" out of range) that `current_gear_display` uses.
- So "no suggestion" and "assist off" both arrive as suggestion = current gear.

## 3. How the halo shows it

| Part | Source |
|---|---|
| Which digit is suggested | the game: `desired_gear_display`, read by the template |
| Green or amber, and "differs from the current gear" | the DLL, from the gear it already reads: leaves `su<k>` (strip place k is above the current gear) and `sd<k>` (below), k = 0 (N) to 8 |
| Option, own car only | the DLL: all 18 leaves false while the option is off, the gear is not read or a car is being watched |

Scene (every live dial; `tools/native/halo_native.py` `_halo`): per strip place a null `<root>_sg<k>`, hidden in the
scene, holding an anim null `zh_sg<k>_anim` at the mark's centre with two quads `<root>_sgu<k>` (sprite `sg_up_<k>`)
and `<root>_sgd<k>` (`sg_dn_<k>`) on layer 25, above the digits and the RPM line. The place nulls hang on the halo's
root like the digits, so the G-force meter's centre keeps them. The HUD editor's copy has none. Sprites:
`tools/halo.js` `drawGearSuggest`, exported by `tools/export_native.js`.

Template (every live dial's `halo_ctl`, race HUD and spectator HUD alike; `_anim_nodes`):

- `v_sg<k>`: static `visible` False.
- `sg_gear`: an MVCD on `desired_gear_display` with one event per value the game writes. "N", "1" ... "8" show
  that place and hide the other eight; "R", "9" and "?" hide all nine. Registered and queried by `halo_ctl`'s
  `trigger` (the `[F1HD]`'s `show`), unregistered by `untrigger`. Its other signals: section 6.
- `v_sgu<k>` / `v_sgd<k>`: `visible` bound to the leaves `su<k>` / `sd<k>`, False while a leaf is absent.
- `x_sg<k>` (UIXA on `zh_sg<k>_anim`), `sg_t` (timer), `sg_q` (a second MVCD on the same value): section 6.

The mark has no animation of its own and does not depend on the Animations option: it shows and hides at once,
except that a place the game has only just named shows its mark a moment later (section 6).

## 4. What this rests on

| Fact | Evidence |
|---|---|
| The stock dial's template nodes stay as they are under the halo, so the dial view model publishes as stock | [code] `check_stock_kept`; [game] the halo binds `revs`, `ers_stored`, `speed_str`, `om_active`, `is_xm_active`, `drs_pit_state` of the same view model |
| An MVCD on a string leaf of this view model fires the event named like the value; its show / hide switch a static-visible group | [game] the DRS pill of the 2025 and F2 halo (`drs_pit_state`) |
| register + query from the `[F1HD]`'s `show` | [game] the class dials, the 2026 dial's animation nodes |
| `desired_gear_display` holds the suggestion as "N", "1" ... "8" | [code] section 2 only |

Fail-safe: no event at all, an absent leaf, no DLL, another game build, the option off: every mark stays hidden and
the halo is the 0.2.2 picture. A value outside the game's table would leave the last place's group as it was (the
table read in section 2 has no such value); the DLL's leaves still light a mark only on a place that is not the
current gear.

The DLL writes changed leaves before leaves that are only due for their 2 s refresh (`leaves.hpp` `flush`), so the
lit digit and the two leaves of a place turn in the same frame.

## 5. Open points

1. Seen in game on the first build: the mark appears with the assist on (the leaf's content and the MVCD's
   one-character events were read statically before).
2. Which of the two orders of section 6 the game has.
3. The launcher's API cannot read a view-model value, so the log cannot show the game's leaf. The loader log has
   one line when the marks are armed or disarmed: `[halo-re] suggested gear: marks armed (option on; ...)`. To tell
   "the game gives no suggestion" from "the mark fails": switch the Halo dial option off; the stock dial then shows
   its own hint from the same values.

## 6. No flash on a gear change

Seen in game on the first build: at every upshift and downshift a green or amber mark flashed for a frame or a few.

The mark needs two things to agree: the place the game names and the DLL's side leaves of that place. With no
suggestion the game names the current gear. Both sides read the same gearbox value, but they do not turn in the same
frame, and either order lights a mark that no one suggested:

| Order | What flashed | The fix |
|---|---|---|
| A: the DLL's leaves turn first | the game still names the gear just left, whose leaf now says "beside the current gear": amber on an upshift, green on a downshift | the DLL holds a place dark after the gear leaves it |
| B: the game's value turns first | the game names the new gear's place while the leaves still describe the gear before: green on an upshift, amber on a downshift | the template shows a newly named place only after a short delay |

Which order the game has is not known. Read statically [code]: the dial view model's update (0x1414ebb30, a virtual of
the view model) calls the gear update on every call while the dial has a car, with no timer of its own, and the gear
update writes `desired_gear_display` at once; a DLL write is queued and applied on the next flow tick (Swofty
`hud.md`). That supports B, by one tick or more. How often the game calls the dial's update, and where in a tick a
binding takes a value, were not read. Both are built.

### 6.1 A: the DLL's hold

`hud_model.cpp`: when the gear read changes, every strip place from the gear left up to, but not including, the new
gear (so also the places passed when several gears go by between two frames) is held for `kSgearHold` = 0.3 s on the
model's clock; `View.sgear_hold` is the bit mask of the held places and `publish_sgear` writes both leaves of a held
place false. Per place: no other place's leaves change, so a suggestion several gears away never blinks while the
driver shifts toward it. A frame without a gear keeps the last gear read; another car or a restart clears the holds.
0.3 s: far longer than any frame order can differ (a few ticks), short enough that a real suggestion on a gear just
left (the driver shifted past the suggested gear) comes up without a noticeable wait. Host tests: `test_sgear_hold`.

### 6.2 B: the template's delay

A place's two marks hang on an anim null (`zh_sg<k>_anim`) with a clip, played by `x_sg<k>`:

- The clip (scale only, on the halo's clip time base: one play runs fraction 0.10 to 0.90 in 0.75 s on the linear
  curve): folded (scale 0.001, as the rival line's fold) from the play's start for 9 of its 48 key intervals = 0.141 s,
  full size from the next key (0.156 s) to the play's end, and full size at both ends of the clip and in the scene.
- Every event of `sg_gear`: each place it hides first gets `goToFraction(0.10)` (it waits folded at the play's
  start); the place it names gets `show` and then `playToFraction(0.90)`. A player is always signalled while its
  place's group is shown, and both signals of a pair run in the one event. So a place is delayed exactly when the game newly
  names it. A place that stays up receives nothing. A signal to the start only ever reaches a place that the same
  event hides.
- `halo_ctl`'s `trigger`: `goToFraction(0.90)` to all nine, then `sg_gear`'s register and query: a mark that is up
  when the dial is shown again stays up without a blink.
- 0.141 s is one key interval more than the longest the leaves can trail the game's value that can be shown: the DLL's frame may read the
  gearbox one tick after the game's update, the write applies one tick later, a frame whose write budget (40) is
  used up adds one, the binding at most one: four ticks, which is 0.125 s at 32 frames a second (0.141 s: at 28).
- It is a clip, not a timer, because `goToFraction` + `playToFraction` from a decision node's event run in game on
  this very dial at every shift (the gear digit's tick) [game], while no timer node of this addon has been seen
  running in game. It does not depend on the Animations option: no DLL leaf takes part.

A real suggestion appears up to 0.156 s later than the game names it (after a hold: up to 0.3 s after the shift).

### 6.3 What a fault does

| What goes wrong | What the player sees |
|---|---|
| The players' signals do nothing | the marks are at full size (the scene's pose): the first build's behaviour, flash included |
| `goToFraction` runs, `playToFraction` does not | the named place's marks stay folded until the backstop: `sg_gear`'s event also resets the timer `sg_t` (0.85 s, just after a play's end; stopped while no place is named); its `time_out_expired` queries `sg_q`, a second MVCD on `desired_gear_display` that is never registered, whose event sends `goToFraction(0.90)` to the named place. Both signals are proven together in game (the gear tick); the timer's shape is the stock HUD's and `an_omt`'s |
| The timer never fires | nothing: it only matters in the row above |
| The timer fires at the very tick of a shift | that one shift may show the first build's flash (the named place is put at full size) |
| The game writes the same value again and the node fires again | the named place is played to the end it is already at: nothing changes |
| The game's value trails the DLL's leaves by more than the hold | the first build's flash under order A, from 0.3 s after the shift |

Not built: the game's own bool `showing_desired_gear` (written in the same update as the value, true only while the
suggestion differs from the current gear) as the gate of the place groups. It would remove both orders at the source
with no timing at all, but no stock node binds it, so its type and content rest on the static reading alone.
