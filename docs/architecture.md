# Architecture

The halo is part of the game's own HUD. The game's UI draws it, and the game's HUD editor moves and resizes it. A
native DLL reads the game's state in-process and fills view-model values for it. Nothing leaves the process: there
is no UDP, no socket, no shared memory and no companion app.

```
 F1_25.exe (one process)
 ┌─────────────────────────────────────────────────────────────────────────────────────────┐
 │ game memory ──read only──> IGameStateProvider (game_state_f1_25.cpp) ──> GameState       │
 │                                                                            │             │
 │                                hud_model.cpp (no memory access) <──────────┘             │
 │                                       │ View                                            │
 │                     leaves.hpp publish: swofty::hud::set("view_model_data.hud_halo_*")   │
 │                                       │                                                 │
 │ game UI: hud_dynamic_templates.ui (halo_template.erp) binds the leaves and the game's     │
 │ own values (speed_str, revs, ers_stored, om_active, is_xm_active, #session.*)            │
 │                                       │                                                 │
 │ game UI: dial_om_xm.idf (halo_scene.erp) = stock dial parked + halo scene (sprites,      │
 │ masks, text) inside boundless_customisation -> movable and resizable in the HUD editor   │
 │                                                                                          │
 │ HUD editor: dial_complete.idf + .uipre (halo_scene.erp) = static halo copy 'halo_pv',    │
 │ stock dial hidden by the preview data; hidden again in game by hud_f1_dial and the       │
 │ spectator HUD's modern_dial (halo_template.erp, halo_spectator.erp)                      │
 │                                                                                          │
 │ 2025 / F2 cars: live halo copies h25 (dial_complete.idf) and hf2 (dial_f2_complete.idf), │
 │ shown by hud_f1_dial / hud_f2_dial while the leaf cls (setting all_cars) is on; DRS      │
 │ pill and ERS mode pill switched by decision nodes on drs_pit_state / ers_mode            │
 └─────────────────────────────────────────────────────────────────────────────────────────┘
```

## Runtime (native/)

