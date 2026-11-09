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
 └─────────────────────────────────────────────────────────────────────────────────────────┘
```

## Runtime (native/)

| Part | File | Role |
|---|---|---|
| Entry | `halo_hud.cpp` | Swofty native addon. Runs on the game's flow thread (`on_frame`). Reads options, samples the provider, runs the model, publishes the leaves, writes the validation log |
| Provider | `game_state.hpp`, `game_state_f1_25.cpp` | `IGameStateProvider::sample()` fills `GameState`. Build-checked (`compatible()`); fault-free copies only; never writes |
| Model | `hud_model.cpp` | Turns `GameState` into what the halo shows (`View`): eased capsule and pedal fills, discrete states unchanged, rival choice, turn number |
| Leaves | `leaves.hpp` | The `hud_halo_*` view-model leaves (strings and booleans), written only when they change |
| Track data | `halo_track.cpp`, `halo_corners.hpp` | Official corner lists for stock circuits (matched by name and length) |
| Validation log | `diag_log.cpp` | Optional CSV for the in-game test drive (`tools/ingame/analyze_diag.py`) |

Each value's source (offsets, types, accepted ranges, what happens when it cannot be read) is named next to the
read in `game_state_f1_25.cpp`.

## Graphics pipeline (tools/)

| Step | Tool | Output |
|---|---|---|
| 1. Reference drawing | `tools/halo.js` (canvas, HUD units, origin = dial centre) | the look; theme `authentic` is what the game shows |
| 2. Sprite export | `tools/export_native.html` + `export_native.js` (headless Chrome `--dump-dom`) | 56 RGBA sprites with their HUD-unit bounds, plus G and P |
| 3. Textures | `tools/native/textures.py` | PNGs and BC7 blocks (`sprites.json`) |
| 4. Archives | `tools/native/build_native.py` (`halo_native.py`, `erpbuild.py`, `bc7.py`) | `erp/halo_scene.erp`, `erp/halo_template.erp`, `erp/halo_spectator.erp`, `erp/halo.json` (Swofty overlay ops) built from the game's stock resources |
| 5. Checks | `check_leaves.py` (template vs DLL leaves), `scene_dump.py` + `sim_page.py` (browser simulation of the built scene; with `dial_complete.idf`, `preview.json` and root `halo_pv`, the HUD editor preview) | pass/fail and a rendered page |

Dynamic parts in the built scene:

- One sprite per slat, shown cumulatively.
- Two sprites per gear digit: the lit one while engaged, the unlit one otherwise.
- Static windows for the capsule levels.
- A sliding window over the battery fill.
- A rotating quad under a texture mask for the RPM bar.
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
`hud_f1_dial` template and the spectator HUD's `modern_dial` hide `halo_pv` and show the four parts (static values,
no bindings), so the F1 25 dial looks as before; the F2 dials use other scenes and are untouched. The editor shows
the halo for every car, because the dial preview is shared by all dial types. To be confirmed in game: the editor
shows the copy and its box, and the F1 25 dial is unchanged in a 2025 car.

## Rules the code keeps

- The renderer never touches memory; only the provider reads it, and only through fault-free copies.
- No value is invented: a field that cannot be read hides its part of the halo.
- Discrete states (gear, Boost, Overtake, aero mode, turn) are never interpolated.
- No per-frame scans, no allocations in the read path, no locks or blocking.
- Any other game build: the provider switches off and the halo uses only the game's own view-model values.
