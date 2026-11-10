"""Game-native F1 TV timing tower (Phase 2): replaces the stock leaderboard (template hud_track_position, scene
driver_position_table_stacked.idf) in place. The game's own UI draws everything: baked sprites from tools/tower/tower.js
on quads, live text in the game's own text styles, the F1 logo and FIA badge as the game's own textures.

Where the tower lives
- The stacked table scene has no quad mesh of its own, so the tower is built into the scene of the table's bottom cap
  (driver_position_bottom_cap.idf) and drawn by a second instance of it, 'tt_host', placed at the table's top-left.
  Every tower quad reuses that scene's own mesh 'pill_base' (the halo's mechanism: own-scene mesh, new material
  binding per sprite). The tower's root 'tt_root' is hidden by default, so the stock cap instance never shows it.
- In game, template nodes under hud_track_position show tt_host (and hide the stock table, element 'mask') while the
  DLL leaf hud_tt_on is true; while it is false or absent the stock table is back, unchanged.
- HUD editor (no template runs there; seen in game 2026-11-09: the editor draws every tower element whatever its
  isHidden, with only the .uipre's texts): the table's .uipre hides 'mask', and in tt_host the cap graphics and the
  live tower (tt_root), and fills the texts of 'tp_root', a static copy of the tower in the preview state below that
  holds only what that state shows (one element per state, no bindings: the halo's dial_complete pattern, which draws
  cleanly in the editor). In game, static template nodes hide tp_root in both cap instances.
- Team logos (round 3): the stock pill's own pattern. Each row holds an eXRef of the stock logo unit
  (driver_position_team_logo.idf, cloned from the pill row's 'team_logo' reference: the unit's quad, mesh and material
  binding), and a template node sets textureOverride on the unit's 'team_logo' quad from the DLL's hud_tt_rNN_badge with
  the stock pill's exact property tag (stock: team_badge_image, textureOverride <- team_badge_texture). Two nested nulls
  show it only while hud_tt_teamcol and hud_tt_rNN_bdg are both true. The editor copy has no logo (the stock editor
  preview draws none either).
- Team-colour bar (round 4, docs/timing-tower/names-and-colour-bar.md): per row and vehicle id, a null shown by
  hud_tt_rNN_cVV holds that car's code text and a bar quad (a white sprite; a template node sets its colourOverride from
  the game's #session.cars.car<vid>.nub_colour, as the halo tints its white sprites from the current car's). The code
  text no longer binds its own visible, so the bar adds one binding per car per row. The bar shows whatever the Team
  logos setting says. The editor copy has no bar (it binds nothing).
- Replay screen (round 5, docs/timing-tower/replay-hud.md 6): a third bottom cap instance, tt_host, in the replay
  scene where the game's replay board starts, and the same tower nodes (tower_nodes) in the replay template; the
  board hides while hud_tt_on is true. See build_replay_scene() and build_replay_template() at the end. Since round 6
  the tower is drawn there at REPLAY_SCALE (0.78), smaller than the board (0.9), from the same top-left.
- Series logo (round 6, 2026-11-10): the header's logo is the game's own lap counter logo, so an F2 session shows the
  F2 logo and an F1 session the F1 logo. The header holds an eXRef of the stock unit car_category_logo.idf (cloned from
  the lap counter scene's reference) and a template node sets textureOverride on the unit's quad from the leaf the
  game's own lap counter binds (logo_texture: on the HUD the lap counter's view model, on the replay screen the
  screen's, which the stock replay header binds). Its default is the F1 logo's own string, the value the game writes
  in an F1 session. No DLL leaf. The HUD editor's copy keeps the F1 logo quad (tp_f1).

Coordinates: HUD units of tower.js (1 unit = 3 px at 1080p, x right, y down), origin = the tower's top-left.
Scene units: KT scene units per HUD unit (1 scene unit = screen width / 19.2).

Leaves: docs/timing-tower/leaves.md (contract, version CONTRACT_VERSION). Only bool and text DLL leaves are bound;
no int32 DLL leaf (the contract asks for the bool forms while int32 bindings are unproven in game).
"""
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NATIVE = os.path.join(os.path.dirname(HERE), 'native')
SWL = os.environ.get('SWOFTY_TOOLS', '')
sys.path.insert(0, SWL)
sys.path.insert(0, NATIVE)
from pkg import Pkg, Obj, Arr, Val  # noqa: E402
import idf as I  # noqa: E402
import uiops as U  # noqa: E402
import uinode as N  # noqa: E402
import halo_native as H  # noqa: E402  (shared helpers only; the halo's build is not changed)

CONTRACT_VERSION = 5          # leaves.md v5 (2026-11-10): trial, show (bool); v4: rNN_badge, rNN_bdg; v3: red, yel, ysec, ysna
KT = 0.03                    # scene units per HUD unit
CAP_EM = H.CAP_EM            # game font cap height / em, measured in game

STACKED = 'eaid://ui_package/art/osd/components/driver_position_table/driver_position_table_stacked.idf'
STACKED_UIPRE = 'eaid://ui_package/art/osd/components/driver_position_table/driver_position_table_stacked.uipre'
CAP = 'eaid://ui_package/art/osd/units/driver_position_table/driver_position_bottom_cap.idf'
CAP_MESH = CAP + '/pill_base?context=render'
DIAL = 'eaid://ui_package/art/osd/components/dial/dial_om_xm.idf'       # eText model: speedo_number (as the halo)
LAPC = 'eaid://ui_package/art/osd/components/lap_counter/lap_counter.idf'   # eCentre model: centre_lap_value
# Team logos (round 3): the stock pill row, its eXRef of the logo unit (the model for the tower's), the unit and the
# quad inside it that the stock pill's textureOverride targets
ROW = 'eaid://ui_package/art/osd/units/driver_position_table/driver_position_row.idf'
LOGO = 'eaid://ui_package/art/osd/units/driver_position_table/driver_position_team_logo.idf'
LOGO_XREF, LOGO_QUAD = 'team_logo', 'team_logo'
STOCK_PILLS = 'hud_track_position.osd_visibility_option.track_position'
STOCK_PILL_ROWS = ('lead_entry', 'entry_0', 'entry_1', 'entry_2', 'entry_3')
STOCK_BADGE = ('team_badge_image', 'textureOverride', 'team_badge_texture')   # node, property, pill leaf
TEMPLATE_PARENT = 'hud_track_position.osd_visibility_option.track_position'
STOCK_CAP_NODE = TEMPLATE_PARENT + '.bottom_cap'
CLOCK_MODEL = 'hud_session_timer_dynamic'   # the stock template whose time_remaining_formatter (UITF) is cloned
HOST, ROOT, CTL, MASK = 'tt_host', 'tt_root', 'tt_ctl', 'mask'
PV_ROOT = 'tp_root'          # the HUD editor's static copy of the tower (fix round 1), beside tt_root in the cap scene
# The game's lap counter (template hud_lap_counter, scene lap_counter.idf: F1 logo, session label, LAP x / y) sits
# right above the tower; it is hidden while the tower shows (fix round 1). Its parts the stock template never shows or
# hides (so a bound visible here never fights the game's own): every top-level element except the two lap holders,
# and inside those holders the parts the stock nodes leave alone.
LAPC_TEMPLATE = 'hud_lap_counter.osd_visibility_option'
LAPC_HIDE = ('car_category_logo', 'edge_base', 'edge_border', 'lap_bg', 'lockup', 'session_icon',
             'centre_lap_value', 'separator_bg', 'separator_bg_top', 'centre_formation')
LAPC_STOCK_KIDS = ('car_category_logo', 'edge_base', 'edge_border', 'holder_formation', 'holder_standard', 'lap_bg',
                   'lockup', 'session_icon')
# Series logo (round 6): the lap counter scene's reference to the stock logo unit (the model for the header's), the
# unit and its quad, and the stock lap counter's binding on that quad (node, property, the leaf relative to the lap
# counter's view model). The HUD binds the same leaf by its absolute path: a HUD element's view model is
# #view_model_data.hud.content.<its nameId in hud_layouts.uidl> (check_hud_layouts: hud_lap_counter -> lap_counter; the
# stock hud_track_position binds its own as #view_model_data.hud.content.lap_times.*). The game writes
# "#overrides.osd.timing_tower.timing_tower_logos." + the session's series key (lc_f1_logo, lc_f2_logo, lc_f2_26_logo:
# overrides.uidb); SERIES_DEFAULT, the F1 value, holds until the leaf is read.
CAT_LOGO = 'eaid://ui_package/art/osd/units/lap_counter/car_category_logo.idf'
CAT_XREF, CAT_QUAD = 'car_category_logo', 'logo_icon'
STOCK_SERIES = (LAPC_TEMPLATE + '.logo', 'textureOverride', 'logo_texture')
HUD_LAPC_NAME = 'lap_counter'                        # hud_lap_counter's nameId in the stock HUD layouts
HUD_SERIES = f'#view_model_data.hud.content.{HUD_LAPC_NAME}.logo_texture'
SERIES_DEFAULT = '#overrides.osd.timing_tower.timing_tower_logos.lc_f1_logo'
SERIES = '@series_logo'      # a series logo record's leaf in Tower.recs: tower_nodes() puts in the screen's own
SERIES_EL = 'tt_logo'        # the header's eXRef (the HUD editor's copy keeps the F1 quad tp_f1)
HUD_LAYOUTS = 'eaid://ui_package/art/osd/screens/hud_layouts/hud_layouts.uidl'
VM = '#view_model_data.hud_tt_'
NROWS, NCARS = 22, 24
# Gap column vs driver code (fix round 1, 2026-11-09; measured on in-game Bahrain screenshots, ui-build.md "Fix round 1").
# In game the widest 2026 code, HAM (OSD_24_bold), is 1.44 p wide (the drawing's Saira metric said 1.39 p), and the
# game's number font is about 40 % wider than the drawing's: "+33.7" is 26.3 HUD units wide, so it filled its whole box
# and sat 0.08 p from the code. Now every code is boxed to CODE_BOX (clampwidth: a longer code squeezes instead of
# growing into the gap column), and every gap text box stops GAP_CLEAR short of that box (both in p).
CODE_BOX = 1.47
GAP_CLEAR = 0.20
CODE = '#session.cars.car{v}.driver.name_code'     # leaves.md section 4 (L2), one text per vehicle id. The
# game names the list elements snprintf("car%u", vid): car0 ... car23, never zero-padded (re-findings.md 4)
NUB = '#session.cars.car{v}.nub_colour'            # the car's team colour (rgba): leaves.md section 4 (L2); the stock
# template binds #session.current_car.nub_colour as rgba, so the type check reads the tag from there
# The bar's colourOverride while the game's value is absent: fully transparent, so no colour means no bar (never a
# made-up colour; the stock and halo nodes use white there).
BAR_DEFAULT = '#00000000'
LAPS = '#session.number_of_laps'                    # stock hud_lap_counter binds it (si32)
CLOCK_IN, CLOCK_STR = '#session.time_remaining', 'time_remaining_str'   # stock session timer formatter
DROPZONE = '#session.dropzone'                      # optional debug display (build flag), int32 -> si32
# Game values no stock template node binds (the type check needs their type; evidence in leaves.md section 4)
KNOWN_TYPES = {
    '#session.current_car.driver.name_code': 'stri',   # VM string, row builder 0x1424be430 (re-findings.md 4c)
    DROPZONE: 'si32',                                    # VM type object "int32" (field-traces.md 5.1, L2)
}
TAGS = {'bool': 'bool', 'text': 'stri', 'int32': 'si32'}
UIPRE_TEXT, UIPRE_VISIBLE, UIPRE_LOC = 4045306521, 839438211, 3919839003   # .uipre setter keys (stock table)
# bar (round 4): the logo unit's layer, over the row's fills and the player highlight, under the texts and the retired
# row's half-opaque layer (so a retired row's bar dims with it)
LAYER = {'bg': 20, 'hl': 22, 'p1': 23, 'mark': 25, 'bar': 30, 'text': 40, 'dim': 45}
# the yellow flag block's second line (round 2): the game's own word, localised, then hud_tt_ysec ("2", "1 3").
# Swap the label here (a game string id, localised): never "TRACK HAZARD" (design decision, 2026-11-09).
YEL_LABEL = 'lng_sector'
YEL_TYPICAL_EM = 5.0          # "SECTOR 2" in the game font, in em: places the line if the eCentre keeps it in place

# Time Trial board (2026-11-10). While hud_tt_trial is true (the DLL reads the game mode
# label "time_trial") the template shows tt_trial instead of the standings (tt_stack): a header with the series logo,
# TIME TRIAL and the game's lap line, then up to five rows, one per pill of the game's own board (Track Position's view
# model pill_0 ... pill_4: the stock pills' leaves, bound with the stock pills' tags). Rows and gap cells are switched by
# decision nodes on the pills' own active and show_text_label, as the stock pills switch theirs. No DLL row leaf.
LAPTIMES_VM = '#view_model_data.hud.content.lap_times.'     # Track Position's view model (check_hud_layouts)
LAPC_VM = f'#view_model_data.hud.content.{HUD_LAPC_NAME}.'  # the lap counter's
NPILLS = 5
PILL = LAPTIMES_VM + 'pill_{i}.{leaf}'
# the pill leaves the board binds: leaf -> (the stock pill's node that binds it, property); build_template reads each
# tag from all five stock pills (stock_trial)
TRIAL_PILL = {'pos_name': ('position', 'text'), 'driver_name': ('name', 'text'), 'gap_text': ('gap_text', 'text'),
              'nub_colour': ('team_colour', 'colourOverride'),
              'team_badge_texture': ('team_badge_image', 'textureOverride'),
              'show_tyres': ('tyre_info', 'visible'), 'tyre_compound': ('tyre_info.tyre_icon', 'textureOverride'),
              'is_current_car': ('player_indicator', 'visible')}
TRIAL_ACTIVE = 'pill_{i}.active'          # Track Position's own decision nodes read it so (lead_entry_active, ...)
TRIAL_GAPSHOW = 'show_text_label'         # each stock pill's should_show_gap_text reads it (relative to its pill)
STOCK_TT = 'stock'                        # a rec's tag placeholder: the stock template's tag for that value
LAP_VISIBLE = '#ui_menu_data.hud_lap_number_visible'        # the stock lap counter's switch: LAP n, or its own label
LAP_DESC = '#ui_menu_data.hud_lap_description_string'
LAP_DESC_LOC = '#ui_menu_data.hud_lap_description_loc_tag'
LAP_NOW = LAPC_VM + 'current_car_path.lap'                  # stock lap_value: text <- current_car_path.lap (relative)
LAP_NOW_STOCK = (LAPC_TEMPLATE + '.standard_lap_holder.lap_value', 'text', 'current_car_path.lap')
TRIAL_LABEL = ('TIME', 'TRIAL')  # static, two lines beside the logo as the game's own lettering (English in game)
TRIAL_ROOT, TRIAL_SERIES_EL = 'tt_trial', 'tt_tlogo'
TRIAL_TYRE = 0.6             # the tyre icon's side, in p (the stock logo unit: the game's own tyre texture fills it)
# the band as the game's lap counter lays it out: the series logo on the left (the standings' logo box, moved), the
# FIA badge under it, TIME / TRIAL centred in the rest (HUD units: left edge, label cap, line gap)
TRIAL_LOGO_X, TRIAL_LABEL_CAP, TRIAL_LABEL_GAP = 5.0, 5.5, 4.0
# the session line "LAP 0" as the race line's: a left-to-right stacker in an eCentre, started at -TRIAL_LAP / 2 (HUD
# units, a typical "LAP 1") so it is centred in case the eCentre keeps it in place
TRIAL_LAP = 23.5


def leaf(key):
    return VM + key


def style_n(style):
    """'OSD_24_regular' -> 24: the style's em is N/100 scene units"""
    return int(re.search(r'(\d+)_', style).group(1))


# ---------------------------------------------------------------- contract
def contract_types(path):
    """docs/timing-tower/leaves.md -> {'#view_model_data.hud_tt_<leaf>': tag} for every leaf of sections 2-4."""
    text = open(path, encoding='utf-8').read()
    m = re.search(r'Contract version:\s*(\d+)', text)
    if not m or int(m.group(1)) != CONTRACT_VERSION:
        raise SystemExit(f'{path}: contract version {m and m.group(1)}, this builder follows {CONTRACT_VERSION}')
    out = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 2 or cells[1] not in TAGS:
            continue
        for nm in re.findall(r'`([a-z0-9A-Z_]+)`', cells[0]):
            names = [nm]
            if 'NN' in nm:
                names = [x.replace('NN', f'{i:02d}') for i in range(NROWS) for x in names]
            if 'VV' in nm:
                names = [x.replace('VV', f'{v:02d}') for v in range(NCARS) for x in names]
            for n in names:
                out[leaf(n)] = TAGS[cells[1]]
    return out