| Part | File | Role |
|---|---|---|
| Entry | `halo_hud.cpp` | Swofty native addon. Runs on the game's flow thread (`on_frame`). Reads options, samples the provider, runs the model, publishes the leaves, writes the validation log |
| Provider | `game_state.hpp`, `game_state_f1_25.cpp` | `IGameStateProvider::sample()` fills `GameState`. Build-checked (`compatible()`); fault-free copies only; never writes |
| Model | `hud_model.cpp` | Turns `GameState` into what the halo shows (`View`): eased capsule and pedal fills (the 2026 scale and the 2025 cars' 120 kW scale), discrete states unchanged, rival choice, turn number |
| Leaves | `leaves.hpp` | The `hud_halo_*` view-model leaves (strings and booleans), written only when they change |
| Track data | `halo_track.cpp`, `halo_corners.hpp` | Official corner lists for stock circuits (matched by name and length) |
| Validation log | `diag_log.cpp` | Optional CSV for the in-game test drive (`tools/ingame/analyze_diag.py`) |

Field provenance, lifecycle and cost: `docs/internal-state/fields.md`.

## Graphics pipeline (tools/)

| Step | Tool | Output |
|---|---|---|
| 1. Reference drawing | `tools/halo.js` (canvas, HUD units, origin = dial centre) | the look; theme `authentic` is what the game shows |
| 2. Sprite export | `tools/native/export_sprites.py` (`tools/export_native.html` + `export_native.js` in headless Edge `--dump-dom`, one sprite per run; `--keep` copies a previous set's sprites unchanged) | 125 RGBA sprites (64 halo, 61 G-force meter) with their HUD-unit bounds, plus G and P |
| 3. Textures | `export_sprites.py` (or `tools/native/textures.py` for a one-page dump) | PNGs, `sprites.npz` and `sprites.json`; `build_native.py` encodes BC7 |
| 4. Archives | `tools/native/build_native.py` (`halo_native.py`, `erpbuild.py`, `bc7.py`) | `erp/halo_scene.erp`, `erp/halo_template.erp`, `erp/halo_spectator.erp`, `erp/halo.json` (Swofty overlay ops) built from the game's stock resources; the class halos too (Car classes below) |
| 5. Checks | `check_leaves.py` (template vs DLL leaves; `info.json`, `info_2025.json`, `info_f2.json`), `scene_dump.py` + `sim_page.py` (browser simulation of the built scene; with `dial_complete.idf`, `preview.json` and root `halo_pv`, the HUD editor preview), `class_preview.py` (the 2025, F2 and 2026 halos with the template's decision nodes applied: `docs/halo-car-classes/build/preview.html`), `spectator_preview.py` (the three spectator dials with a watched car's state: `docs/spectator-ui/build/preview.html`) | pass/fail and rendered pages |

Dynamic parts in the built scene:

- One sprite per slat, shown cumulatively.
- Two sprites per gear digit: the lit one while engaged, the unlit one otherwise.
- Static windows for the capsule levels.
- A sliding window over the battery fill.
- A rotating quad under a texture mask for the RPM bar.
- The G-force meter (setting `g_meter`, `docs/gmeter/design.md` §8): group `halo_std` (base, Boost, Overtake,
  battery, capsules, speed) shows while it is off; group `halo_gmeter` (hidden in the scene, shown by the template
  while it is on) holds its base, label, 8 segments, 4 white and 4 red bars, and one sprite per value digit and place.
- Game text styles for speed, mph, turn number and names, placed with the game's measured text model: the text
  origin is the alignment anchor and the baseline, and the cap height is 0.672 em (measured in game).

## HUD editor (moving and resizing)

The game's HUD editor (`screens/hud_customisation.ui`, flow_options.erp) edits the dial as one element. What it
shows, and what it saves, come from these stock resources:

| What | Where | Effect |
|---|---|---|
| Which scene the editor shows | `hud_layouts.uidl` (persistent.erp): the dial group's leader `dial_f1` = `dial_complete.idf`; `dial_f2`, `dial_f1_om_xm` (the 2026 dial) and `dial_f2_26` follow it (`dynamicGroup`) | The editor always shows `dial_complete`, whatever the car |
| How it looks there | no template runs in the editor: the scene's own state plus its `.uipre` preview data (the stock 75 %, gear 5, 135 MPH, RPM 10045) | the halo has to be in `dial_complete` itself, statically |
| Selection box | the scene root's `tl_customisation` / `br_customisation` points (the `eBoundless` subtree does not count) | set to the halo's footprint in both dial scenes |
| Saved layout | `Documents\My Games\F1 25\hud_customisation\hud_customisation.xml`: one x, y, scale per layout (Practice, Qualifying, Race, ...), the same for all four dial keys | applied to the dial instance's root, so `boundless_customisation` and the halo under it follow |

So the addon puts a static copy of the halo (`halo_pv`, the `PREVIEW` state in `halo_native.py`) into
`dial_complete`, and its `.uipre` hides the stock dial's four parts and fills the copy's texts. In game, the
`hud_f1_dial` template and the spectator HUD's `modern_dial` hide `halo_pv`. The spectator HUD shows the four parts
(static values, no bindings). `hud_f1_dial` shows them while the setting `all_cars` is off (their `visible` bound to
the leaf `cls`, negated) and the 2025 cars' halo while it is on (Car classes below). The editor shows the halo for
every car, because the dial preview is shared by all dial types. To be confirmed in game: the editor shows the copy
and its box, and with `all_cars` off the F1 25 dial is unchanged in a 2025 car.

## Car classes (2025 and F2 cars)

The running dial template tells the car class (`docs/halo-car-classes.md` 2.1), so each class has its own live copy
of the halo in the scene its template drives.

| Class | Scene, copy | Differences from the 2026 halo |
|---|---|---|
| 2025 F1 | `dial_complete.idf`, root `h25` beside `halo_pv` | DRS pill in place of active aero; `ERS MODE` caption and the mode pill (NONE / MEDIUM / HOTLAP / OVERTAKE) in place of Boost and Overtake, with battery and capsules in group `h25_ers` (shown while the game's `has_ers`); capsules on the DLL's 120 kW leaves `rk` / `dk` |
| F2 | `dial_f2_complete.idf`, root `hf2` under `ui_visibility_hook` > `boundless_customisation` | DRS pill; no battery, capsules or pills (base `base_f2`); its quads clone the scene's centred edge quad `central_bg_edge` and bind through their own material bindings (`resources.EdgeBindings`) |

- Each copy is hidden in its scene, so the HUD editor and the spectator HUD never show it. Its anim nulls keep the
  2026 names (`zh_*`); the scene's string table and clips are extended for them.
- Template: under each dial's `[F1HD]` (`hud_f1_dial` / `hud_f2_dial`), the copy's bindings and a group `halo_ctl`
  with the decision nodes and the switch nodes. `halo_ctl` registers its decision nodes like the stock dial's
  `drs_and_pit_distance`: group command `trigger` (register + query each node) and `untrigger` (unregister), sent
  from the `[F1HD]`'s `show` and `hide` commands after the stock signals.
- Decision nodes: an MVCD on `drs_pit_state` (one event per state: grey, outline or green pill) and four SVCDs on
  `ers_mode` (`ui32` 0–3, equality: one per mode pill). No DLL leaf for the mode, so it also works with the DLL's
  provider off.
- Setting `all_cars` → DLL leaf `cls`: shows the copy's root; negated, it shows the stock dial's parts (2025: the
  editor-copy control's four parts; F2: `frame`, `fuel`, `holder_central`, `pit_indicator`).
- The 2026 dial (`dial_om_xm.idf`, `hud_f1_dial_om_xm`) is unchanged; the build checks its template subtree.

## Rules the code keeps

- The renderer never touches memory; only the provider reads it, and only through fault-free copies.
- No value is invented: a field that cannot be read hides its part of the halo.
- Discrete states (gear, Boost, Overtake, aero mode, turn) are never interpolated.
- No per-frame scans, no allocations in the read path, no locks or blocking.
- Any other game build: the provider switches off and the halo uses only the game's own view-model values.