def dll_leaves(path):
    """tower_leaves.txt from the DLL's host tests (sh native/tests/run_tests.sh <out>) -> {'#…': tag}"""
    out = {}
    for line in open(path, encoding='utf-8'):
        parts = line.split()
        if len(parts) == 2:
            out['#' + parts[0].lstrip('#')] = parts[1]
    return out


# ---------------------------------------------------------------- scene
def logo_geometry(logo_bytes):
    """The stock logo unit's drawn quad (driver_position_team_logo.idf: icon_transition > team_logo, a square on its
    own mesh and material binding) -> (centre x, centre y, side, layer), scene units in the unit's root frame (y up).
    Checked: the quad's ancestors only translate (no rotation, scale 1) and its extents are a centred square, so an
    eXRef at position P and uniform scale s draws it centred at P + s * centre, s * side wide."""
    idf = I.Idf(logo_bytes)
    assert idf.scenes[0].name == I.component_id(LOGO), 'not the stock logo unit'
    quads = [(e, d) for e, d in idf.scenes[0].root.walk() if e.name == LOGO_QUAD]
    assert len(quads) == 1, ('logo unit: one quad named', LOGO_QUAD, len(quads))
    q = quads[0][0].obj
    assert q['geoms'].items and I._val(q['geoms'].items[0].get('resourceid')).startswith(LOGO + '/' + LOGO_QUAD)
    lo, hi = I.get_param(q, 'minExtents'), I.get_param(q, 'maxExtents')
    w, h = hi[0] - lo[0], hi[2] - lo[2]                    # x and z: the quad is turned like the cap's pill_base
    assert abs(w - h) < 1e-6 and abs(lo[0] + hi[0]) < 1e-6 and abs(lo[2] + hi[2]) < 1e-6, (lo, hi)
    x, y = 0.0, 0.0
    chain = []

    def path(o, trail):
        if o is q:
            chain.extend(trail)
            return True
        return any(path(c, trail + [c]) for c in (o.get('children').items if o.get('children') is not None else []))
    assert path(idf.scenes[0].entry['scene'], [])
    for o in chain:
        if o is not q:
            assert all(abs(v - 1.0) < 1e-6 for v in o['scale'].value[:3]), ('logo unit: a scaled ancestor', o['name'])
            r = o['rotation'].value
            assert abs(abs(r[3]) - 1.0) < 1e-6, ('logo unit: a rotated ancestor', o['name'])
        x += o['position'].value[0]
        y += o['position'].value[1]
    layer = I.get_param(q, 'eLayer.layer')
    assert isinstance(layer, int) and not I.get_param(q, 'eLayer.layerIsOffset'), 'logo unit: an absolute layer'
    return x, y, w, layer


def _quat_axes(r):
    """quaternion (x, y, z, w) -> the images of the x and z axes"""
    x, y, z, w = r[:4]
    return ((1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)),
            (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)))


def series_geometry(unit_bytes):
    """The stock lap counter logo unit's drawn quad (car_category_logo.idf: icon_transition > logo_icon, on its own
    mesh and material binding) -> (left, top, width, height, layer): its top-left corner and size in scene units, in the
    unit's root frame (y up). Checked: the quad's ancestors only translate; the quad is not scaled and its quarter turn
    about x lays the mesh's z on -y (as the cap's pill_base), so its extents (x 0..w, z 0..h) span x left..left + w and
    y top..top - h. Its pivot (the quad's centre) is left out, as the stock places it: the lap counter scene puts the
    unit 0.17 inside its panel's top-left (lap_bg spans y 0 to -1.15, the separator under the logo is at -0.75), which
    holds only without the pivot. An eXRef at P with uniform scale s draws it from P + s * (left, top)."""
    idf = I.Idf(unit_bytes)
    assert idf.scenes[0].name == I.component_id(CAT_LOGO), 'not the stock lap counter logo unit'
    quads = [e for e, _ in idf.scenes[0].root.walk() if e.name == CAT_QUAD]
    assert len(quads) == 1, ('series logo unit: one quad named', CAT_QUAD, len(quads))
    q = quads[0].obj
    assert q['geoms'].items and I._val(q['geoms'].items[0].get('resourceid')).startswith(CAT_LOGO + '/' + CAT_QUAD)
    drawn = [e.name for e, _ in idf.scenes[0].root.walk() if e.geoms]
    assert drawn == [CAT_QUAD], ('series logo unit: other drawn elements', drawn)
    lo, hi = I.get_param(q, 'minExtents'), I.get_param(q, 'maxExtents')
    assert abs(lo[1]) < 1e-6 and abs(hi[1]) < 1e-6 and hi[0] > lo[0] and hi[2] > lo[2], (lo, hi)
    ax, az = _quat_axes(q['rotation'].value)
    assert all(abs(a - b) < 1e-5 for a, b in zip(ax + az, (1, 0, 0, 0, -1, 0))), ('series logo quad turned', ax, az)
    assert all(abs(v - 1.0) < 1e-6 for v in q['scale'].value[:3]), 'series logo quad scaled'
    chain = []

    def path(o, trail):
        if o is q:
            chain.extend(trail)
            return True
        return any(path(c, trail + [c]) for c in (o.get('children').items if o.get('children') is not None else []))
    assert path(idf.scenes[0].entry['scene'], [])
    x, y = 0.0, 0.0
    for o in chain:
        if o is not q:
            assert all(abs(v - 1.0) < 1e-6 for v in o['scale'].value[:3]), ('series logo unit: a scaled ancestor', o['name'])
            assert abs(abs(o['rotation'].value[3]) - 1.0) < 1e-6, ('series logo unit: a rotated ancestor', o['name'])
        x += o['position'].value[0]
        y += o['position'].value[1]
    layer = I.get_param(q, 'eLayer.layer')
    assert isinstance(layer, int) and not I.get_param(q, 'eLayer.layerIsOffset'), 'series logo unit: an absolute layer'
    return x + lo[0], y - lo[2], hi[0] - lo[0], hi[2] - lo[2], layer


def check_hud_layouts(uidl_bytes):
    """The stock HUD layouts (hud_layouts.uidl, persistent.erp): the view model path HUD_SERIES names. The 'default'
    layout must hold the game's lap counter (template hud_lap_counter, key lap_counter) as nameId HUD_LAPC_NAME and
    Track Position (hud_track_position, the tower's own element) as 'lap_times', and no other layout may swap either
    (a session layout replaces a default component by its dynamic key). -> {template: nameId}"""
    p = Pkg(uidl_bytes)
    assert p.root['id'].value == 'hud_layouts', 'not the stock HUD layouts'
    want = {'hud_lap_counter': ('lap_counter', HUD_LAPC_NAME), 'hud_track_position': ('track_position', 'lap_times')}
    found = {}
    for lay in p.root['layouts'].items:
        lid = lay['id'].value
        for c in lay['components'].items:
            tmpl = c.get('eDynamicLayout.dynamicTemplate')
            key = c.get('eDynamicLayout.dynamicKey')
            tmpl, key = (tmpl.value if tmpl is not None else None), (key.value if key is not None else None)
            for t, (k, _nm) in want.items():
                if tmpl == t or key == k:
                    found.setdefault(t, []).append((lid, tmpl, key, c['nameId'].value))
    for t, (k, nm) in want.items():
        assert found.get(t) == [('default', t, k, nm)], ('HUD layouts: where the game puts', t, found.get(t))
    return {t: nm for t, (_k, nm) in want.items()}


class Scene:
    """Builds elements into the bottom cap scene (models: its own quad and null, the halo's eText model, the stock
    lap counter's eCentre, the stock table's eStacker, the stock pill row's eXRef of the team logo unit, the stock lap
    counter's eXRef of its logo unit)."""

    def __init__(self, cap_bytes, dial_bytes, lapc_bytes, stacked_bytes, embs, row_bytes, logo_bytes, cat_bytes):
        self.idf = I.Idf(cap_bytes)
        self.entry = self.idf.scenes[0].entry
        self.root = self.entry['scene']
        assert self.idf.scenes[0].name == I.component_id(CAP), 'not the bottom cap scene'
        self.T_quad = H._find(self.root, 'pill_base')
        self.T_null = H._find(self.root, 'driver_group')
        self.T_text = H._find(I.Idf(dial_bytes).scenes[0].entry['scene'], 'speedo_number')
        self.T_centre = H._find(I.Idf(lapc_bytes).scenes[0].entry['scene'], 'centre_lap_value')
        self.T_stack = H._find(I.Idf(stacked_bytes).scenes[0].entry['scene'], 'full_stacker')
        assert all(x is not None for x in (self.T_quad, self.T_null, self.T_text, self.T_centre, self.T_stack))
        g = self.T_quad['geoms'].items[0]
        assert g['resourceid'].value == CAP_MESH, g['resourceid'].value
        assert g['asset'].value == int.from_bytes(hashlib.md5(CAP_MESH.encode()).digest()[:8], 'big')
        lo, hi = I.get_param(self.T_quad, 'minExtents'), I.get_param(self.T_quad, 'maxExtents')
        self.mesh_w, self.mesh_h = hi[0] - lo[0], hi[2] - lo[2]          # 3.04 x 0.12 (x and z: the quad is turned)
        assert abs(self.mesh_w - 3.04) < 1e-4 and abs(self.mesh_h - 0.12) < 1e-4, (self.mesh_w, self.mesh_h)
        hid = [it for it in self.T_text['params'].items if I._val(it.get('name')) == 'isHidden']
        assert hid and hid[0]['value'].type == 'bool', 'eText model lost its isHidden param'
        assert I.get_param(self.T_centre, 'centreX') is True and I.get_param(self.T_stack, 'stackerType') == 't'
        # the team logo: the pill row's own eXRef of the logo unit (fileRef, xref id and material binding as stock)
        row_idf = I.Idf(row_bytes)
        assert row_idf.scenes[0].name == I.component_id(ROW), 'not the stock pill row'
        xr = [e.obj for e, _ in row_idf.scenes[0].root.walk() if e.name == LOGO_XREF]
        assert len(xr) == 1 and I._val(xr[0].get('typeName')) == 'eXRef', 'pill row: no single team_logo eXRef'
        self.T_xref = xr[0]
        assert I.get_param(self.T_xref, 'fileRef') == LOGO and self.T_xref['xref'].value == I.component_id(LOGO)
        assert I.get_param(self.T_xref, 'XrefMaterialBinding') == I.material_binding(LOGO)
        assert not self.T_xref['children'].items and not self.T_xref['geoms'].items
        assert I.get_param(self.T_xref, 'isHidden') is None, 'the stock logo reference is never hidden by itself'
        cx, cy, self.logo_side, self.logo_layer = logo_geometry(logo_bytes)   # stock: (0.12, -0.18), 0.24, layer 30
        self.logo_c = (cx, cy)
        # between the row's fills / highlight / marks and its texts; under the retired row's half-opaque layer
        assert LAYER['mark'] < self.logo_layer < LAYER['text'] < LAYER['dim'], ('logo layer', self.logo_layer)
        assert LAYER['hl'] < LAYER['mark'] < LAYER['bar'] < LAYER['text'], ('bar layer', LAYER['bar'])
        # the series logo (round 6): the lap counter's own eXRef of its logo unit (file, xref id, material binding)
        cx = [e.obj for e, _ in I.Idf(lapc_bytes).scenes[0].root.walk() if e.name == CAT_XREF]
        assert len(cx) == 1 and I._val(cx[0].get('typeName')) == 'eXRef', 'lap counter: no single car_category_logo eXRef'
        self.T_cat = cx[0]
        assert I.get_param(self.T_cat, 'fileRef') == CAT_LOGO and self.T_cat['xref'].value == I.component_id(CAT_LOGO)
        assert I.get_param(self.T_cat, 'XrefMaterialBinding') == I.material_binding(CAT_LOGO)
        assert not self.T_cat['children'].items and not self.T_cat['geoms'].items
        assert I.get_param(self.T_cat, 'isHidden') is None, 'the stock lap counter logo reference is hidden by itself'
        *self.series_q, self.series_layer = series_geometry(cat_bytes)   # stock: (0, 0, 1.44, 0.52), layer 30
        # over the header's band (bg), under its texts
        assert LAYER['bg'] < self.series_layer < LAYER['text'], ('series logo layer', self.series_layer)
        self.embs = embs
        self.names = set()
        self.hidden = {}       # element -> hidden by default (= the editor preview state)

    def _base(self, tmpl, name, pos, rot=None, scale=(1, 1, 1), hidden=False):
        if name in self.names:
            raise KeyError('duplicate element ' + name)
        self.names.add(name)
        o = I.clone_node(tmpl)
        o.set('name', Val('stri', name))
        H._param(o, 'guid', H._guid(name))
        o.set('position', H._vec(pos))
        o.set('scale', H._vec(scale))
        o.set('rotation', Val('quat', list(rot) if rot is not None else [-0.0, -0.0, 0.0, -1.0]))
        for key in ('children', 'anims'):
            if o.get(key) is not None:
                o.set(key, Arr([], o[key].tag))
        pa = o['params']
        pa.items = [it for it in pa.items if I._val(it.get('name')) not in ('isHidden', 'eAnimationGroup.AnimGroup')]
        if hidden:
            I.set_param(o, 'isHidden', True, 'bool')
        self.hidden[name] = bool(hidden)
        return o

    @staticmethod
    def kids(o, *children):
        o['children'].items.extend(c for c in children if c is not None)
        return o

    def null(self, name, x=0.0, y=0.0, hidden=False, scale=1.0):
        return self._base(self.T_null, name, (KT * x, -KT * y, 0.0), None, (scale, scale, 1.0), hidden)

    def quad(self, name, mat, x0, y0, x1, y1, layer, hidden=False):
        """A quad over the HUD rect (x0, y0)-(x1, y1) of its parent's frame, showing material binding `mat`."""
        w, h = KT * (x1 - x0), KT * (y1 - y0)
        c = (KT * (x0 + x1) / 2, -KT * (y0 + y1) / 2, 0.0)
        o = self._base(self.T_quad, name, c, self.T_quad['rotation'].value, (w / self.mesh_w, 1.0, h / self.mesh_h), hidden)
        o['geoms'].items[0].set('materialid', Val('stri', self.embs[mat]))
        H._param(o, 'eLayer.layer', int(layer), 'si32')
        return o

    def text(self, name, style, halign, box, wrapping, textcase, hidden=False):
        o = self._base(self.T_text, name, (0.0, 0.0, 0.0), None, (1, 1, 1), hidden)
        H._param(o, 'boxWidth', float(box), 'fp32')
        H._param(o, 'halign', halign)
        H._param(o, 'style', style)
        H._param(o, 'wrapping', wrapping)
        H._param(o, 'textcase', textcase)
        H._param(o, 'eLayer.layer', LAYER['text'], 'si32')
        return o

    def centre(self, name, x, y):
        return self._base(self.T_centre, name, (KT * x, -KT * y, 0.0))

    def stacker(self, name, x, y, kind, gap_hud):
        o = self._base(self.T_stack, name, (KT * x, -KT * y, 0.0))
        H._param(o, 'stackerType', kind)
        H._param(o, 'gap', float(KT * gap_hud), 'fp32')
        return o

    def logo(self, name, x, y, side):
        """An eXRef of the stock team logo unit (a clone of the pill row's reference), scaled uniformly so that the
        unit's square quad is `side` HUD units wide and centred on HUD (x, y) of the parent's frame. No isHidden: its
        holder nulls show or hide it, as the pill row's own reference is never hidden by itself."""
        s = KT * side / self.logo_side
        pos = (KT * x - s * self.logo_c[0], -KT * y - s * self.logo_c[1], 0.0)
        return self._base(self.T_xref, name, pos, None, (s, s, 1.0))

    def series_logo(self, name, x0, y0, w):
        """An eXRef of the stock lap counter logo unit (a clone of the lap counter scene's reference), scaled uniformly
        so that the unit's quad is `w` HUD units wide with its top-left corner at HUD (x0, y0) of the parent's frame.
        No isHidden: the header's null shows or hides it, as the lap counter's own reference is never hidden by itself."""
        left, top, qw, _qh = self.series_q
        s = KT * w / qw
        pos = (KT * x0 - s * left, -KT * y0 - s * top, 0.0)
        return self._base(self.T_cat, name, pos, None, (s, s, 1.0))


class Tower:
    """The tower's elements and their bindings.
    mode 'game': the live tower (tt_root): every element, recs = one per bound element:
      {'el', 'vis': (db, negate) | None, 'text': (db, tag) | ('=', text, localise) | None}
      or, for a team logo, {'el': <the eXRef>, 'vis': None, 'text': None, 'tex': (db, tag), 'sub': LOGO_QUAD}: a
      textureOverride on the unit's quad (layout path eXRef > quad, as the stock pill's team_badge_image); the header's
      series logo (round 6) likewise with db SERIES (each template puts in its own leaf), 'sub': CAT_QUAD and
      'default': SERIES_DEFAULT
    mode 'preview': the HUD editor's static copy (tp_root, names tt_* -> tp_*): only the elements the preview state
      shows, none hidden, no bindings; pv_texts = [(element, text, localised)] for the .uipre."""

    def __init__(self, B, meta, preview, debug_dropzone=False, mode='game'):
        self.B, self.G, self.sp = B, meta['G'], meta['sprites']
        self.pv_on, self.pv_text = preview
        self.recs = []
        self.trecs = []      # the Time Trial board's recs: the HUD template only, never the replay screen's
        self.pv_texts = []
        self.debug_dropzone = debug_dropzone
        assert mode in ('game', 'preview'), mode
        self.game = mode == 'game'

    # -- helpers
    def n(self, name):
        """element name: tt_* in the live tower, tp_* in the editor copy"""
        return name if self.game or not name.startswith('tt_') else 'tp_' + name[3:]

    def shows(self, vis, neg=False):
        """preview: is an element shown by vis (negated: by not vis) in the preview state"""
        return not vis or bool(self.pv_on.get(vis, False)) != neg

    def bind(self, el, vis=None, neg=False, text=None):
        if self.game:
            self.recs.append({'el': el, 'vis': (vis, neg) if vis else None, 'text': text})

    def bind_texture(self, el, db, tag, sub=LOGO_QUAD, default=None):
        """textureOverride on the unit's quad `sub` inside eXRef `el` (game mode only): the stock pill's badge binding,
        or (sub CAT_QUAD) the stock lap counter's logo binding"""
        if self.game:
            rec = {'el': el, 'vis': None, 'text': None, 'tex': (db, tag), 'sub': sub}
            if default is not None:
                rec['default'] = default
            self.recs.append(rec)

    def bind_colour(self, el, db, tag):
        """colourOverride of quad `el` from a game colour (the team-colour bar; game mode only)"""
        if self.game:
            self.recs.append({'el': el, 'vis': None, 'text': None, 'col': (db, tag)})

    def lit(self, db, neg=False):
        return bool(self.pv_on.get(db, False)) != neg

    def hidden(self, vis, neg=False):
        """game: hidden by default unless the preview state shows it (only matters where no template runs: the
        template binds every such element in game, and the editor hides tt_root)"""
        return self.game and bool(vis) and not self.lit(vis, neg)

    def null(self, name, x=0.0, y=0.0, scale=1.0):
        return self.B.null(self.n(name), x, y, scale=scale)

    def shown_null(self, name, x=0.0, y=0.0, vis=None, neg=False):
        """a null shown in game while vis (negated: while not vis); preview: None unless the preview state shows it"""
        if not self.game and not self.shows(vis, neg):
            return None
        o = self.B.null(self.n(name), x, y, hidden=self.hidden(vis, neg))
        if vis:
            self.bind(self.n(name), vis, neg)
        return o

    def switched(self, name, sw, states, init, x=0.0, y=0.0):
        """game only (Time Trial board): a null at HUD (x, y) that a decision node shows and hides. sw: (the value as
        the decision node reads it, the same value's absolute path for the simulator); states: {'0': shown, '1': shown};
        init: shown before the first decision (the template node's static visible, the scene's isHidden)."""
        o = self.B.null(name, x, y, hidden=not init)
        self.recs.append({'el': name, 'vis': None, 'text': None, 'sw': [sw[0], sw[1], dict(states)], 'init': bool(init)})
        return o

    def quad(self, name, mat, rect, layer, vis=None, neg=False):
        if not self.game and not self.shows(vis, neg):
            return None
        x0, y0, x1, y1 = rect
        o = self.B.quad(self.n(name), mat, x0, y0, x1, y1, layer, hidden=self.hidden(vis, neg))
        if vis:
            self.bind(self.n(name), vis, neg)
        return o

    def sprite(self, name, sprite, dx=0.0, dy=0.0, layer=LAYER['mark'], vis=None, neg=False):
        s = self.sp[sprite]
        return self.quad(name, sprite, (s['x0'] + dx, s['y0'] + dy, s['x1'] + dx, s['y1'] + dy), layer, vis, neg)

    @staticmethod
    def fit_box(size, box):
        """pixel size (w, h) fitted by aspect into box (x, y, w, h) and centred in it -> (x0, y0, w, h)"""
        bx, by, bw, bh = box
        a = size[0] / size[1]
        w, h = (bw, bw / a) if bw / bh < a else (bh * a, bh)
        return bx + (bw - w) / 2, by + (bh - h) / 2, w, h

    def fit(self, name, key, size, box, layer, vis=None):
        """a game texture of pixel size (w, h), fitted by aspect into box (x, y, w, h) and centred in it"""
        x0, y0, w, h = self.fit_box(size, box)
        return self.quad(name, key, (x0, y0, x0 + w, y0 + h), layer, vis)

    def series_logo(self, name, size, box):
        """game: the header's series logo, the stock lap counter logo unit fitted like a texture of pixel size `size`
        into box (the unit's quad has that aspect), its texture bound to the screen's logo_texture (SERIES)"""
        x0, y0, w, h = self.fit_box(size, box)
        _l, _t, qw, qh = self.B.series_q
        assert abs(w / h - qw / qh) < 1e-3 * qw / qh, ('the series logo unit is not the logo texture\'s shape', qw, qh, size)
        o = self.B.series_logo(self.n(name), x0, y0, w)
        self.bind_texture(self.n(name), SERIES, SERIES_TAG, sub=CAT_QUAD, default=SERIES_DEFAULT)
        return o

    def text(self, name, x, base, cap, style, halign, box_hud, text, wrapping='clampwidth', textcase='upper',
             vis=None, neg=False):
        """eText `name` in a holder null at (x, baseline); the holder's scale sets the cap height (the game's texts
        are never scaled themselves). The eText origin is the alignment anchor and the baseline (measured in game).
        Preview: only if the preview state shows it, its text recorded for the .uipre."""
        if not self.game and not self.shows(vis, neg):
            return None
        n = style_n(style)
        sc = (KT * cap / CAP_EM) / (n / 100.0)
        holder = self.B.null(self.n(name) + '_n', x, base, scale=sc)
        t = self.B.text(self.n(name), style, halign, KT * box_hud / sc, wrapping, textcase,
                        hidden=self.hidden(vis, neg))
        self.bind(self.n(name), vis, neg, text)
        if not self.game and text:
            if text[0] == '=':
                self.pv_texts.append((self.n(name), text[1], text[2]))
            elif text[0] in self.pv_text:
                self.pv_texts.append((self.n(name), self.pv_text[text[0]], False))
        return self.B.kids(holder, t)

    # -- parts
    def header(self):
        G, p, W = self.G, self.G['p'], self.G['w']
        top = self.shown_null('tt_top', vis=leaf('hdr'))
        if top is None:
            return None
        self.B.kids(top, self.sprite('tt_hdr_bg', 'hdr', layer=LAYER['bg']))
        lg, fa = G['logo'], G['fia']
        lbox = (lg['x'], lg['y'], lg['w'], lg['h'])
        # the series logo (round 6): in game the game's own lap counter logo (F1 or F2, the game's choice) on the F1
        # logo's place and size; the HUD editor's copy keeps the F1 logo quad
        logo = (self.series_logo(SERIES_EL, GAME_SIZE['g_f1'], lbox) if self.game else
                self.fit('tt_f1', 'g_f1', GAME_SIZE['g_f1'], lbox, LAYER['mark']))
        self.B.kids(top, logo,
                    self.fit('tt_fia', 'g_fia', GAME_SIZE['g_fia'], (fa['x'], fa['y'], fa['w'], fa['h']), LAYER['mark']))
        S, base = G['sess'], G['sep'] + G['sessBase']
        # race line "LAP 10 / 71": an eCentre centres it (the stock lap counter's pattern). The lap number and the
        # word LAP sit in a right-to-left stacker, so the word follows the number's width; the slash and the total
        # are placed from the junction. The junction is set for a typical "LAP 10 / 71" in case the eCentre keeps
        # the children where they are.
        race = self.shown_null('tt_sr', W / 2, 0.0, vis=leaf('race'))
        if race is not None:
            rc = self.B.centre(self.n('tt_src'), 0.0, 0.0)
            J = 0.75 * p
            stk = self.B.stacker(self.n('tt_lap_stk'), J - S['gap2'] * p, base, 'r', S['gap1'] * p)
            num = self.text('tt_lapn', 0.0, 0.0, S['lapNum']['cap'] * p, 'OSD_30_bold', 'right', 1.6 * p,
                            (leaf('lap'), 'stri'), vis=leaf('lapna'), neg=True)
            bar = 0.36 * p
            na = self.quad('tt_lapna', 'na', (-bar, -S['lapWord']['cap'] * p / 2 - 0.03 * p, 0.0,
                                              -S['lapWord']['cap'] * p / 2 + 0.03 * p), LAYER['mark'], vis=leaf('lapna'))
            word = self.text('tt_lapw', 0.0, 0.0, S['lapWord']['cap'] * p, 'OSD_24_regular', 'right', 1.8 * p,
                             ('=', 'lng_lap', True))
            self.B.kids(stk, num, na, word)
            slash_w = 0.22 * p
            slash = self.text('tt_slash', J + slash_w / 2, base, S['slash']['cap'] * p, 'OSD_24_regular', 'centre',
                              0.5 * p, ('=', '/', False), wrapping='none')
            total = self.text('tt_laps', J + slash_w + S['gap3'] * p, base, S['laps']['cap'] * p, 'OSD_24_regular',
                              'left', 1.4 * p, (LAPS, 'laps'), wrapping='none')
            self.B.kids(top, self.B.kids(race, self.B.kids(rc, stk, slash, total)))
        # timed line "Q2 1:46": label right of the junction's left, clock left-aligned after it
        timed = self.shown_null('tt_st', W / 2, 0.0, vis=leaf('timed'))
        if timed is not None:
            tc = self.B.centre(self.n('tt_stc'), 0.0, 0.0)
            Jt = -0.27 * p
            lab = self.text('tt_sess', Jt - S['gapT'] * p / 2, base, S['label']['cap'] * p, 'OSD_24_regular', 'right',
                            1.6 * p, (leaf('sess'), 'stri'), wrapping='none')
            clk = self.text('tt_clk', Jt + S['gapT'] * p / 2, base, S['clock']['cap'] * p, 'OSD_26_bold', 'left',
                            2.2 * p, (CLOCK_STR, 'stri'), wrapping='none')
            self.B.kids(top, self.B.kids(timed, self.B.kids(tc, lab, clk)))
        # status blocks under the band (shown only with the header): one at a time, in the DLL's order (leaves v3,
        # `hs`): chequered > red > SC > VSC > yellow. Bools only (D5: no int32 binding); nested nulls give the AND:
        # tt_nchq (not chequered) holds red, SC, VSC (the DLL never sets two of them) and, inside tt_nsc / tt_nvsc /
        # tt_nred, the yellow block. Two row slots each, chequered one; the rows below move down by the stacker.
        H_ = G['sep'] + G['band']
        sc = G['status']['sc']
        fbox = (sc['fx0'] * p, sc['fy0'] * p, (sc['fx1'] - sc['fx0']) * p, (sc['fy1'] - sc['fy0']) * p)
        chq = self.shown_null('tt_chq', 0.0, H_, vis=leaf('chq'))
        if chq is not None:
            self.B.kids(top, self.B.kids(chq, self.sprite('tt_chq_bg', 'chq', layer=LAYER['bg'])))
        under = []
        red = self.shown_null('tt_red', 0.0, H_, vis=leaf('red'))
        if red is not None:
            under.append(self.B.kids(red, self.sprite('tt_red_bg', 'red', layer=LAYER['bg'])))
        for key, sprite in (('sc', 'sc'), ('vsc', 'vsc')):
            blk = self.shown_null(f'tt_{key}', 0.0, H_, vis=leaf(key))
            if blk is not None:
                self.B.kids(blk, self.sprite(f'tt_{key}_bg', sprite, layer=LAYER['bg']),
                            self.fit(f'tt_{key}_fia', 'g_fia_k', GAME_SIZE['g_fia_k'], fbox, LAYER['mark']))
                under.append(blk)
        yel = self.yellow(H_)
        if yel is not None:
            for key in ('red', 'vsc', 'sc'):                      # innermost first
                yel = self.B.kids(self.shown_null(f'tt_n{key}', vis=leaf(key), neg=True), yel)
            under.append(yel)
        if under:
            self.B.kids(top, self.B.kids(self.shown_null('tt_nchq', vis=leaf('chq'), neg=True), *under))
        return top

    def yellow(self, y):
        """the yellow flag block (tower.js drawStatus 'yellow'): the baked YELLOW FLAG bar and dark band (sprite yel),
        and on the band the game's word (YEL_LABEL, localised) and the flagged sectors (hud_tt_ysec: "2", "1 3"), or
        the dim bar while a yellow zone has no sector (ysna). Game text styles (white): the drawing's yellow line text
        needs a colour no stock template sets on a label without a binding."""
        blk = self.shown_null('tt_yel', 0.0, y, vis=leaf('yel'))
        if blk is None:
            return None
        G, p, W = self.G, self.G['p'], self.G['w']
        cap = G['status']['hazCap'] * p
        base = p + G['mid'] + cap / 2
        em = cap / CAP_EM
        line = self.B.centre(self.n('tt_ysl'), W / 2, 0.0)
        stk = self.B.stacker(self.n('tt_ys_stk'), -YEL_TYPICAL_EM * em / 2, base, 'l', 0.28 * em)
        word = self.text('tt_ysw', 0.0, 0.0, cap, 'OSD_24_regular', 'left', 4.0 * p, ('=', YEL_LABEL, True))
        num = self.text('tt_ysn', 0.0, 0.0, cap, 'OSD_26_bold', 'left', 1.6 * p, (leaf('ysec'), 'stri'),
                        vis=leaf('ysna'), neg=True)
        na = self.quad('tt_ysna', 'na', (0.0, -cap / 2 - 0.03 * p, 0.36 * p, -cap / 2 + 0.03 * p), LAYER['mark'],
                       vis=leaf('ysna'))
        self.B.kids(stk, word, num, na)
        return self.B.kids(blk, self.sprite('tt_yel_bg', 'yel', layer=LAYER['bg']), self.B.kids(line, stk))

    def row(self, i):
        G, p, W = self.G, self.G['p'], self.G['w']
        r = f'tt_r{i:02d}'
        L = lambda k: leaf(f'r{i:02d}_{k}')   # noqa: E731
        mid = G['mid']
        row = self.shown_null(r, 0.0, i * p, vis=L('on'))
        if row is None:
            return None
        k = self.B.kids
        k(row, self.quad(r + '_s', 'strip', (0.0, 0.0, G['strip'], p), LAYER['bg']),
          self.quad(r + '_b', 'panel', (G['strip'], 0.0, W, p), LAYER['bg']))
        if i:
            k(row, self.quad(r + '_sl', 'sep', (0.0, -G['stripSepH'] / 2, G['strip'], G['stripSepH'] / 2), LAYER['hl']))
        k(row, self.quad(r + '_me', 'me', (0.0, 0.0, W, p), LAYER['hl'], vis=L('me')))
        b = G['p1']
        k(row, self.quad(r + '_p1', 'p1', (b['x'], b['y'], b['x'] + b['w'], b['y'] + b['h']), LAYER['p1'], vis=L('p1')))
        k(row, self.sprite(r + '_up', 'up', vis=L('up')), self.sprite(r + '_dn', 'dn', vis=L('dn')))
        # the position number: hidden while an arrow shows (nested groups give AND)
        pa = self.shown_null(r + '_pa', vis=L('up'), neg=True)
        pb = self.shown_null(r + '_pb', vis=L('dn'), neg=True)
        if pa is not None and pb is not None:
            k(row, k(pa, k(pb, self.text(r + '_pos', G['posX'], mid + G['posCap'] / 2, G['posCap'], 'OSD_19_regular',
                                         'centre', 0.9 * G['strip'], (L('pos'), 'stri'), wrapping='none'))))
        # the team logo (round 3): the stock logo unit, shown while teamcol and rNN_bdg (nested nulls give the AND;
        # either leaf false or absent: the slot is empty), its quad textured from rNN_badge exactly as the stock pill
        # textures it from team_badge_texture. The game's square badge is fitted to the measured slot's height
        # (badgeH 0.652 p, so it never exceeds the slot's 0.843 x 0.652 p). Round 4: centred between the bar and the
        # code (barBadgeX, 0.163 p clear on each side) and on the text middle; the editor copy has no logo, so it keeps
        # today's slot.
        lt = self.shown_null(r + '_lt', vis=leaf('teamcol'))
        lb = self.shown_null(r + '_lb', vis=L('bdg'))
        if lt is not None and lb is not None:
            assert BADGE_TAG, 'build_tower.py sets BADGE_TAG from the stock pill (stock_badge_tag)'
            el = self.n(r + '_lg')
            k(row, k(lt, k(lb, self.B.logo(el, G['barBadgeX'], mid, G['badgeH']))))
            self.bind_texture(el, L('badge'), BADGE_TAG)
        # the driver code: the game's own per-car text, one per vehicle id, shown by rNN_cVV, boxed to CODE_BOX. Live
        # tower (round 4): each car's code sits in a null 'rNN_vVV' that holds rNN_cVV, with that car's team-colour bar
        # beside it, so the bar shares the code's visibility (one new binding per car per row: its colour). Editor copy:
        # the code texts straight in the holder, no bar, as before.
        code_box = CODE_BOX * p
        n = style_n('OSD_24_bold')
        sc = (KT * G['codeCap'] / CAP_EM) / (n / 100.0)
        hx, hy = G['codeX'], mid + G['codeCap'] / 2
        holder = self.null(r + '_cn', hx, hy, scale=sc)
        # the bar: flush against the strip, centred on the text middle, in the holder's frame (scaled by sc)
        bar = G['bar']
        bar_rect = ((bar['x'] - hx) / sc, (mid - bar['h'] / 2 - hy) / sc,
                    (bar['x'] + bar['w'] - hx) / sc, (mid + bar['h'] / 2 - hy) / sc)
        for v in range(NCARS):
            sel = L(f'c{v:02d}')
            if not self.game and not self.shows(sel):
                continue
            el = self.n(f'{r}_c{v:02d}')
            if not self.game:
                t = self.B.text(el, 'OSD_24_bold', 'left', KT * code_box / sc, 'clampwidth', 'upper')
                self.pv_texts.append((el, self.pv_text[CODE.format(v=v)], False))
                k(holder, t)
                continue
            car = self.B.null(f'{r}_v{v:02d}', hidden=self.hidden(sel))
            self.bind(f'{r}_v{v:02d}', sel)
            t = self.B.text(el, 'OSD_24_bold', 'left', KT * code_box / sc, 'clampwidth', 'upper')
            self.bind(el, None, False, (CODE.format(v=v), 'stri'))
            q = self.B.quad(f'{r}_b{v:02d}', 'bar', *bar_rect, LAYER['bar'])
            self.bind_colour(f'{r}_b{v:02d}', NUB.format(v=v), 'rgba')
            k(holder, k(car, t, q))
        k(row, holder)
        # gap / interval: race and timed cells differ; the dim bar while unavailable. Every gap text box stops
        # GAP_CLEAR short of the code box (fix round 1). Race: P1's 'Interval' / 'Leader' and a retired row's 'Out' /
        # 'DSQ' / 'NC' at the drawing's label size (rNN_p1, rNN_out); every other race text at the number size
        # ('+2 LAPS' too: no leaf tells it apart). Timed: label and number sizes are the same.
        code_end = G['codeX'] + code_box
        gap = (L('gap'), 'stri')
        for key, lay, vis in (('gr', 'race', leaf('race')), ('gt', 'timed', leaf('timed'))):
            num, rx = G['num'][lay], G['num'][lay]['r']
            box = rx - code_end - GAP_CLEAR * p
            g = self.shown_null(f'{r}_{key}', vis=vis)
            if g is None:
                continue
            if lay == 'race':
                lc = G['labelCap']['race']
                qa = self.shown_null(f'{r}_{key}a', vis=L('p1'), neg=True)
                qb = self.shown_null(f'{r}_{key}b', vis=L('out'), neg=True)
                if qa is not None and qb is not None:
                    k(g, k(qa, k(qb, self.text(f'{r}_{key}x', rx, mid + num['cap'] / 2, num['cap'], 'OSD_24_regular',
                                               'right', box, gap, textcase='mixed'))))
                for sfx, v in (('l', L('p1')), ('o', L('out'))):
                    k(g, self.text(f'{r}_{key}{sfx}', rx, mid + lc / 2, lc, 'OSD_24_regular', 'right', box, gap,
                                   textcase='mixed', vis=v))
            else:
                k(g, self.text(f'{r}_{key}x', rx, mid + num['cap'] / 2, num['cap'], 'OSD_24_regular', 'right', box,
                               gap, textcase='mixed'))
            k(g, self.quad(f'{r}_{key}na', 'na', (rx - 0.36 * p, mid - 0.03 * p, rx, mid + 0.03 * p),
                           LAYER['mark'], vis=L('gna')))
            k(row, g)
        # tyre: one baked letter per compound (tyre colours), the dim bar while unavailable
        ty = self.shown_null(r + '_ty', vis=leaf('tyres'))
        if ty is not None:
            for c in 'SMHIW':
                k(ty, self.sprite(f'{r}_t{c}', 'ty_' + c, vis=L('t' + c)))
            k(ty, self.quad(r + '_tna', 'na', (G['tyreX'] - 0.12 * p, mid - 0.03 * p, G['tyreX'] + 0.12 * p,
                                               mid + 0.03 * p), LAYER['mark'], vis=L('tna')))
            k(row, ty)
        # side boxes right of the panel: '!' penalty first, then 'P' (pit lane) in the next slot
        sd = G['side']
        top = mid + sd['dy'] - sd['h'] / 2
        slot = lambda j: W + j * (sd['w'] + sd['gap'])   # noqa: E731
        k(row, self.sprite(r + '_pen', 'pen', slot(0), top, vis=L('pen')))
        q0 = self.shown_null(r + '_q0', vis=L('pen'), neg=True)
        q1 = self.shown_null(r + '_q1', vis=L('pen'))
        if q0 is not None:
            k(row, k(q0, self.sprite(r + '_pit0', 'pit', slot(0), top, vis=L('pit'))))
        if q1 is not None:
            k(row, k(q1, self.sprite(r + '_pit1', 'pit', slot(1), top, vis=L('pit'))))
        # retired / DNF / DSQ / NC: the row at about 50 % (a half-opaque layer in the row's colours over it)
        out = self.shown_null(r + '_out', vis=L('out'))
        if out is not None:
            k(out, self.quad(r + '_os', 'dims', (0.0, 0.0, G['strip'], p), LAYER['dim']),
              self.quad(r + '_op', 'dimp', (G['strip'], 0.0, W, p), LAYER['dim']))
            k(row, out)
        if self.game:
            k(row, self.debug(i))
        return row

    def debug(self, i):
        """Validation-log view (leaf dbg) under the last shown row (fix round 1; it was above the tower, over the
        game's lap counter): the DLL's dbgtxt line under row i while row i + 1 is off, left-aligned with the panel;
        with the build flag also the game's #session.dropzone on a second line. Rows never move (leaves.md 3), so
        nested groups (dbg, then not r(i+1)_on) pick the last shown row without relying on stacker bounds."""
        p = self.G['p']
        r = f'tt_r{i:02d}'
        d = self.shown_null(r + '_dbg', vis=leaf('dbg'))
        last = (self.shown_null(r + '_dbgl', vis=leaf(f'r{i + 1:02d}_on'), neg=True) if i + 1 < NROWS
                else self.null(r + '_dbgl'))
        base = p + 0.12 * p + 0.30 * p
        self.B.kids(last, self.text(r + '_dbgt', 0.0, base, 0.30 * p, 'OSD_17_regular', 'left', 12.0 * p,
                                    (leaf('dbgtxt'), 'stri'), wrapping='none', textcase='mixed'))
        if self.debug_dropzone:
            self.B.kids(last, self.text(r + '_dbgz', 0.0, base + 0.45 * p, 0.30 * p, 'OSD_17_regular', 'left',
                                        3.0 * p, (DROPZONE, 'si32'), wrapping='none'))
        return self.B.kids(d, last)

    def trial(self):
        """The Time Trial board, live tower only: tt_trial beside tt_stack, hidden by default; the HUD template
        shows it (and hides tt_stack) while hud_tt_trial. Like the standings: a stacker 't' with the header (shown with
        hdr: band, series logo, FIA badge, the line "TIME TRIAL LAP n") and the rows. Its bindings go to trecs."""
        assert self.game
        G, p, W = self.G, self.G['p'], self.G['w']
        k = self.B.kids
        saved, self.recs = self.recs, self.trecs
        try:
            root = self.B.null(TRIAL_ROOT, hidden=True)
            stack = self.B.stacker('tt_tstack', 0.0, 0.0, 't', 0.0)
            top = self.shown_null('tt_ttop', vis=leaf('hdr'))
            lg, fa = G['logo'], G['fia']
            lw = lg['h'] * GAME_SIZE['g_f1'][0] / GAME_SIZE['g_f1'][1]        # the logo box at the logo's own shape
            k(top, self.sprite('tt_thdr_bg', 'hdr', layer=LAYER['bg']),
              self.series_logo(TRIAL_SERIES_EL, GAME_SIZE['g_f1'], (TRIAL_LOGO_X, lg['y'], lw, lg['h'])),
              self.fit('tt_tfia', 'g_fia', GAME_SIZE['g_fia'], (TRIAL_LOGO_X, fa['y'], lw, fa['h']), LAYER['mark']))
            # TIME / TRIAL in the code style, centred between the logo and the right edge, the two lines centred on
            # the logo and badge column
            xc = (TRIAL_LOGO_X + lw + W) / 2
            mid_y = (lg['y'] + fa['y'] + fa['h']) / 2
            b1 = mid_y - TRIAL_LABEL_GAP / 2
            for j, word in enumerate(TRIAL_LABEL):
                k(top, self.text(f'tt_ttlab{j}', xc, b1 + j * (TRIAL_LABEL_CAP + TRIAL_LABEL_GAP), TRIAL_LABEL_CAP,
                                 'OSD_24_bold', 'centre', W - TRIAL_LOGO_X - lw - 2.0, ('=', word, False),
                                 wrapping='none'))
            # the session line: LAP and the game's lap number, in the race line's styles. While the game's lap
            # counter shows its own label instead of its lap number (hud_lap_number_visible false) the line shows
            # that label, localised as the game asks. Two complete lines, never a hidden child inside a stacker.
            S, base = G['sess'], G['sep'] + G['sessBase']
            lap = self.shown_null('tt_ttl', W / 2, 0.0, vis=LAP_VISIBLE)
            stk = self.B.stacker('tt_ttl_stk', -TRIAL_LAP / 2, base, 'l', S['gap1'] * p)
            k(stk, self.text('tt_tlapw', 0.0, 0.0, S['lapWord']['cap'] * p, 'OSD_24_regular', 'left', 1.8 * p,
                             ('=', 'lng_lap', True), wrapping='none'),
              self.text('tt_tlapn', 0.0, 0.0, S['lapNum']['cap'] * p, 'OSD_30_bold', 'left', 1.6 * p,
                        (LAP_NOW, STOCK_TT), wrapping='none'))
            desc = self.shown_null('tt_ttd', W / 2, 0.0, vis=LAP_VISIBLE, neg=True)
            k(desc, self.text('tt_tdesc', 0.0, base, S['label']['cap'] * p, 'OSD_24_regular', 'centre', W - 6.0,
                              ('@loc', LAP_DESC, LAP_DESC_LOC)))
            k(top, k(lap, k(self.B.centre('tt_ttl_c', 0.0, 0.0), stk)), desc)
            rows = self.null('tt_trows', 0.0, G['sep'] + G['band'])   # where the stacker puts it under the header
            k(rows, *[self.trial_row(i) for i in range(NPILLS)])
            return k(root, k(stack, top, rows))
        finally:
            self.recs = saved

    def trial_row(self, i):
        """One Time Trial row from the game's pill_i, in the standings row's style: strip, panel, the player's highlight,
        position, team-colour bar, team logo, name, gap cell and tyre. Shown while the game's pill is active (the stock
        decision on pill_i.active). The gap cell, while Intervals is on (ints, as the standings rows): the game's gap
        text while the stock pill would open its time cell (show_text_label 1), with the name in the code column's
        box; else the dim bar and the long name box. Intervals off: no gap cell, always the long name box."""
        G, p, W, mid = self.G, self.G['p'], self.G['w'], self.G['mid']
        r = f'tt_q{i:02d}'
        P_ = lambda leaf_: PILL.format(i=i, leaf=leaf_)   # noqa: E731
        k = self.B.kids
        row = self.switched(r, (TRIAL_ACTIVE.format(i=i), P_('active')), {'0': False, '1': True}, False, 0.0, i * p)
        k(row, self.quad(r + '_s', 'strip', (0.0, 0.0, G['strip'], p), LAYER['bg']),
          self.quad(r + '_b', 'panel', (G['strip'], 0.0, W, p), LAYER['bg']))
        if i:
            k(row, self.quad(r + '_sl', 'sep', (0.0, -G['stripSepH'] / 2, G['strip'], G['stripSepH'] / 2), LAYER['hl']))
        k(row, k(self.shown_null(r + '_h', vis=leaf('hl')),
                 self.quad(r + '_me', 'me', (0.0, 0.0, W, p), LAYER['hl'], vis=P_('is_current_car'))))
        k(row, self.text(r + '_pos', G['posX'], mid + G['posCap'] / 2, G['posCap'], 'OSD_19_regular', 'centre',
                         0.9 * G['strip'], (P_('pos_name'), STOCK_TT), wrapping='none'))
        bar = G['bar']
        k(row, self.B.quad(r + '_bar', 'bar', bar['x'], mid - bar['h'] / 2, bar['x'] + bar['w'], mid + bar['h'] / 2,
                           LAYER['bar']))
        self.bind_colour(r + '_bar', P_('nub_colour'), STOCK_TT)
        k(row, k(self.shown_null(r + '_lt', vis=leaf('teamcol')),
                 self.B.logo(r + '_lg', G['barBadgeX'], mid, G['badgeH'])))
        self.bind_texture(r + '_lg', P_('team_badge_texture'), STOCK_TT)
        num = G['num']['timed']
        rx = num['r']
        na0 = rx - 0.36 * p
        gsh = (f'pill_{i}.{TRIAL_GAPSHOW}', P_(TRIAL_GAPSHOW))
        name = lambda el, box: self.text(el, G['codeX'], mid + G['codeCap'] / 2, G['codeCap'], 'OSD_24_bold',  # noqa: E731
                                         'left', box, (P_('driver_name'), STOCK_TT))
        long_box = na0 - GAP_CLEAR * p - G['codeX']
        # the long name: while the pill has no time cell open (_nl), or beside an open one while Intervals is off (_nm)
        k(row, k(self.switched(r + '_nl', gsh, {'0': True, '1': False}, True), name(r + '_nlt', long_box)))
        k(row, k(self.shown_null(r + '_ni', vis=leaf('ints'), neg=True),
                 k(self.switched(r + '_nm', gsh, {'0': False, '1': True}, False), name(r + '_nmt', long_box))))
        code_end = G['codeX'] + CODE_BOX * p
        k(row, k(self.shown_null(r + '_gi', vis=leaf('ints')),
                 k(self.switched(r + '_ns', gsh, {'0': False, '1': True}, False), name(r + '_nst', CODE_BOX * p)),
                 k(self.switched(r + '_gx', gsh, {'0': False, '1': True}, False),
                   self.text(r + '_gxt', rx, mid + num['cap'] / 2, num['cap'], 'OSD_24_regular', 'right',
                             rx - code_end - GAP_CLEAR * p, (P_('gap_text'), STOCK_TT), textcase='mixed')),
                 k(self.switched(r + '_gna', gsh, {'0': True, '1': False}, True),
                   self.quad(r + '_na', 'na', (na0, mid - 0.03 * p, rx, mid + 0.03 * p), LAYER['mark']))))
        k(row, k(self.shown_null(r + '_ty', vis=leaf('tyres')),
                 k(self.shown_null(r + '_ts', vis=P_('show_tyres')), self.B.logo(r + '_tc', G['tyreX'], mid, TRIAL_TYRE * p))))
        self.bind_texture(r + '_tc', P_('tyre_compound'), STOCK_TT)
        return row

    def build(self):
        """game: the root null tt_root (hidden by default; the template shows it in tt_host), with the standings
        (tt_stack) and the Time Trial board (tt_trial). preview: tp_root, the HUD editor's copy (shown by default;
        static template nodes hide it in game)."""
        G = self.G
        root = self.B.null(ROOT if self.game else PV_ROOT, hidden=self.game)
        stack = self.B.stacker(self.n('tt_stack'), 0.0, 0.0, 't', 0.0)
        rows = self.null('tt_rows', 0.0, G['sep'] + G['band'])     # stored where the stacker puts it (header, no block)
        self.B.kids(rows, *[self.row(i) for i in range(NROWS)])
        self.B.kids(stack, self.header(), rows)
        return self.B.kids(root, stack, self.trial() if self.game else None)


GAME_SIZE = {}   # game texture pixel sizes, filled by build_tower.py from the game's own surfaces
BADGE_TAG = None  # the stock pill's textureOverride tag for team_badge_texture, set by build_tower.py (stock_badge_tag)
SERIES_TAG = None  # the stock lap counter's textureOverride tag for logo_texture, set by build_tower.py (stock_series_tag)


def preview_state():
    """The HUD editor's preview (no template runs there): compact, 5 rows, race header, the player on the middle row.
    Placeholder codes, never real driver data. -> (bool leaves, texts by binding)"""
    on = {leaf(k): True for k in ('on', 'hdr', 'race', 'tyres')}
    texts = {leaf('lap'): '10', LAPS: '71'}
    rows = [('10', 'M', '+1.2'), ('11', 'M', '+0.9'), ('12', 'S', '+0.5'), ('13', 'M', '+1.4'), ('14', 'H', '+0.7')]
    for i, (pos, tyre, gap) in enumerate(rows):
        r = f'r{i:02d}_'
        on[leaf(r + 'on')] = True
        on[leaf(f'{r}c{i:02d}')] = True
        on[leaf(r + 't' + tyre)] = True
        texts[leaf(r + 'pos')] = pos
        texts[leaf(r + 'gap')] = gap
        texts[CODE.format(v=i)] = 'DRV'
    on[leaf('r02_me')] = True
    return on, texts


def _ids_and_check(idf, entry, stock_ids, new_names):
    ids = []
    for kid in entry['scene']['children'].items:
        I.recompute_ids(kid, I._val(kid.get('name')), ids)
    I.relookup(entry)
    after = {e.path: e.element_id for e, _ in I.Idf(idf.to_bytes()).scenes[0].root.walk()}
    changed = [k for k, v in stock_ids.items() if after.get(k) != v]
    assert not changed, ('stock element ids changed', changed[:5])
    assert len(set(ids)) == len(ids), 'elementId collision'
    names = [I._val(e.obj.get('name')) for e, _ in I.Idf(idf.to_bytes()).scenes[0].root.walk()]
    dup = {x for x in names if names.count(x) > 1}
    assert not (dup & set(new_names)), ('element name reused', sorted(dup & set(new_names))[:5])


def build_cap(cap_bytes, dial_bytes, lapc_bytes, stacked_bytes, embs, meta, row_bytes, logo_bytes, cat_bytes,
              debug_dropzone=False):
    """the bottom cap scene with the live tower (tt_root) and the HUD editor's copy (tp_root)
    -> (bytes, live Tower, preview Tower)"""
    B = Scene(cap_bytes, dial_bytes, lapc_bytes, stacked_bytes, embs, row_bytes, logo_bytes, cat_bytes)
    stock_ids = {e.path: e.element_id for e, _ in B.idf.scenes[0].root.walk()}
    T = Tower(B, meta, preview_state(), debug_dropzone)
    B.root['children'].items.append(T.build())
    PV = Tower(B, meta, preview_state(), mode='preview')
    B.root['children'].items.append(PV.build())
    assert not any(B.hidden[nm] for nm in B.names if nm.startswith('tp_')), 'the editor copy hides nothing'
    assert not any(nm.startswith('tp_') for rec in T.recs + T.trecs for nm in [rec['el']]), 'the editor copy is never bound'
    _ids_and_check(B.idf, B.entry, stock_ids, B.names)
    walked = [e for e, _ in I.Idf(B.idf.to_bytes()).scenes[0].root.walk()]
    tnames = {e.name for e in walked if e.path == f'{ROOT}.{TRIAL_ROOT}' or e.path.startswith(f'{ROOT}.{TRIAL_ROOT}.')}
    assert not any(rec['el'] in tnames for rec in T.recs), 'a Time Trial element among the standings recs'
    assert all(rec['el'] in tnames for rec in T.trecs), 'a Time Trial rec outside tt_trial'
    xrefs = [e for e in walked if e.type == 'eXRef']
    rows = [e for e in xrefs if e.name.startswith('tt_r') and e.name.endswith('_lg')]
    head = [e for e in xrefs if e.name == SERIES_EL]
    trial = [e for e in xrefs if e.path.startswith(f'{ROOT}.{TRIAL_ROOT}.')]
    assert len(rows) + len(head) + len(trial) == len(xrefs), 'only the live rows, header and Time Trial board hold logos'
    assert len(rows) == NROWS and len(head) == 1 and all(e.xref_ok() for e in xrefs), ('logo references', len(xrefs))
    assert all(e.file_ref == LOGO for e in rows) and head[0].file_ref == CAT_LOGO, 'logo reference files'
    assert head[0].path == f'{ROOT}.tt_stack.tt_top.{SERIES_EL}', ('the series logo sits in the header', head[0].path)
    # the Time Trial board: its series logo, and per row a team logo and a tyre icon (the stock logo unit)
    tl = [e for e in trial if e.name == TRIAL_SERIES_EL]
    tg = [e for e in trial if e.name.startswith('tt_q') and e.name.endswith('_lg')]
    tc = [e for e in trial if e.name.startswith('tt_q') and e.name.endswith('_tc')]
    assert len(tl) == 1 and len(tg) == len(tc) == NPILLS and len(trial) == 1 + 2 * NPILLS, ('Time Trial references', len(trial))
    assert tl[0].file_ref == CAT_LOGO and all(e.file_ref == LOGO for e in tg + tc), 'Time Trial reference files'
    assert tl[0].path == f'{ROOT}.{TRIAL_ROOT}.tt_tstack.tt_ttop.{TRIAL_SERIES_EL}', ('Time Trial series logo', tl[0].path)
    return B.idf.to_bytes(), T, PV


def build_stacked(stacked_bytes):
    """the stacked table with a second bottom cap instance, 'tt_host', at the table's top-left"""
    idf = I.Idf(stacked_bytes)
    entry = idf.scenes[0].entry
    root = entry['scene']
    assert idf.scenes[0].name == I.component_id(STACKED)
    stock_ids = {e.path: e.element_id for e, _ in idf.scenes[0].root.walk()}
    cap = H._find(root, 'driver_position_bottom_cap')
    assert I.get_param(cap, 'fileRef') == CAP and cap['xref'].value == I.component_id(CAP)
    assert H._find(root, HOST) is None and H._find(root, MASK) is not None
    host = I.clone_node(cap)
    host.set('name', Val('stri', HOST))
    H._param(host, 'guid', H._guid(HOST))
    host.set('position', H._vec((0.0, 0.0, 0.0)))
    root['children'].items.append(host)
    _ids_and_check(idf, entry, stock_ids, [HOST])
    return idf.to_bytes()


# ---------------------------------------------------------------- editor preview (.uipre)
def build_uipre(uipre_bytes, texts):
    """The table's editor preview: the stock table ('mask') hidden; in tt_host the cap graphics and the live tower
    (tt_root) hidden, the editor copy (tp_root) shown and its texts filled in. Element ids are djb2 of leaf names,
    nested per instance (as the stock rows). In game 2026-11-09 the editor applied both kinds of nested setter:
    D's texts showed and the cap graphics stayed hidden."""
    p = Pkg(uipre_bytes)
    assert p.root['TargetId'].value == I.component_id(STACKED)
    els = p.root['Elements']

    def nested():
        for top in els.items:
            for el in (top.get('Elements').items if top.get('Elements') is not None else []):
                yield top, el

    def setter(key, vtype, value):
        for _top, el in nested():
            for st in (el.get('Setters').items if el.get('Setters') is not None else []):
                if st['Key'].value == key and st['Value'].type == vtype:
                    s = I.clone_node(st)
                    s['Value'].value = value
                    return s
        raise KeyError(f'no stock setter {key} {vtype}')

    def element(name, setters):
        _top, model = next(nested())
        el = I.clone_node(model)
        el['Id'].value = N.djb2(name)
        el['Setters'].items = list(setters)
        return el

    have = {top['Id'].value for top in els.items}
    assert N.djb2(MASK) not in have and N.djb2(HOST) not in have, 'preview already built'
    els.items.append(element(MASK, [setter(UIPRE_VISIBLE, 'bool', False)]))
    host = I.clone_node(els.items[0])
    host['Id'].value = N.djb2(HOST)
    kids = [element('pill_rotation_anim', [setter(UIPRE_VISIBLE, 'bool', False)]),
            element(ROOT, [setter(UIPRE_VISIBLE, 'bool', False)]),
            element(PV_ROOT, [setter(UIPRE_VISIBLE, 'bool', True)])]
    assert all(el.startswith('tp_') for el, _t, _l in texts), "the editor fills only its copy's texts"
    for el, txt, loc in texts:
        kids.append(element(el, [setter(UIPRE_LOC if loc else UIPRE_TEXT, 'stri', txt)]))
    ids = [k['Id'].value for k in kids]
    assert len(set(ids)) == len(ids), 'preview element id reused'
    host['Elements'].items = kids
    els.items.append(host)
    return p.to_bytes(), len(kids) + 1


# ---------------------------------------------------------------- template
def _stock_types(stock_root):
    types = {}
    for _n, _k, t, db in H._bindings(stock_root, []):
        types.setdefault(db, set()).add(t)
    return types


def binding_type(db, contract, stock):
    """the type a binding to db must have: the contract's for DLL leaves, the stock template's or KNOWN_TYPES' for
    game values (per-car paths checked as the current car's)"""
    if db.startswith(VM):
        return {contract[db]} if db in contract else None
    key = re.sub(r'#session\.cars\.car\d+\.', '#session.current_car.', db)
    if key in stock:
        return stock[key]
    return {KNOWN_TYPES[key]} if key in KNOWN_TYPES else None


def _find_node(root, name):
    found = []

    def walk(x, trail):
        if N.is_node(x):
            t = trail + [N.name(x)]
            if N.name(x) == name:
                found.append(('.'.join(t), x))
            for c in N.children(x):
                walk(c, t)
        elif isinstance(x, Arr):
            for c in x.items:
                walk(c, trail)
        elif isinstance(x, Obj):
            for _k, v in x.items:
                walk(v, trail)

    walk(root, [])
    return found


def _default(tag):
    return {'stri': '', 'si32': 0, 'ui32': 1, 'bool': False}[tag]


def stock_badge_tag(stock_ui_bytes):
    """The stock pill's badge binding, checked on all five pills: node team_badge_image, layout path
    team_logo > team_logo (the row's eXRef, then the unit's quad), property textureOverride bound to the pill leaf
    team_badge_texture. -> the property's type tag (the tower binds its badge leaf with exactly this tag)."""
    p = Pkg(stock_ui_bytes)
    node, prop, db = STOCK_BADGE
    tags = set()
    for row in STOCK_PILL_ROWS:
        n = H._node_at(p.root, f'{STOCK_PILLS}.{row}.{node}')
        lay = [[b['debugName'].value for b in grp.items] for grp in n.items[N.LAYOUT].items]
        assert lay == [[LOGO_XREF, LOGO_QUAD]], ('stock badge layout', row, lay)
        pr = n.items[N.PROPS].get(prop)
        assert pr is not None and pr.get('dbentry') is not None and pr['dbentry'].value == db, ('stock badge', row)
        assert pr.get('dbentrynegate') is None
        tags.add(pr['value'].type)
    assert len(tags) == 1, ('stock badge tags differ', tags)
    return tags.pop()


def stock_series_tag(stock_ui_bytes):
    """The stock lap counter's logo binding (round 6): node hud_lap_counter.osd_visibility_option.logo, layout path
    car_category_logo > logo_icon (the lap counter scene's reference, then the unit's quad), property textureOverride
    bound to logo_texture of the lap counter's view model (relative), not negated, the only stock node binding that
    leaf. -> the property's type tag (the header's series logo binds HUD_SERIES with exactly this tag)."""
    p = Pkg(stock_ui_bytes)
    node, prop, db = STOCK_SERIES
    n = H._node_at(p.root, node)
    lay = [[b['debugName'].value for b in grp.items] for grp in n.items[N.LAYOUT].items]
    assert lay == [[CAT_XREF, CAT_QUAD]], ('stock lap counter logo layout', lay)
    pr = n.items[N.PROPS].get(prop)
    assert pr is not None and pr.get('dbentry') is not None and pr['dbentry'].value == db, 'stock lap counter logo'
    assert pr.get('dbentrynegate') is None
    users = [nm for nm, _k, _t, d in H._bindings(H._node_at(p.root, LAPC_TEMPLATE.split('.')[0]), []) if d == db]
    assert len(users) == 1, ('stock nodes binding', db, users)
    return pr['value'].type


def lap_counter_nodes():
    """hud_lap_counter: one group 'tt_lapc' whose children hide LAPC_HIDE while hud_tt_show is true (the standings or
    the Time Trial board, whose header carries the lap line; visible = NOT show; true while the leaf is
    absent, so the counter is the game's own whenever the tower is off or the DLL is missing)"""
    kids = [U.node('v_tt_lapc_' + el, 'UIGP', [('visible', H._bool_prop(True, leaf('show'), True))], layout=[el],
                   behav=U.GROUP_BEHAVIOURS) for el in LAPC_HIDE]
    return U.node('tt_lapc', 'UIGP', [], kids=kids, behav=U.GROUP_BEHAVIOURS)


def check_lap_counter(lapc_bytes, stock_ui_bytes):
    """The lap counter parts the tower hides must be the stock scene's own, shown by default, and never shown or
    hidden by a stock node (a second visible binding on one element would fight the game's)."""
    idf = I.Idf(lapc_bytes)
    top = [I._val(c.get('name')) for c in idf.scenes[0].entry['scene']['children'].items]
    assert sorted(top) == sorted(LAPC_STOCK_KIDS), ('lap counter scene changed', top)
    els = {e.name: e for e, _ in idf.scenes[0].root.walk()}
    for nm in LAPC_HIDE:
        assert nm in els, ('no lap counter element', nm)
        assert not I.get_param(els[nm].obj, 'isHidden'), ('hidden by default', nm)
        assert sum(1 for x in els if x == nm) == 1
    names = [e.name for e, _ in idf.scenes[0].root.walk()]
    assert all(names.count(nm) == 1 for nm in LAPC_HIDE), 'a hidden part name is not unique'
    p = Pkg(stock_ui_bytes)
    root = H._node_at(p.root, LAPC_TEMPLATE)
    fights = []

    def walk(n):
        for path in n.items[N.LAYOUT].items:
            last = path.items[-1]['debugName'].value if path.items else ''
            if last in LAPC_HIDE and n.items[N.PROPS].get('visible') is not None:
                fights.append((N.name(n), last))
        for c in N.children(n):
            walk(c)
    walk(root)
    assert not fights, ('stock nodes show or hide these lap counter parts', fights)
    return len(LAPC_HIDE)


def tower_nodes(T, stock, badge_tag, root_visible=None, series=None):
    """The nodes under tt_host_n, the same for the HUD and the replay screen: the cap's own graphics hidden, tt_root
    shown (root_visible: its visible prop; the HUD's is a constant true), the editor copy hidden, then one node per
    bound tower element (T.recs). series: (the screen's logo_texture leaf, the tag its stock node binds it with) for
    the header's series logo."""
    nodes = [U.node('v_tt_cap', 'UIGP', [('visible', U.prop('bool', False))], layout=['pill_rotation_anim'],
                    behav=U.GROUP_BEHAVIOURS),
             U.node('v_tt_root', 'UIGP', [('visible', root_visible if root_visible is not None else U.prop('bool', True))],
                    layout=[ROOT], behav=U.GROUP_BEHAVIOURS),
             # the HUD editor's copy never shows in game (static, as the halo's halo_pv control)
             U.hidden('v_tp_root', PV_ROOT)]
    for rec in T.recs:
        el, vis, text = rec['el'], rec['vis'], rec['text']
        if rec.get('col'):
            # the team-colour bar: colourOverride on the quad, as the stock pill's team_colour node and the halo's
            # colour nodes (UIGP); transparent while the game's value is absent (BAR_DEFAULT)
            db, tag = rec['col']
            assert not vis and text is None
            nodes.append(U.node('c_' + el, 'UIGP', [('colourOverride', U.prop(tag, BAR_DEFAULT, db))],
                                layout=[el], behav=U.GROUP_BEHAVIOURS))
            continue
        if rec.get('tex'):
            # the team logo: the stock pill's team_badge_image node (textureOverride on eXRef > quad), the stock tag;
            # the series logo (round 6): the stock lap counter's logo node, the same shape, on the screen's own leaf
            db, tag = rec['tex']
            if db == SERIES:
                if series is None:
                    raise SystemExit(f'{el}: a series logo, but no logo_texture leaf for this screen')
                db, want = series
                if tag != want:
                    raise SystemExit(f'{el}: series logo bound as {tag}, the stock lap counter binds logo_texture as {want}')
                assert rec['sub'] == CAT_QUAD and STOCK_SERIES[1] == STOCK_BADGE[1]
            elif tag != badge_tag:
                raise SystemExit(f'{el}: badge bound as {tag}, the stock pill binds team_badge_texture as {badge_tag}')
            assert not vis and text is None
            nodes.append(U.node('x_' + el, 'UIGP', [(STOCK_BADGE[1], U.prop(tag, rec.get('default', _default(tag)), db))],
                                layout=[el, rec['sub']], behav=U.GROUP_BEHAVIOURS))
            continue
        props = []
        if vis:
            db, neg = vis
            props.append(('visible', H._bool_prop(neg, db, neg)))    # while the leaf is absent: as if false
        if text is None:
            nodes.append(U.node('v_' + el, 'UIGP', props, layout=[el], behav=U.GROUP_BEHAVIOURS))
            continue
        if text[0] == '=':
            props += [('localise', U.prop('bool', text[2])), ('text', U.prop('stri', text[1]))]
        else:
            db, tag = text
            if tag == 'laps':       # the game's total laps: the stock lap counter's own binding type
                (tag,) = stock[LAPS]
            props.append(('text', U.prop(tag, _default(tag), db)))
        nodes.append(U.node('t_' + el, 'UILB', props, layout=[el], behav=U.LABEL_BEHAVIOURS))
    return nodes


def _events(n):
    return {e['eventName'].value for e in n.items[N.EVENTS].items if isinstance(e, Obj)}


def _mvcd(parent, db):
    """the one MVCD child of a template node that reads db (a stock pill reads 'active' twice: not used here)"""
    found = [c for c in N.children(parent) if N.is_node(c) and H._type(c) == 'MVCD'
             and c.items[N.PROPS]['dbEntry']['value'].value == db]
    assert len(found) == 1, ('stock MVCDs on', db, 'under', N.name(parent), len(found))
    return found[0]


def stock_trial(stock_ui_bytes):
    """What the Time Trial board reads, from the stock template. On all five pills of Track Position (dataContext
    pill_0 ... pill_4, in STOCK_PILL_ROWS order): each TRIAL_PILL leaf bound by the same node and property, not negated,
    one tag on all five; Track Position's own MVCD on pill_i.active and each pill's MVCD on show_text_label (their event
    names); the lap counter's lap number (lap_value: text <- current_car_path.lap).
    -> ({absolute value path: {tag}}, {decision value as read from tt_ctl: stock event names})"""
    p = Pkg(stock_ui_bytes)
    types, decisions = {}, {}
    top = H._node_at(p.root, STOCK_PILLS)
    for i, row in enumerate(STOCK_PILL_ROWS):
        pill = H._node_at(p.root, f'{STOCK_PILLS}.{row}')
        dc = pill.items[N.PROPS].get('dataContext')
        assert dc is not None and dc.get('dbentry') is not None and dc['dbentry'].value == f'pill_{i}', (row, 'dataContext')
        for lf, (sub, prop) in TRIAL_PILL.items():
            pr = H._node_at(p.root, f'{STOCK_PILLS}.{row}.{sub}').items[N.PROPS].get(prop)
            assert pr is not None and pr.get('dbentry') is not None and pr['dbentry'].value == lf, ('stock pill', row, sub, prop)
            assert pr.get('dbentrynegate') is None, ('stock pill', row, sub, prop, 'negated')
            types[PILL.format(i=i, leaf=lf)] = {pr['value'].type}
        act = TRIAL_ACTIVE.format(i=i)
        decisions[act] = _events(_mvcd(top, act))
        decisions[f'pill_{i}.{TRIAL_GAPSHOW}'] = _events(_mvcd(pill, TRIAL_GAPSHOW))
    for lf in TRIAL_PILL:
        tags = set().union(*(types[PILL.format(i=i, leaf=lf)] for i in range(NPILLS)))
        assert len(tags) == 1, ('the stock pills bind', lf, 'as', tags)
    node, prop, db = LAP_NOW_STOCK
    pr = H._node_at(p.root, node).items[N.PROPS].get(prop)
    assert pr is not None and pr.get('dbentry') is not None and pr['dbentry'].value == db, 'stock lap counter lap_value'
    types[LAP_NOW] = {pr['value'].type}
    return types, decisions


def _stock_tag(db, tag, stock):
    """a Time Trial rec's tag: STOCK_TT -> the one tag the stock template binds db with"""
    if tag != STOCK_TT:
        return tag
    tags = stock.get(db)
    if not tags or len(tags) != 1:
        raise SystemExit(f'{db}: the stock template binds it as {tags}, not one tag')
    return next(iter(tags))


def trial_nodes(T, stock, base, series_tag):
    """The Time Trial board's template nodes, from T.trecs: one node per bound element under tt_host_n (as
    tower_nodes, plus a static-visible node per decision-switched null), the decision nodes (MVCD, the stock form: one
    per value, events '0' / '1' showing and hiding the switched nodes) and tt_ctl's commands: trigger registers and
    queries every decision node, untrigger unregisters them (the halo's pattern, proven in game).
    base: tt_ctl's path. -> (host nodes, decision nodes, commands, {value: {event: [(node path, pin)]}})"""
    nodes, switches = [], {}
    host = f'{base}.tt_host_n'
    for rec in T.trecs:
        el, vis, text = rec['el'], rec['vis'], rec['text']
        if rec.get('sw'):
            rel, _abs, states = rec['sw']
            nodes.append(U.node('v_' + el, 'UIGP', [('visible', U.prop('bool', rec['init']))], layout=[el],
                                behav=U.GROUP_BEHAVIOURS))
            ev = switches.setdefault(rel, {'0': [], '1': []})
            for state, shown in states.items():
                ev[state].append((f'{host}.v_{el}', 'show' if shown else 'hide'))
            continue
        if rec.get('col'):
            db, tag = rec['col']
            nodes.append(U.node('c_' + el, 'UIGP', [('colourOverride', U.prop(_stock_tag(db, tag, stock), BAR_DEFAULT, db))],
                                layout=[el], behav=U.GROUP_BEHAVIOURS))
            continue
        if rec.get('tex'):
            db, tag = rec['tex']
            default = rec.get('default')
            if db == SERIES:
                db, tag = HUD_SERIES, series_tag
                assert rec['sub'] == CAT_QUAD and rec['tex'][1] == series_tag
            else:
                tag = _stock_tag(db, tag, stock)
                assert rec['sub'] == LOGO_QUAD
            nodes.append(U.node('x_' + el, 'UIGP', [(STOCK_BADGE[1], U.prop(tag, default if default is not None else
                                                                            _default(tag), db))],
                                layout=[el, rec['sub']], behav=U.GROUP_BEHAVIOURS))
            continue
        props = []
        if vis:
            db, neg = vis
            props.append(('visible', H._bool_prop(neg, db, neg)))    # while the value is absent: as if false
        if text is None:
            nodes.append(U.node('v_' + el, 'UIGP', props, layout=[el], behav=U.GROUP_BEHAVIOURS))
            continue
        if text[0] == '=':
            props += [('localise', U.prop('bool', text[2])), ('text', U.prop('stri', text[1]))]
        elif text[0] == '@loc':
            # the game's own lap label, localised when the game says so (the stock specialised_lap_holder's label)
            props += [('localise', U.prop('bool', False, text[2])), ('text', U.prop('stri', '', text[1]))]
        else:
            db, tag = text
            tag = _stock_tag(db, tag, stock)
            props.append(('text', U.prop(tag, _default(tag), db)))
        nodes.append(U.node('t_' + el, 'UILB', props, layout=[el], behav=U.LABEL_BEHAVIOURS))
    decisions, trig, untrig = [], [], []
    for rel, ev in switches.items():
        name = 'tt_mv_' + rel.replace('.', '_')
        evs = [U.event(s, [U.sig(path, pin, s) for path, pin in ev[s]]) for s in ('0', '1')]
        decisions.append(U.node(name, 'MVCD', [('dbEntry', U.prop('stri', rel))], events=evs))
        path = f'{base}.{name}'
        trig += [U.sig(path, 'register', 'trigger'), U.sig(path, 'query', 'trigger')]
        untrig.append(U.sig(path, 'unregister', 'untrigger'))
    return nodes, decisions, [U.command('trigger', trig), U.command('untrigger', untrig)], switches


def clock_formatter(ui_root):
    """the session clock: the stock session timer's formatter (hud_dynamic_templates.ui), cloned as tt_clock_fmt (it
    writes time_remaining_str, which the timed header's clock text reads)"""
    fmt = [x for path, x in _find_node(ui_root, 'time_remaining_formatter') if path.startswith(CLOCK_MODEL + '.')]
    assert len(fmt) == 1, len(fmt)
    clock = I.clone_node(fmt[0])
    clock.items[N.PROPS]['name'].value = 'tt_clock_fmt'
    return clock


def build_template(ui_bytes, stock_ui_bytes, T, contract):
    """hud_dynamic_templates.ui (the halo's build, from erp/halo_template.erp) plus the tower's nodes.
    -> (bytes, node count, [(dbentry, tag)] every tower binding)"""
    p = Pkg(ui_bytes)
    stock = _stock_types(Pkg(stock_ui_bytes).root)
    badge_tag = stock_badge_tag(stock_ui_bytes)
    # the series logo: the stock lap counter binds logo_texture relative to its view model; the tower binds the same
    # leaf by its absolute path (HUD_SERIES, check_hud_layouts), so that path carries the stock node's tag
    series_tag = stock_series_tag(stock_ui_bytes)
    assert HUD_SERIES not in stock, 'a stock node binds the lap counter logo by its absolute path'
    stock[HUD_SERIES] = {series_tag}
    # the Time Trial board: the stock pills' and lap counter's values by their absolute paths (the stock binds
    # them relative to its pills and its lap counter), each with the stock tag
    ttypes, tdecisions = stock_trial(stock_ui_bytes)
    assert not set(ttypes) & set(stock), 'a stock node binds a pill value by its absolute path'
    stock.update(ttypes)
    target = H._node_at(p.root, TEMPLATE_PARENT)
    assert not any(N.name(c) == CTL for c in N.children(target)), 'template already has the tower'
    base = f'{TEMPLATE_PARENT}.{CTL}'
    nodes = tower_nodes(T, stock, badge_tag, series=(HUD_SERIES, series_tag))
    tnodes, decisions, cmds, switches = trial_nodes(T, stock, base, series_tag)
    check_trial_decisions(switches, tdecisions)
    clock = clock_formatter(p.root)
    # the standings (tt_stack) hide and the Time Trial board (tt_trial) shows while hud_tt_trial; absent: standings
    switch = [U.node('v_tt_stack', 'UIGP', [('visible', H._bool_prop(True, leaf('trial'), True))], layout=['tt_stack'],
                     behav=U.GROUP_BEHAVIOURS),
              U.node('v_' + TRIAL_ROOT, 'UIGP', [('visible', H._bool_prop(False, leaf('trial')))], layout=[TRIAL_ROOT],
                     behav=U.GROUP_BEHAVIOURS)]
    host = U.node('tt_host_n', 'UIGP', [('visible', H._bool_prop(False, leaf('show')))], kids=nodes + switch + tnodes,
                  layout=[HOST], behav=U.GROUP_BEHAVIOURS)
    mask = U.node('tt_mask', 'UIGP', [('visible', H._bool_prop(True, leaf('show'), True))], layout=[MASK],
                  behav=U.GROUP_BEHAVIOURS)
    ctl = U.node(CTL, 'UIGP', [], kids=[mask, host, clock] + decisions, behav=U.GROUP_BEHAVIOURS)
    ctl.items[N.COMMANDS].items.extend(cmds)
    # the stock cap instance never shows the tower (its root is hidden by default; this makes it explicit in game)
    # nor the editor's copy (shown by default: only these static nodes hide it in game)
    cap_off = [U.hidden('tt_cap_off', ROOT), U.hidden('tp_cap_off', PV_ROOT)]
    # the game's lap counter: hidden while the tower shows, back as the game has it while hud_tt_on is false or absent
    lapc = lap_counter_nodes()

    # every binding's type must be the type of the value it reads: a mismatch crashes the game
    bad, out = [], []
    for node, prop, t, db in (H._bindings(ctl, []) + [b for c in cap_off for b in H._bindings(c, [])] +
                              H._bindings(lapc, [])):
        want = binding_type(db, contract, stock)
        if not want:
            bad.append(f'{node}.{prop} <- {db}: type unknown (not in the contract, no stock binding, not in KNOWN_TYPES)')
        elif t not in want:
            bad.append(f'{node}.{prop} <- {db}: {t}, the value is {"/".join(sorted(want))}')
        out.append((db, t))
    if bad:
        raise SystemExit('tower binding types:\n  ' + '\n  '.join(bad))
    N.fix_ids(ctl, TEMPLATE_PARENT)
    target.items[N.CHILDREN].items.append(ctl)
    # Track Position's enable registers and queries the board's decision nodes (through tt_ctl's trigger), its
    # disable unregisters them: beside the stock pills' own decisions, as the halo's [F1HD] show / hide trigger halo_ctl
    for cmd, pin in (('enable', 'trigger'), ('disable', 'untrigger')):
        c = [x for x in target.items[N.COMMANDS].items if isinstance(x, Obj) and x['commandName'].value == cmd]
        assert len(c) == 1, (TEMPLATE_PARENT, cmd, len(c))
        assert not any(s['to_object_name'].value == base for s in c[0]['signals'].items), 'tt_ctl already triggered'
        c[0]['signals'].items.append(U.sig(base, pin, cmd))
    cap_node = H._node_at(p.root, STOCK_CAP_NODE)
    assert not N.children(cap_node), 'the stock bottom_cap node has children'
    for c in cap_off:
        N.fix_ids(c, STOCK_CAP_NODE)
        cap_node.items[N.CHILDREN].items.append(c)
    lapc_node = H._node_at(p.root, LAPC_TEMPLATE)
    assert not any(N.name(c) == N.name(lapc) for c in N.children(lapc_node)), 'lap counter already has the tower node'
    N.fix_ids(lapc, LAPC_TEMPLATE)
    lapc_node.items[N.CHILDREN].items.append(lapc)
    # read back: the board's nodes and decisions where the signals say, every signal target a node of tt_ctl
    data = p.to_bytes()
    got = H._node_at(Pkg(data).root, base)
    paths = {}

    def walk(n, path):
        paths[path] = n
        for c in N.children(n):
            if N.is_node(c):
                walk(c, f'{path}.{N.name(c)}')
    walk(got, base)
    for ev in switches.values():
        for sigs in ev.values():
            assert all(path in paths for path, _pin in sigs), 'a decision signal without its node'
    assert len(decisions) == len(switches) == 2 * NPILLS, ('Time Trial decision nodes', len(decisions))
    T.trial_info = {'nodes': len(tnodes) + len(switch), 'decisions': len(decisions),
                    'signals': sum(len(s) for ev in switches.values() for s in ev.values()),
                    'values': sorted(switches)}
    return data, len(nodes) + len(switch) + len(tnodes) + len(decisions) + 5 + len(N.children(lapc)) + 1, out


def check_trial_decisions(switches, stock):
    """Each Time Trial decision node reads a value a stock decision node reads (Track Position's pill_i.active, or a
    pill's show_text_label: the same value from tt_ctl, pill_i.show_text_label), and uses exactly that node's event
    names (the halo's check_decisions rule)."""
    for rel, ev in switches.items():
        if rel not in stock:
            raise SystemExit(f'Time Trial decision on {rel}: no stock decision node reads it')
        used = {s for s, sigs in ev.items() if sigs}
        if used != stock[rel]:
            raise SystemExit(f'Time Trial decision on {rel}: events {sorted(used)}, the stock node has {sorted(stock[rel])}')


# ---------------------------------------------------------------- replay screen (round 5, docs/timing-tower/replay-hud.md 6)
# The replay screen (replays_and_highlights: template in flow_replay.erp and screens/replays_and_highlights.erp, scene
# in those two and flow_frontend.erp) hides the whole HUD and shows its own board: a header (session_timer) and the
# rows (driver_table). While hud_tt_on is true both hide and a third instance of the bottom cap, tt_host, shows the
# tower at the board's top-left, at REPLAY_SCALE (0.78 since round 6; the board's own is 0.9, round 5 used it), so 22
# rows with a two-line block end above the replay controls. The tower's nodes are the HUD's (tower_nodes), so every element
# shows what it shows in the HUD; tt_root also follows the screen's show_drivers_list (the stock list's switch), and
# the instance hides while the lap sting's full-screen video plays (its layers lie between the tower's panels and its
# texts, so the video would cut through the tower). With hud_tt_on false or absent the board is the game's own.
REPLAY_UI = 'eaid://ui_package/screens/replays_and_highlights.ui'
REPLAY_SCENE = 'eaid://ui_package/art/screens/theatre/replay_highlights.idf'
REPLAY_STING_SCENE = 'eaid://ui_package/art/components/theatre/the_video_panel.idf'
REPLAY_ROOT = 'replays_and_highlights'               # the .ui's screen node (UISC); its layout is REPLAY_SCENE
REPLAY_VM = '#replay_flow.replays_and_highlights.'   # its view model (the stock rows bind show_driver_details so)
REPLAY_GROUP = 'elements_null'                       # the scene's null that holds the board
REPLAY_TABLE, REPLAY_HEADER = 'driver_table', 'session_timer'
REPLAY_REFS = {REPLAY_TABLE: 'eaid://ui_package/art/components/theatre/the_driver_position_table.idf',
               REPLAY_HEADER: 'eaid://ui_package/art/components/theatre/the_spec_session_timer.idf'}
REPLAY_POS = (-9.2, 5.0)        # the board's top-left: its header's position (scene units, origin at the screen centre)
REPLAY_BOARD_SCALE = 0.9        # the stock board's scale (its two references), checked
REPLAY_SCALE = 0.78             # the tower's (design decision 2026-11-10; was 0.9, the board's)
REPLAY_SHOW = REPLAY_VM + 'show_drivers_list'        # the stock list group's visible (bool)
REPLAY_STING = REPLAY_VM + 'is_video_sting_enabled'  # the stock lap sting's visible (bool)
# the series logo's leaf on the replay screen (round 6): the screen's own logo_texture, which the stock board's header
# binds (node lap_counter: textureOverride on session_timer); the game writes it with the HUD lap counter's writer
REPLAY_SERIES = REPLAY_VM + 'logo_texture'
SCENE_ROOT = 'Scene Root'
# the board's hide nodes set visible on each instance's Scene Root, which no stock node sets (the stock driver_list_group
# and lap_counter set visible on the references themselves). The stock form of such a chain:
# replay_interface > replay_button_set>camera_view>Scene Root, visible <- #replay_data.controls.show_camera_button
REPLAY_MASKS = (('tt_mask_table', REPLAY_TABLE), ('tt_mask_header', REPLAY_HEADER))
REPLAY_STING_NODE = 'tt_sting'


def build_replay_scene(scene_bytes):
    """The replay scene with tt_host: a clone of the board's driver_table reference (the scene has no bottom cap
    reference to clone), retargeted to the bottom cap (persistent.erp's copy, which tower_scene.erp overlays), at the
    board's top-left (the header's position) and REPLAY_SCALE (the board itself: REPLAY_BOARD_SCALE), under
    elements_null after the board. Every stock element id is kept; nodeidlookup gains tt_host. -> (bytes, info)"""
    idf = I.Idf(scene_bytes)
    sc = idf.scenes[0]
    entry = sc.entry
    assert len(idf.scenes) == 1 and sc.name == I.component_id(REPLAY_SCENE), 'not the stock replay scene'
    stock_ids = {e.path: e.element_id for e, _ in sc.root.walk()}
    stock_lookup = set(sc.nodeidlookup)
    names = [e.name for e, _ in sc.root.walk()]
    assert HOST not in names, 'the replay scene already has ' + HOST
    assert all(names.count(nm) == 1 for nm in [REPLAY_GROUP] + list(REPLAY_REFS)), 'a board name is not unique'
    group = H._find(entry['scene'], REPLAY_GROUP)
    assert group is not None and I._val(group.get('typeName')) == 'eNull', 'replay scene: no ' + REPLAY_GROUP
    kids = {I._val(c.get('name')): c for c in group['children'].items}
    for nm, ref in REPLAY_REFS.items():
        o = kids.get(nm)
        assert o is not None and I._val(o.get('typeName')) == 'eXRef', ('the board reference changed', nm)
        assert I.get_param(o, 'fileRef') == ref and o['xref'].value == I.component_id(ref), (nm, 'fileRef / xref')
        assert I.get_param(o, 'XrefMaterialBinding') == I.material_binding(ref), (nm, 'material binding')
        assert not o['children'].items and not o['geoms'].items and I.get_param(o, 'isHidden') is None, nm
        assert all(abs(v - REPLAY_BOARD_SCALE) < 1e-6 for v in o['scale'].value[:3]), (nm, 'the board scale changed')
    table, header = kids[REPLAY_TABLE], kids[REPLAY_HEADER]
    hx, hy = header['position'].value[:2]
    assert abs(hx - REPLAY_POS[0]) < 1e-4 and abs(hy - REPLAY_POS[1]) < 1e-4, ('the board moved', hx, hy)
    host = I.clone_node(table)
    host.set('name', Val('stri', HOST))
    H._param(host, 'guid', H._guid('replay_highlights/' + HOST))
    I.retarget(host, CAP)
    assert I.get_param(host, 'XrefMaterialBinding') == I.material_binding(CAP), 'tt_host material binding'
    host.set('position', I.clone_node(header['position']))
    sv = host['scale']
    host.set('scale', Val(sv.type, [float(REPLAY_SCALE)] * 3 + list(sv.value[3:])))
    group['children'].items.append(host)
    _ids_and_check(idf, entry, stock_ids, [HOST])
    out = idf.to_bytes()
    # read back: tt_host once, a bottom cap reference where the board starts, stock ids and lookup kept
    back = I.Idf(out)
    e = back.scenes[0].root.find(HOST)
    assert e is not None and e.type == 'eXRef' and e.xref_ok() and e.xref == I.component_id(CAP), 'tt_host reference'
    assert e.path == f'{REPLAY_GROUP}.{HOST}' and e.id_ok() and e.file_ref == CAP
    assert set(back.scenes[0].nodeidlookup) == stock_lookup | {I.djb2(HOST)}, 'nodeidlookup'
    after = {x.path: x.element_id for x, _ in back.scenes[0].root.walk()}
    assert all(after.get(k) == v for k, v in stock_ids.items()) and len(after) == len(stock_ids) + 1
    return out, {'position': [round(x, 6) for x in e.obj['position'].value[:3]], 'scale': list(e.scale),
                 'params': sorted(e.params), 'xref': e.xref, 'elements': len(after),
                 'lookup': len(back.scenes[0].nodeidlookup)}


def sting_layers(video_panel_bytes):
    """the lap sting's drawn layers (the_video_panel.idf: two full-screen video quads, two texts), checked to lie above
    the tower's panels and logos and below its texts: the reason the tower hides while the sting plays. -> layers"""
    idf = I.Idf(video_panel_bytes)
    assert idf.scenes[0].name == I.component_id(REPLAY_STING_SCENE), 'not the stock video panel'
    quads, texts = [], []
    for e, _ in idf.scenes[0].root.walk():
        lay = I.get_param(e.obj, 'eLayer.layer')
        if lay is None:
            continue
        assert not I.get_param(e.obj, 'eLayer.layerIsOffset'), (e.name, 'relative layer')
        if e.geoms:
            lo, hi = I.get_param(e.obj, 'minExtents'), I.get_param(e.obj, 'maxExtents')
            quads.append((lay, hi[0] - lo[0], hi[2] - lo[2]))
        elif e.type == 'eText':
            texts.append(lay)
    assert quads and all(w >= 19.2 - 1e-4 and h >= 10.8 - 1e-4 for _l, w, h in quads), ('not full-screen', quads)
    layers = sorted([q[0] for q in quads] + texts)
    assert LAYER['bar'] < layers[0] and layers[-1] < LAYER['text'], ('the sting no longer cuts through the tower', layers)
    return layers


def _layout_names(n):
    """a UI node's layout chains: [[debugName, ...], ...]"""
    return [[b['debugName'].value for b in grp.items] for grp in n.items[N.LAYOUT].items]


def _visible_targets(root):
    """(node path, layout chain from the screen's scene) of every node below the screen root that sets visible. A
    child's chain continues its parent's (stock: replay_interface > replay_button_set>camera_view>Scene Root); a node
    without a layout keeps its parent's. elements_null is left out: layouts find elements by name below the scene root
    (stock: driver_list_group's layout is driver_table, which sits under elements_null)."""
    found = []

    def walk(n, path, chains):
        mine = [c + [x for x in own if x != REPLAY_GROUP] for c in chains for own in _layout_names(n)] or chains
        if n.items[N.PROPS].get('visible') is not None:
            found.extend((path, tuple(c)) for c in mine)
        for c in N.children(n):
            if N.is_node(c):
                walk(c, f'{path}.{N.name(c)}', mine)

    for c in N.children(root):
        if N.is_node(c):
            walk(c, f'{REPLAY_ROOT}.{N.name(c)}', [[]])
    return found


def replay_stock_types(root):
    """the replay template's bound types: every absolute binding, and the screen-level relative ones as REPLAY_VM +
    leaf (a direct child of the screen root binds its view model so: driver_list_group visible <- show_drivers_list).
    Relative bindings further down are a row's or a widget's own and are left out."""
    types = {}
    for kid in N.children(root):
        if not N.is_node(kid):
            continue
        for _n, _k, t, db in H._bindings(kid, []):
            if db.startswith('#'):
                types.setdefault(db, set()).add(t)
        for _k, v in kid.items[N.PROPS].items:
            if isinstance(v, Obj) and v.get('dbentry') is not None and not v['dbentry'].value.startswith('#'):
                types.setdefault(REPLAY_VM + v['dbentry'].value, set()).add(v['value'].type)
    return types


def replay_binding_type(db, contract, hud, replay):
    """the type a replay tower binding must have: the contract's for DLL leaves; the replay template's for its view
    model; for game values the stock tags of the HUD template and of the replay template (both, where both bind it),
    per-car paths checked as the current car's; else KNOWN_TYPES"""
    if db.startswith(VM):
        return {contract[db]} if db in contract else None
    if db.startswith(REPLAY_VM):
        return replay.get(db)
    key = re.sub(r'#session\.cars\.car\d+\.', '#session.current_car.', db)
    sets = [m[key] for m in (hud, replay) if key in m]
    if sets:
        return set.intersection(*sets) or None
    return {KNOWN_TYPES[key]} if key in KNOWN_TYPES else None


def build_replay_template(ui_bytes, hud_stock_ui_bytes, T, contract):
    """replays_and_highlights.ui plus the tower: under the screen root one group tt_ctl with
      tt_mask_table, tt_mask_header  driver_table>Scene Root, session_timer>Scene Root: visible <- NOT hud_tt_on
      tt_host_n                      tt_host: visible <- hud_tt_on; the HUD's tower nodes (tower_nodes), with v_tt_root
                                     bound to show_drivers_list
      tt_sting                       tt_host>Scene Root: visible <- NOT is_video_sting_enabled
      tt_clock_fmt                   the HUD's clock formatter (the timed header's clock)
    Every binding typed against the contract and the stock tags. -> (bytes, info, [(dbentry, tag)])"""
    p = Pkg(ui_bytes)
    root = H._node_at(p.root, REPLAY_ROOT)
    rp = root.items[N.PROPS]
    assert U._type(root) == 'UISC', 'replay template: the root is not a screen'
    assert rp.get('allowVMBinding') is not None and rp['allowVMBinding']['value'].value is True
    lay = root.items[N.LAYOUT].items
    assert len(lay) == 1 and lay[0].items[0]['componentId'].value == I.component_id(REPLAY_SCENE), 'screen layout'
    assert not any(N.name(c) == CTL for c in N.children(root)), 'the replay template already has the tower'
    hud_p = Pkg(hud_stock_ui_bytes)
    hud = _stock_types(hud_p.root)
    badge_tag = stock_badge_tag(hud_stock_ui_bytes)
    replay = replay_stock_types(root)
    for db in (REPLAY_SHOW, REPLAY_STING):
        assert replay.get(db) == {'bool'}, ('the stock screen no longer binds', db, replay.get(db))
    assert not any(db.endswith(CLOCK_STR) for db in replay), 'the replay screen binds time_remaining_str itself'
    # the series logo: the screen's logo_texture, bound by the stock board's header with the HUD lap counter's tag
    series_tag = stock_series_tag(hud_stock_ui_bytes)
    assert replay.get(REPLAY_SERIES) == {series_tag}, ('the stock screen binds', REPLAY_SERIES, replay.get(REPLAY_SERIES))
    # no stock node shows or hides what these nodes do (a second visible on one element would fight the game's)
    targets = {(REPLAY_TABLE, SCENE_ROOT), (REPLAY_HEADER, SCENE_ROOT), (HOST,), (HOST, SCENE_ROOT)}
    stock_vis = _visible_targets(root)
    fights = [(path, ch) for path, ch in stock_vis if ch in targets]
    assert not fights, ('stock nodes set visible where the tower does', fights)
    for el in (REPLAY_TABLE, REPLAY_HEADER):
        assert any(ch == (el,) for _p, ch in stock_vis), ('the stock board is no longer switched on its reference', el)

    nodes = tower_nodes(T, hud, badge_tag, root_visible=U.prop('bool', True, REPLAY_SHOW),
                        series=(REPLAY_SERIES, series_tag))
    host = U.node('tt_host_n', 'UIGP', [('visible', H._bool_prop(False, leaf('on')))], kids=nodes, layout=[HOST],
                  behav=U.GROUP_BEHAVIOURS)
    masks = [U.node(nm, 'UIGP', [('visible', H._bool_prop(True, leaf('on'), True))], layout=[el, SCENE_ROOT],
                    behav=U.GROUP_BEHAVIOURS) for nm, el in REPLAY_MASKS]
    sting = U.node(REPLAY_STING_NODE, 'UIGP', [('visible', H._bool_prop(True, REPLAY_STING, True))],
                   layout=[HOST, SCENE_ROOT], behav=U.GROUP_BEHAVIOURS)
    clock = clock_formatter(hud_p.root)
    ctl = U.node(CTL, 'UIGP', [], kids=masks + [host, sting, clock], behav=U.GROUP_BEHAVIOURS)

    # every binding's type must be the type of the value it reads: a mismatch crashes the game when the screen opens
    bad, out = [], []
    for node, prop, t, db in H._bindings(ctl, []):
        want = replay_binding_type(db, contract, hud, replay)
        if not want:
            bad.append(f'{node}.{prop} <- {db}: type unknown (not in the contract, no stock binding, not in KNOWN_TYPES)')
        elif t not in want:
            bad.append(f'{node}.{prop} <- {db}: {t}, the value is {"/".join(sorted(want))}')
        out.append((db, t))
    if bad:
        raise SystemExit('replay tower binding types:\n  ' + '\n  '.join(bad))
    N.fix_ids(ctl, REPLAY_ROOT)
    root.items[N.CHILDREN].items.append(ctl)
    data = p.to_bytes()

    # read back: the group once under the root, its children in order, ids by path
    q = Pkg(data)
    got = H._node_at(q.root, f'{REPLAY_ROOT}.{CTL}')
    kids = [N.name(c) for c in N.children(got)]
    assert kids == [nm for nm, _ in REPLAY_MASKS] + ['tt_host_n', REPLAY_STING_NODE, 'tt_clock_fmt'], kids
    count = 0

    def walk(n, path):
        nonlocal count
        count += 1
        pid = n.items[N.PROPS].get('id')
        assert pid is None or pid.value == N.djb2(path), ('node id', path)
        for c in N.children(n):
            if N.is_node(c):
                walk(c, f'{path}.{N.name(c)}')
    walk(got, f'{REPLAY_ROOT}.{CTL}')
    info = {'nodes': count, 'tower_nodes': len(nodes), 'bindings': len(out),
            'dll_leaves': len({db for db, _ in out if db.startswith(VM)}),
            'stock_visible_nodes': len(stock_vis), 'replay_vm': sorted(db for db, _ in out if db.startswith(REPLAY_VM))}
    return data, info, out


# ---------------------------------------------------------------- the spectator HUD (docs/spectator-ui.md 3.1, 10.3)
# The spectator screen's board: a header reference (session_timer) and a table reference (driver_position_table) in
# spectator_mode_2.idf. That scene stays stock: kizi.spectator-hud replaces it (docs/spectator-ui.md 9), and when two
# addons replace one resource the later one wins. So tt_host goes into the table's own scene, beside the null that
# holds the stock rows, and is placed at the board's top-left (the header reference's position).
SPECT_UI = 'eaid://ui_package/screens/hud_spectator_2.ui'
SPECT_SCREEN = 'eaid://ui_package/art/osd/screens/spectator_mode_2.idf'
SPECT_TABLE = 'eaid://ui_package/art/osd/components/spectator_mode/spec_driver_position_table.idf'
SPECT_HEADER = 'eaid://ui_package/art/osd/components/spectator_mode/spec_session_timer.idf'
SPECT_ROOT = 'hud_spectator_2'                 # the .ui's screen node (UISC)
SPECT_PARENT = SPECT_ROOT + '.content'         # the stock board's nodes sit here; tt_ctl goes beside them
SPECT_PREFIX = 'spectator_mode_2'              # the stock layouts' first link (the screen scene, below osd.idf's spectator_2)
SPECT_TABLE_EL, SPECT_HEADER_EL = 'driver_position_table', 'session_timer'   # the board's references in the screen scene
SPECT_GROUP = 'transition'                     # the table scene's null above the stacker of the stock rows
SPECT_CAP_SRC = 'bottom_cap'                   # the table scene's reference that tt_host is cloned from
SPECT_SHOW = 'show_left_side'                  # the screen view model's switch for the board (driver_list_panel, session_display)
SPECT_SERIES = 'logo_texture'                  # the screen view model's series logo (session_display.logo binds it)
SPECT_MASKS = (('tt_mask_table', (SPECT_PREFIX, SPECT_TABLE_EL, SPECT_GROUP)),
               ('tt_mask_header', (SPECT_PREFIX, SPECT_HEADER_EL, SCENE_ROOT)))


def build_spectator_scene(table_bytes, screen_bytes):
    """The spectator board's table scene with tt_host: a clone of its bottom_cap reference, retargeted to the bottom cap
    (persistent.erp's copy, which tower_scene.erp overlays), under the scene root beside 'transition' (the stock rows'
    null, which the table mask hides), at the board's top-left and REPLAY_SCALE. The offset comes from the stock screen
    scene (read only): the header reference's position minus the table reference's. Every stock element id is kept;
    nodeidlookup gains tt_host. -> (bytes, info)"""
    scr = I.Idf(screen_bytes)
    assert len(scr.scenes) == 1 and scr.scenes[0].name == I.component_id(SPECT_SCREEN), 'not the stock spectator scene'
    refs = {}
    for e, _ in scr.scenes[0].root.walk():
        if e.name in (SPECT_TABLE_EL, SPECT_HEADER_EL):
            assert e.name not in refs, ('the board reference is not unique', e.name)
            refs[e.name] = e
    for nm, ref in ((SPECT_TABLE_EL, SPECT_TABLE), (SPECT_HEADER_EL, SPECT_HEADER)):
        e = refs.get(nm)
        assert e is not None and e.type == 'eXRef' and e.file_ref == ref, ('the board reference changed', nm)
        assert e.path == nm, ('the board reference moved', e.path)
        assert all(abs(v - 1.0) < 1e-6 for v in e.obj['scale'].value[:3]), (nm, 'the board scale changed')
    tx, ty = refs[SPECT_TABLE_EL].obj['position'].value[:2]
    hx, hy = refs[SPECT_HEADER_EL].obj['position'].value[:2]
    assert abs(hx - REPLAY_POS[0]) < 1e-4 and abs(hy - REPLAY_POS[1]) < 1e-4, ('the board moved', hx, hy)
    local = (hx - tx, hy - ty)

    idf = I.Idf(table_bytes)
    sc = idf.scenes[0]
    entry = sc.entry
    assert len(idf.scenes) == 1 and sc.name == I.component_id(SPECT_TABLE), 'not the stock spectator table scene'
    stock_ids = {e.path: e.element_id for e, _ in sc.root.walk()}
    stock_lookup = set(sc.nodeidlookup)
    names = [e.name for e, _ in sc.root.walk()]
    assert HOST not in names, 'the spectator table scene already has ' + HOST
    assert all(names.count(nm) == 1 for nm in (SPECT_GROUP, SPECT_CAP_SRC)), 'a table name is not unique'
    top = {I._val(c.get('name')): c for c in entry['scene']['children'].items}
    group = top.get(SPECT_GROUP)
    assert group is not None and I._val(group.get('typeName')) == 'eNull', 'spectator table: no top-level ' + SPECT_GROUP
    assert list(top) == [SPECT_GROUP], ('the table scene root holds more than the stock rows', list(top))
    src = H._find(entry['scene'], SPECT_CAP_SRC)
    assert src is not None and I._val(src.get('typeName')) == 'eXRef', 'spectator table: no ' + SPECT_CAP_SRC
    assert not src['children'].items and not src['geoms'].items, SPECT_CAP_SRC
    assert src.get('anims') is None or not src['anims'].items, SPECT_CAP_SRC
    assert I.get_param(src, 'isHidden') is None, SPECT_CAP_SRC
    host = I.clone_node(src)
    host.set('name', Val('stri', HOST))
    H._param(host, 'guid', H._guid('spec_driver_position_table/' + HOST))
    I.retarget(host, CAP)
    assert I.get_param(host, 'XrefMaterialBinding') == I.material_binding(CAP), 'tt_host material binding'
    pv = src['position']
    host.set('position', Val(pv.type, [float(local[0]), float(local[1]), 0.0] + list(pv.value[3:])))
    sv = host['scale']
    host.set('scale', Val(sv.type, [float(REPLAY_SCALE)] * 3 + list(sv.value[3:])))
    entry['scene']['children'].items.append(host)
    _ids_and_check(idf, entry, stock_ids, [HOST])
    out = idf.to_bytes()
    # read back: tt_host once, under the scene root, a bottom cap reference; stock ids and lookup kept
    back = I.Idf(out)
    e = back.scenes[0].root.find(HOST)
    assert e is not None and e.type == 'eXRef' and e.xref_ok() and e.xref == I.component_id(CAP), 'tt_host reference'
    assert e.path == HOST and e.id_ok() and e.file_ref == CAP
    assert set(back.scenes[0].nodeidlookup) == stock_lookup | {I.djb2(HOST)}, 'nodeidlookup'
    after = {x.path: x.element_id for x, _ in back.scenes[0].root.walk()}
    assert all(after.get(k) == v for k, v in stock_ids.items()) and len(after) == len(stock_ids) + 1
    world = [round(tx + local[0], 6), round(ty + local[1], 6)]
    return out, {'local': [round(x, 6) for x in e.obj['position'].value[:3]], 'world': world, 'scale': list(e.scale),
                 'params': sorted(e.params), 'xref': e.xref, 'elements': len(after),
                 'lookup': len(back.scenes[0].nodeidlookup)}


def _chains(n):
    return [tuple(b['debugName'].value for b in grp.items) for grp in n.items[N.LAYOUT].items]


def spectator_visible_targets(content):
    """(node path, layout chain) of every node under the screen's content that sets visible; a child's chain continues
    its parent's, a node without a layout keeps its parent's (chains start at the screen scene: spectator_mode_2 >)"""
    found = []

    def walk(n, path, chains):
        mine = [c + own for c in chains for own in _chains(n)] or chains
        if n.items[N.PROPS].get('visible') is not None:
            found.extend((path, c) for c in mine)
        for c in N.children(n):
            if N.is_node(c):
                walk(c, f'{path}.{N.name(c)}', mine)

    for c in N.children(content):
        if N.is_node(c):
            walk(c, f'{SPECT_PARENT}.{N.name(c)}', [()])
    return found


def spectator_stock_types(root):
    """the spectator template's bound types: every absolute binding, and the relative ones that resolve in the screen's
    own view model (nodes below the screen root with no dataContext on the way: driver_list_panel's show_left_side,
    session_display.logo's logo_texture). A list's rows and a dial's parts bind their own view models: left out."""
    types = {}
    for _n, _k, t, db in H._bindings(root, []):
        if db.startswith('#'):
            types.setdefault(db, set()).add(t)

    def walk(n):
        props = n.items[N.PROPS]
        if props.get('dataContext') is not None:
            return
        for _k, v in props.items:
            if isinstance(v, Obj) and v.get('dbentry') is not None and not v['dbentry'].value.startswith('#'):
                types.setdefault(v['dbentry'].value, set()).add(v['value'].type)
        for c in N.children(n):
            if N.is_node(c):
                walk(c)

    for c in N.children(root):
        if N.is_node(c):
            walk(c)
    return types


def spectator_binding_type(db, contract, hud, spect):
    """the type a spectator tower binding must have: the contract's for DLL leaves; the spectator template's for its
    screen view model; for game values the stock tags of the HUD template and of the spectator template (both, where
    both bind it), per-car paths checked as the current car's; else KNOWN_TYPES"""
    if db.startswith(VM):
        return {contract[db]} if db in contract else None
    if not db.startswith('#') and db in spect:
        return spect[db]
    key = re.sub(r'#session\.cars\.car\d+\.', '#session.current_car.', db)
    sets = [m[key] for m in (hud, spect) if key in m]
    if sets:
        return set.intersection(*sets) or None
    return {KNOWN_TYPES[key]} if key in KNOWN_TYPES else None


def build_spectator_template(ui_bytes, stock_ui_bytes, hud_stock_ui_bytes, T, contract):
    """hud_spectator_2.ui as the halo built it (erp/halo_spectator.erp: stock + the halo's dial groups) plus the tower:
    under the screen's content one group tt_ctl with
      tt_mask_table   driver_position_table>transition (the stock rows): visible <- NOT hud_tt_on
      tt_mask_header  session_timer>Scene Root (the stock header): visible <- NOT hud_tt_on
      tt_host_n       driver_position_table>tt_host: visible <- hud_tt_on; the HUD's tower nodes (tower_nodes), with
                      v_tt_root bound to show_left_side (the stock board's switch) and the series logo to logo_texture
      tt_clock_fmt    the HUD's clock formatter (the timed header's clock)
    Every binding typed against the contract and the stock tags. -> (bytes, info, [(dbentry, tag)])"""
    stock_root = Pkg(stock_ui_bytes).root
    # the input is the halo's: the stock template plus our halo groups, nothing else
    assert H._canon(H._strip_ours(Pkg(ui_bytes).root)) == H._canon(stock_root), 'the halo spectator .ui is not stock + halo'
    p = Pkg(ui_bytes)
    root = H._node_at(p.root, SPECT_ROOT)
    rp = root.items[N.PROPS]
    assert U._type(root) == 'UISC', 'spectator template: the root is not a screen'
    assert rp.get('allowVMBinding') is not None and rp['allowVMBinding']['value'].value is True
    content = H._node_at(p.root, SPECT_PARENT)
    cp = content.items[N.PROPS]
    assert U._type(content) == 'UIGP' and not _chains(content) and cp.get('dataContext') is None, 'spectator content'
    assert not any(N.name(c) == CTL for c in N.children(content)), 'the spectator template already has the tower'
    hud_p = Pkg(hud_stock_ui_bytes)
    hud = _stock_types(hud_p.root)
    badge_tag = stock_badge_tag(hud_stock_ui_bytes)
    series_tag = stock_series_tag(hud_stock_ui_bytes)
    spect = spectator_stock_types(H._node_at(stock_root, SPECT_ROOT))
    assert spect.get(SPECT_SHOW) == {'bool'}, ('the stock screen binds', SPECT_SHOW, spect.get(SPECT_SHOW))
    assert spect.get(SPECT_SERIES) == {series_tag}, ('the stock screen binds', SPECT_SERIES, spect.get(SPECT_SERIES))
    assert CLOCK_STR not in spect, 'the spectator screen binds time_remaining_str itself'
    # the stock board shows and hides on its references, never where the tower does (a second visible on one element
    # would fight the game's)
    stock_vis = spectator_visible_targets(H._node_at(stock_root, SPECT_PARENT))
    targets = {chain for _nm, chain in SPECT_MASKS} | {(SPECT_PREFIX, SPECT_TABLE_EL, HOST),
                                                       (SPECT_PREFIX, SPECT_TABLE_EL, HOST, SCENE_ROOT)}
    fights = [(path, ch) for path, ch in stock_vis if ch in targets]
    assert not fights, ('stock nodes set visible where the tower does', fights)
    assert any(ch == (SPECT_PREFIX, SPECT_HEADER_EL) for _p, ch in stock_vis), 'the stock header is no longer switched'

    nodes = tower_nodes(T, hud, badge_tag, root_visible=U.prop('bool', True, SPECT_SHOW), series=(SPECT_SERIES, series_tag))
    host = U.node('tt_host_n', 'UIGP', [('visible', H._bool_prop(False, leaf('on')))], kids=nodes,
                  layout=[SPECT_PREFIX, SPECT_TABLE_EL, HOST], behav=U.GROUP_BEHAVIOURS)
    masks = [U.node(nm, 'UIGP', [('visible', H._bool_prop(True, leaf('on'), True))], layout=list(chain),
                    behav=U.GROUP_BEHAVIOURS) for nm, chain in SPECT_MASKS]
    clock = clock_formatter(hud_p.root)
    ctl = U.node(CTL, 'UIGP', [], kids=masks + [host, clock], behav=U.GROUP_BEHAVIOURS)

    # every binding's type must be the type of the value it reads: a mismatch crashes the game when the screen opens
    bad, out = [], []
    for node, prop, t, db in H._bindings(ctl, []):
        want = spectator_binding_type(db, contract, hud, spect)
        if not want:
            bad.append(f'{node}.{prop} <- {db}: type unknown (not in the contract, no stock binding, not in KNOWN_TYPES)')
        elif t not in want:
            bad.append(f'{node}.{prop} <- {db}: {t}, the value is {"/".join(sorted(want))}')
        out.append((db, t))
    if bad:
        raise SystemExit('spectator tower binding types:\n  ' + '\n  '.join(bad))
    N.fix_ids(ctl, SPECT_PARENT)
    content.items[N.CHILDREN].items.append(ctl)
    data = p.to_bytes()

    # read back: the group once under content, its children in order, ids by path; outside tt_ctl the halo's .ui as given
    q = Pkg(data)
    got = H._node_at(q.root, f'{SPECT_PARENT}.{CTL}')
    kids = [N.name(c) for c in N.children(got)]
    assert kids == [nm for nm, _ in SPECT_MASKS] + ['tt_host_n', 'tt_clock_fmt'], kids
    assert H._canon(H._strip_ours(q.root, (CTL,))) == H._canon(Pkg(ui_bytes).root), 'a node outside tt_ctl changed'
    assert H._canon(H._strip_ours(q.root, H.OUR_GROUPS + (CTL,))) == H._canon(stock_root), 'a stock node changed'
    count = 0

    def walk(n, path):
        nonlocal count
        count += 1
        pid = n.items[N.PROPS].get('id')
        assert pid is None or pid.value == N.djb2(path), ('node id', path)
        for c in N.children(n):
            if N.is_node(c):
                walk(c, f'{path}.{N.name(c)}')
    walk(got, f'{SPECT_PARENT}.{CTL}')
    info = {'nodes': count, 'tower_nodes': len(nodes), 'bindings': len(out),
            'dll_leaves': len({db for db, _ in out if db.startswith(VM)}),
            'stock_visible_nodes': len(stock_vis), 'screen_vm': sorted({db for db, _ in out if not db.startswith('#')})}
    return data, info, out
