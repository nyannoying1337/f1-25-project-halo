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
import math
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

CONTRACT_VERSION = 13         # leaves.md v13: kin1 ... krs, gh_* (header card motion); v12: rNN_xu1 ... rNN_xrs (row motion, no trigger); v11: rNN_u1 ... rNN_st; v10: rNN_dup, rNN_ddn, flap; v9: rows r22-r29, cars c24-c29; v8: rNN_pb, rNN_ob, rNN_fl; v7: clock, rNN_ko; v6: rNN_det; v5: trial, show (bool); v4: rNN_badge, rNN_bdg; v3: red, yel, ysec, ysna
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
# right above the tower; it is hidden while the tower shows (fix round 1; its panel). Every part that draws
# lies in an element that no stock template node targets, and a tower node (tt_lapc > v_tt_lapc_<el>) hides that
# element while hud_tt_show:
# - LAPC_HIDE: such parts in the stock scene (fix round 1; seen hidden in game, an in-game Practice screenshot);
# - LAPC_WRAP: the panel's parts (lap_bg with lap_bg_overlay, edge_base, edge_border, lockup) are each the target
#   of a stock node, and those drew in game whatever the tower did: earlier builds put tower nodes on them, a later one bound
#   visible on their own stock nodes; both left the empty panel (in-game Practice screenshots, 2026-11-10,
#   "empty box still there" without a flag). The build wraps each in a new null of its own (LAPC_WRAPPER + part) at the
#   part's place in the scene (order, position and every stock name kept; the stock nodes find their parts by name
#   through the scene's nodeidlookup) and hides the wrapper. The parent-hides-child behaviour is the one fix round 1
#   shows in game: centre_lap_value's tower node hid the lap texts in it, which stock text nodes target.
LAPC_TEMPLATE = 'hud_lap_counter.osd_visibility_option'
LAPC_HIDE = ('car_category_logo', 'session_icon', 'centre_lap_value', 'separator_bg', 'separator_bg_top',
             'centre_formation')
LAPC_WRAP = ('edge_base', 'edge_border', 'lap_bg', 'lockup')
LAPC_WRAPPER = 'tt_lapw_'
LAPC_STOCK_KIDS = ('car_category_logo', 'edge_base', 'edge_border', 'holder_formation', 'holder_standard', 'lap_bg',
                   'lockup', 'session_icon')
# The game's race condition flag message (template hud_left_notification_dynamic, nameId race_condition_flag_message,
# scene race_condition_flag_message.idf; default layout (0.51, -0.51), the lap counter's place): "LAP 0", CAUTION and
# SECTOR 3 in a hazard frame over the tower's header (an in-game Practice screenshot). The tower hides it while
# hud_tt_show with one tower node on FLAGM_PART, the scene element that holds everything it draws and that no stock node
# targets (its stock nodes target Scene Root, flag_bg and the parts below). The tower's header shows the yellow, SC, VSC,
# red and chequered states itself.
FLAGM_TEMPLATE = 'hud_left_notification_dynamic.osd_visibility_option.left_notification.left_message'
FLAGM_SCENE = 'eaid://ui_package/art/osd/components/message_system/race_condition_flag_message.idf'
FLAGM_PART = 'boundless'
FLAGM_NODE = 'tt_flagm'      # the tower's group under a message node (the HUD's and the spectator's)
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
NROWS, NCARS = 30, 30
# Gap column vs driver code (fix round 1, 2026-11-09; measured on an in-game Bahrain screenshot, ui-build.md "Fix round 1").
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
# the formatter's start pin. Every stock time_remaining_formatter (hud_session_timer_dynamic and both HUD pill
# stacks) gets exactly one signal, this pin, from its timer's visibility decision ('visible'); the clone got none
# at first (the clock never showed). tt_ctl's trigger (Track Position's enable) sends it now (check_clock_start).
CLOCK_PIN = 'formatTime'
# the HUD's clock goes through an absolute node: the clone writes the clock text into hud_tt_clock (the stock
# pit lane timer's formatter writes its absolute #session.current_car.pit_lane_timer_str the same way) and the
# header's clock text reads it. The DLL keeps the node existing ("") while the header is not timed and never writes
# it while timed (leaves.md v7). A decision on hud_tt_timed also starts the clone ('1': the header turned timed), as
# the stock timers' visibility decisions do. The replay and spectator copies are unchanged (relative, open).
CLOCK_OUT_KEY, CLOCK_DECISION = 'clock', 'tt_mv_clock'
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
# ko: the knockout hatch, over the position strip, under the player highlight (10 % white: it shows over the
# hatch as over the strip), the P1 box, the arrows and the number
LAYER = {'bg': 20, 'ko': 21, 'hl': 22, 'p1': 23, 'mark': 25, 'bar': 30, 'text': 40, 'dim': 45}
# the lap time flash's text colours (a static colourOverride on the coloured copies of the timed gap text,
# as the stock champion label's '#eab51fff') and the race's fastest lap box. Green from the reference clip's
# personal-best text (measured: median (78, 174, 75), 90th percentile (147, 199, 146) over the glyphs); the clip
# shows no purple, so the purple is chosen for the dark panel. Display choices, no game value.
FLASH = {'pb': (0x58, 0xD6, 0x54), 'ob': (0xA6, 0x4B, 0xF4)}
FLASH_HEX = {k: '#%02x%02x%02xff' % c for k, c in FLASH.items()}
# the animations ( leaves.md v12). In every live row (never the HUD editor's copy) two nested
# anim nulls at the row's origin hold everything that belongs to the car: tt_rNN_mu slides it up (the car gained
# places), tt_rNN_md down; inside them tt_rNN_au and tt_rNN_ad hold the up and down arrows for their entry. Each null
# has its own clip in the cap scene (anim_clips): translation only (scene y up). A clip is at rest (zero offset) at
# fraction 0, at fraction 1 and between its segments. A segment holds one motion: from its start offset at fraction a
# to rest at b, keyed on the broadcast's ease-out (time constant ANIM_TAU) over the play's ANIM_PLAY seconds. A motion is
# goToFraction(a) + playToFraction(b) on ANIM_CURVE, a linear curve, so the clip's keys alone shape it (seen in game:
# the game plays a curve of type ease_out with steepness s as (t / T)^s, a slow start [game]); every segment spans the
# same fraction, so every play is alike whatever a play's length depends on (the curve's period [game]). mu and
# md hold a segment per distance (1, 2, 3 rows), au and ad one (the entry). The faded texts fade in on FADE_CURVE (UIMOs
# in the stock fade-in's form). Template nodes: anim_nodes().
ANIM_NULLS = ('mu', 'md', 'au', 'ad')
ANIM_ROWS = {'mu': -1.0, 'md': 1.0, 'au': -0.43, 'ad': 0.43}  # start offset per row of distance, in row pitches (y up)
ANIM_SEGS = {1: (0.05, 0.35), 2: (0.375, 0.675), 3: (0.70, 1.0)}  # rows of distance -> (a, b) on mu and md
ANIM_ENTRY = (0.70, 1.0)              # the arrow entry's segment on au and ad
ANIM_EPS = 0.005                      # fraction: the key before a segment (on the profile's extension) and the rest
                                      # keys around it (a spline through the keys keeps the profile's slope at a)
ANIM_PLAY = 0.75                      # s: a play's length = ANIM_CURVE's period (tower_anim.hpp kPlay)
ANIM_TAU = 0.154                      # s: the broadcast's ease-out (50 % at 0.107 s, 90 % at 0.355 s)
ANIM_KEYS = 20                        # key intervals per segment, closer at the start (anim_keys)
ANIM_CURVE = 'bc_grid_rundown_item_current'  # linear, 0.75 s, steepness 1 (the game's curve library)
FADE_CURVE = 'generic_fade_on'        # ease_out, 0.15 s, steepness 2 (the stock fade-in's own curve)
ANIM_FADES = ('pos', 'gtpb', 'gtob')  # the faded texts tt_rNN_<key>: the number (xnf), the flash copies (xff)
ANIM_CODES = ('xu1', 'xu2', 'xu3', 'xd1', 'xd2', 'xd3', 'xeu', 'xed', 'xnf', 'xff', 'xrs')  # leaves.md v12, AnimCode order
CAP_STRTAB = CAP + '?context=animstringtable&file=0'
CAP_ANIM = 'pill_rotation_anim'        # the cap scene's own animated null: the model of the anim nulls
# the flag cards slide in and out (leaves.md v13). In the live tower (never the HUD
# editor's copy) the cards (tt_cards) and the rows (tt_rows) sit in one top-to-bottom stacker (tt_bstk) inside a body
# that two nested anim nulls move (tt_xin > tt_xout: the rows' mu / md form, ANIM_SEGS, the same ease-out), in a static
# clip window (tt_clip: the halo's battery and capsule window, dial_mods' eWindow) whose top edge is the header band's
# bottom edge: tt_clipn takes the rows' old place in tt_stack after tt_top, so the Tower header setting off still puts
# the rows at the top. kinK: the body starts the card's height up (the new card hidden under the band, the rows where
# they were) and eases to rest; koutK: it starts the card's height down (the rows where they were) with the card's copy
# (tt_gh_<card>, hud_tt_gh_<card>) one card height above the cards, and eases to rest: the copy rolls up under the band
# while the rows close the gap. Every stacker moves with its children: none reads a moving bound.
BODY_NULLS = ('xin', 'xout')                # tt_xin (outer), tt_xout: named to sort after the rows' clips
BODY_SIGN = {'xin': 1.0, 'xout': -1.0}      # start offset direction (scene y up): in starts above, out below
BODY_PITCHES = {1: 1.0, 2: 2.0, 3: 2.5}     # card size (tower_anim.hpp card_size) -> the card's height in row pitches
CARD_SIZE = {'chq': 1, 'red': 2, 'sc': 2, 'vsc': 3, 'yel': 2}
CARDS = ('chq', 'red', 'sc', 'vsc', 'yel')  # Card order (tower_anim.hpp); the copies' leaves gh_<card>
HEAD_CODES = ('kin1', 'kin2', 'kin3', 'kout1', 'kout2', 'kout3', 'krs')   # leaves.md v13, HeadCode order
CLIP_LEFT, CLIP_RIGHT, CLIP_BOTTOM = 1.0, 4.0, 1.0   # p: the window past the panel (the rows' pit, penalty and
                                                     # fastest lap marks reach 1.6 p past its right edge) and the rows
CLIP_Z = -0.12                              # the window's z, as the stock window's and the halo's (content back at 0)
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
# the spectator's Detail cell. Sizes in p. Every text fits its cell
# unsqueezed at the game's widths (the number style's digits 1.126 caps each, measured 2026-11-09; letters Saira's x
# the same ratio, about 5 % wider than the game's own board shows them, an in-game "Interval"): the widest texts are a
# two-digit penalty "15s" (3.13 caps) and the places gained "up 21" (the triangle, DET_GAP and 2.25 caps). The cell
# runs from the gap column's right edge to the panel's (the '!' box starts there): 0.79 p in races, 0.69 p in timed
# sessions (their gap column ends 1.3 HUD further right). The sizes keep at least 0.08 p clear on both sides: at
# 0.22 p a race's "10s" or "up 19" sat 0.05 p (1.5 px at 1080p) from the gap text and read as one string.
# - races: every text at DET_CAP, centred on the tyre letter (0.26 before, so "10s" squeezed to 0.97 and "15s" did
#   not fit); the box keeps DET_CLEAR from both edges; places gained or lost: the triangle (sprites pcu / pcd,
#   DET_ARROW w x h) and the count in its colour, one group centred on the tyre letter;
# - timed sessions: the menu offers no text there (Detail None, Tyre, Best; spectator-ui.md 10.4), so a text shows only
#   in the views it does not offer; DET_CAP_T, centred in the narrower cell, so "15s" fits it too.
DET_CAP, DET_CAP_T = 0.20, 0.17
DET_CLEAR = 0.075            # the text box's clearance from the gap column's edge and the panel's, each side
DET_GAP = 0.03               # triangle to count
DET_ARROW = (0.14, 0.105)    # the places gained / lost triangle (export_tower.js pcu / pcd: the same numbers)
DIGIT_CAPS = 1.126            # the game's number-style digit advance, in caps (fix round 1; tower_sim GAME_CAPS)
LAP_CAP = 0.37               # race lap times (the spectator's Gap Fastest Lap): "1:28.6" fits the race gap box
#                              unsqueezed (5.40 caps; at the number cap 0.428 p it squeezed to about 0.89)
LAP_CAP_T = 0.28             # timed lap times (P1's best lap, the flash, Gap Fastest Lap): "1:06.506" (7.654
#                              caps) fits the timed gap box (2.166 p) unsqueezed; at the number cap 0.383 p the game
#                              squeezed P1's to about 0.73 (an in-game Q1 screenshot)


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
    counter's eXRef of its logo unit; dial_mods' eWindow, the halo's clip window)."""

    def __init__(self, cap_bytes, dial_bytes, lapc_bytes, stacked_bytes, embs, row_bytes, logo_bytes, cat_bytes,
                 mods_bytes):
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
        # the cap's own animated null (one anims entry naming its clip), the model of the rows' anim nulls (the
        # halo's anim nulls are clones of dial_mods' animated null the same way)
        self.T_anim = H._find(self.root, CAP_ANIM)
        assert self.T_anim is not None and I._val(self.T_anim.get('typeName')) == 'eNull', 'cap: no animated null'
        ents = self.T_anim['anims'].items
        assert len(ents) == 1 and ents[0]['asset'].type == 'stri', 'cap: the animated null has not one anims entry'
        assert ents[0]['asset'].value == f'{CAP}/{CAP_ANIM}?context=animation', ents[0]['asset'].value
        self.anims = []        # the anim nulls (their clips: anim_clips)
        # the clip window's model, dial_mods' mod_1_icon_fill_mask (the halo's windows clone it): an eWindow of
        # width x length centred on its position, its extents that rect, no geometry or clip of its own
        self.T_win = H._find(I.Idf(mods_bytes).scenes[0].entry['scene'], 'mod_1_icon_fill_mask')
        assert self.T_win is not None and I._val(self.T_win.get('typeName')) == 'eWindow', 'dial_mods: no eWindow'
        w0, l0 = I.get_param(self.T_win, 'width'), I.get_param(self.T_win, 'length')
        lo0, hi0 = I.get_param(self.T_win, 'minExtents'), I.get_param(self.T_win, 'maxExtents')
        assert all(abs(a - b) < 1e-6 for a, b in zip(lo0[:2] + hi0[:2], (-w0 / 2, -l0 / 2, w0 / 2, l0 / 2))), (lo0, hi0)
        assert not self.T_win['geoms'].items and not self.T_win['anims'].items

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

    def null(self, name, x=0.0, y=0.0, hidden=False, scale=1.0, z=0.0):
        return self._base(self.T_null, name, (KT * x, -KT * y, z), None, (scale, scale, 1.0), hidden)

    def anim_null(self, name):
        """a null at its parent's origin, moved by its own clip CAP/<name>?context=animation that a UIXA plays: a
        clone of the cap's animated null with its anims entry renamed (the halo's anim null form, halo_native
        Scene.null(anim=True)). Clip keys are the null's absolute local transform, so it sits at (0, 0, 0)."""
        o = self._base(self.T_anim, name, (0.0, 0.0, 0.0))
        entry = I.clone_node(self.T_anim['anims'].items[0])
        entry.set('asset', Val('stri', f'{CAP}/{name}?context=animation'))
        o.set('anims', Arr([entry], self.T_anim['anims'].tag))
        self.anims.append(name)
        return o

    def window(self, name, x0, y0, x1, y1):
        """a clip window over the HUD rect (x0, y0)-(x1, y1) of its parent's frame: a clone of dial_mods' window
        (the halo's battery and capsule windows), centred on the rect at z CLIP_Z. Its children are in its own frame
        (relative to the rect's centre), as in the halo's windows."""
        w, l = KT * (x1 - x0), KT * (y1 - y0)
        o = self._base(self.T_win, name, (KT * (x0 + x1) / 2, -KT * (y0 + y1) / 2, CLIP_Z))
        H._param(o, 'width', float(w), 'fp32')
        H._param(o, 'length', float(l), 'fp32')
        H._param(o, 'minExtents', [-w / 2, -l / 2, -0.0, 0.0], 'vec3')
        H._param(o, 'maxExtents', [w / 2, l / 2, -0.0, 0.0], 'vec3')
        return o

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
        # the Detail cell's places gained / lost count in the triangles' colours (tower.js P.up, P.down)
        self.det_hex = {k: '#%sff' % meta['P'][k].lstrip('#').lower() for k in ('up', 'down')}
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

    def bind(self, el, vis=None, neg=False, text=None, colour=None):
        if self.game:
            rec = {'el': el, 'vis': (vis, neg) if vis else None, 'text': text}
            if colour:
                rec['tcol'] = colour    # a static colourOverride on the text's label
            self.recs.append(rec)

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
             vis=None, neg=False, colour=None):
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
        self.bind(self.n(name), vis, neg, text, colour)
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
        # the flag cards (cards()): the HUD editor's copy holds them here, under the band, and the stacker
        # moves the rows below them; the live tower holds them in the clipped body with the rows (build(), body())
        if not self.game:
            self.B.kids(top, *[c for c in self.cards(G['sep'] + G['band']) if c is not None])
        return top

    def card(self, key, pfx, y, vis, text=None):
        """the flag card `key` (chq, red, sc, vsc, yel): a null pfx + key at (0, y) shown by vis, its parts named pfx +
        part. The cards: pfx 'tt_' (the live tower's names; the HUD editor's copy 'tp_'); the exit's copies: 'tt_gh_'.
        text: the yellow line's (sectors, no sector) leaves, default the card's own (ysec, ysna)"""
        if key == 'yel':
            return self.yellow(y, pfx, vis, *(text or (leaf('ysec'), leaf('ysna'))))
        blk = self.shown_null(f'{pfx}{key}', 0.0, y, vis=vis)
        if blk is None:
            return None
        parts = [self.sprite(f'{pfx}{key}_bg', key, layer=LAYER['bg'])]
        if key in ('sc', 'vsc'):
            # the VSC block is 2.50 p (the broadcast reference; its sprite's bounds move the rows down), its FIA badge
            # moved down by vscDy so it stays centred as in the SC box
            p, sc = self.G['p'], self.G['status']['sc']
            dy = sc.get('vscDy', 0.0) * p if key == 'vsc' else 0.0
            box = (sc['fx0'] * p, sc['fy0'] * p + dy, (sc['fx1'] - sc['fx0']) * p, (sc['fy1'] - sc['fy0']) * p)
            parts.append(self.fit(f'{pfx}{key}_fia', 'g_fia_k', GAME_SIZE['g_fia_k'], box, LAYER['mark']))
        return self.B.kids(blk, *parts)

    def cards(self, y):
        """the status blocks under the band (shown only with the header), each at y: one at a time, in the DLL's order
        (leaves v3, `hs`): chequered > red > SC > VSC > yellow. Bools only (D5: no int32 binding); nested nulls give
        the AND: tt_nchq (not chequered) holds red, SC, VSC (the DLL never sets two of them) and, inside tt_nsc /
        tt_nvsc / tt_nred, the yellow block. Two row slots each (VSC 2.5), chequered one; the rows below
        move down by the stacker. -> [tt_chq, tt_nchq], None where the preview state shows none"""
        chq = self.card('chq', 'tt_', y, leaf('chq'))
        under = [b for b in (self.card(k, 'tt_', y, leaf(k)) for k in ('red', 'sc', 'vsc')) if b is not None]
        yel = self.card('yel', 'tt_', y, leaf('yel'))
        if yel is not None:
            for key in ('red', 'vsc', 'sc'):                      # innermost first
                yel = self.B.kids(self.shown_null(f'tt_n{key}', vis=leaf(key), neg=True), yel)
            under.append(yel)
        return [chq, self.B.kids(self.shown_null('tt_nchq', vis=leaf('chq'), neg=True), *under) if under else None]

    def yellow(self, y, pfx='tt_', vis=None, ysec=None, ysna=None):
        """the yellow flag block (tower.js drawStatus 'yellow'): the baked YELLOW FLAG bar and dark band (sprite yel),
        and on the band the game's word (YEL_LABEL, localised) and the flagged sectors (hud_tt_ysec: "2", "1 3"), or
        the dim bar while a yellow zone has no sector (ysna). Game text styles (white): the drawing's yellow line text
        needs a colour no stock template sets on a label without a binding. pfx, vis and the line's leaves serve
        the exit's copy (tt_gh_yel: hud_tt_gh_ysec / gh_ysna, the line as the card showed it when it went)."""
        vis, ysec, ysna = vis or leaf('yel'), ysec or leaf('ysec'), ysna or leaf('ysna')
        blk = self.shown_null(f'{pfx}yel', 0.0, y, vis=vis)
        if blk is None:
            return None
        G, p, W = self.G, self.G['p'], self.G['w']
        cap = G['status']['hazCap'] * p
        base = p + G['mid'] + cap / 2
        em = cap / CAP_EM
        line = self.B.centre(self.n(f'{pfx}ysl'), W / 2, 0.0)
        stk = self.B.stacker(self.n(f'{pfx}ys_stk'), -YEL_TYPICAL_EM * em / 2, base, 'l', 0.28 * em)
        word = self.text(f'{pfx}ysw', 0.0, 0.0, cap, 'OSD_24_regular', 'left', 4.0 * p, ('=', YEL_LABEL, True))
        num = self.text(f'{pfx}ysn', 0.0, 0.0, cap, 'OSD_26_bold', 'left', 1.6 * p, (ysec, 'stri'), vis=ysna, neg=True)
        na = self.quad(f'{pfx}ysna', 'na', (0.0, -cap / 2 - 0.03 * p, 0.36 * p, -cap / 2 + 0.03 * p), LAYER['mark'],
                       vis=ysna)
        self.B.kids(stk, word, num, na)
        return self.B.kids(blk, self.sprite(f'{pfx}yel_bg', 'yel', layer=LAYER['bg']), self.B.kids(line, stk))

    def ghosts(self):
        """the live tower: the exit's copies, tt_gh_<card> for every card, each its card's height above the cards'
        top (in the body: where the card was while the body starts down, rolling up under the band as it eases to
        rest), shown by hud_tt_gh_<card> (the DLL: only with its kout code, for at most 0.85 s). The yellow copy's line
        reads hud_tt_gh_ysec / gh_ysna, the sectors as the card showed them when it went, never the live ones. In
        tt_ghost, shown with the header as the cards."""
        g = self.shown_null('tt_ghost', vis=leaf('hdr'))
        for key in CARDS:
            h = self.sp[key]['y1'] - self.sp[key]['y0']
            self.B.kids(g, self.card(key, 'tt_gh_', -h, leaf(f'gh_{key}'),
                                      (leaf('gh_ysec'), leaf('gh_ysna')) if key == 'yel' else None))
        return g

    def body(self, cards, rows, ghost):
        """the live tower: tt_clipn (in tt_stack after tt_top: the band's bottom edge, or the top with the header
        off) > tt_clip (the clip window, from that edge down past the rows and their marks) > tt_clipo (back at
        tt_clipn's origin) > tt_xin > tt_xout (the body's anim nulls) > [tt_ghost,
        tt_bstk (stacker: tt_cards, tt_rows)]: the copies first, so a copy draws before the rows (layer, then scene
        order) as its card does. self.clip: the window's HUD rect in tt_clipn's frame"""
        G, p, W = self.G, self.G['p'], self.G['w']
        x0, x1 = -CLIP_LEFT * p, W + CLIP_RIGHT * p
        L = (max(BODY_PITCHES.values()) + NROWS + CLIP_BOTTOM) * p
        self.clip = (x0, 0.0, x1, L)
        k = self.B.kids
        clipn = self.null('tt_clipn', 0.0, G['sep'] + G['band'])     # stored where the stacker puts it (header)
        win = self.B.window('tt_clip', x0, 0.0, x1, L)
        back = self.B.null('tt_clipo', -(x0 + x1) / 2, -L / 2, z=-CLIP_Z)
        xin, xout = self.B.anim_null('tt_xin'), self.B.anim_null('tt_xout')
        bstk = self.B.stacker('tt_bstk', 0.0, 0.0, 't', 0.0)
        return k(clipn, k(win, k(back, k(xin, k(xout, ghost, k(bstk, cards, rows))))))

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
        # the knockout hatch: the whole position strip while rNN_ko (Q1, Q2, SQ1, SQ2: a car below the last
        # position that goes through); P1 is never in the zone, so the red box is untouched
        k(row, self.quad(r + '_ko', 'ko', (0.0, 0.0, G['strip'], p), LAYER['ko'], vis=L('ko')))
        # everything that belongs to the car rides in two anim nulls at the row's origin
        # (tt_rNN_mu > tt_rNN_md) that slide it in from the car's old row; the strip, the panel, the separator, the
        # knockout hatch and the debug line stay outside, still. The arrows sit in their own entry nulls inside (au, ad).
        # Live tower only: the HUD editor's copy never moves. The elements keep their order (and layers) as without animations.
        mv = row
        if self.game:
            mv = self.B.anim_null(r + '_md')
            k(row, k(self.B.anim_null(r + '_mu'), mv))
        k(mv, self.quad(r + '_me', 'me', (0.0, 0.0, W, p), LAYER['hl'], vis=L('me')))
        b = G['p1']
        p1 = self.quad(r + '_p1', 'p1', (b['x'], b['y'], b['x'] + b['w'], b['y'] + b['h']), LAYER['p1'], vis=L('p1'))
        up, dn = self.sprite(r + '_up', 'up', vis=L('up')), self.sprite(r + '_dn', 'dn', vis=L('dn'))
        if self.game:
            k(mv, k(self.B.anim_null(r + '_au'), up), k(self.B.anim_null(r + '_ad'), dn))
        else:
            k(mv, up, dn)
        # the position number and P1's red box: hidden while an arrow shows (nested groups give AND). The
        # broadcast drops the leader's box while the new leader's arrow shows (broadcast reference); an earlier build drew the green arrow
        # on the red box. The box keeps its layer (under the number), the nulls only add the AND.
        pa = self.shown_null(r + '_pa', vis=L('up'), neg=True)
        pb = self.shown_null(r + '_pb', vis=L('dn'), neg=True)
        if pa is not None and pb is not None:
            k(mv, k(pa, k(pb, p1, self.text(r + '_pos', G['posX'], mid + G['posCap'] / 2, G['posCap'],
                                             'OSD_19_regular', 'centre', 0.9 * G['strip'], (L('pos'), 'stri'),
                                             wrapping='none'))))
        else:
            k(mv, p1)
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
            k(mv, k(lt, k(lb, self.B.logo(el, G['barBadgeX'], mid, G['badgeH']))))
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
        k(mv, holder)
        # gap / interval: race and timed cells differ; the dim bar while unavailable. Every gap text box stops
        # GAP_CLEAR short of the code box (fix round 1). Race: P1's 'Interval' / 'Leader' and a retired row's 'Out' /
        # 'DSQ' / 'NC' at the drawing's label size (rNN_p1, rNN_out); every other race text at the number size
        # ('+2 LAPS' too: no leaf tells it apart). Timed: label and number sizes are the same; lap times at
        # LAP_CAP_T.
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
                lap = LAP_CAP * p
                if qa is not None and qb is not None:
                    gx = self.text(f'{r}_{key}x', rx, mid + num['cap'] / 2, num['cap'], 'OSD_24_regular', 'right', box,
                                   gap, textcase='mixed')
                    if self.game:
                        # while the column holds lap times (leaf laps, the spectator's Gap Fastest Lap) the
                        # text at LAP_CAP, so a lap time fits the box unsqueezed; gaps keep the number size
                        k(g, k(qa, k(qb, k(self.shown_null(f'{r}_{key}n', vis=leaf('laps'), neg=True), gx),
                                         k(self.shown_null(f'{r}_{key}m', vis=leaf('laps')),
                                           self.text(f'{r}_{key}xl', rx, mid + lap / 2, lap, 'OSD_24_regular', 'right',
                                                     box, gap, textcase='mixed')))))
                    else:
                        k(g, k(qa, k(qb, gx)))
                for sfx, v in (('l', L('p1')), ('o', L('out'))):
                    t = self.text(f'{r}_{key}{sfx}', rx, mid + lc / 2, lc, 'OSD_24_regular', 'right', box, gap,
                                  textcase='mixed', vis=v)
                    if sfx == 'l' and self.game:
                        # docs/spectator-ui.md 10.4: while the gap column holds lap times (leaf laps, the
                        # spectator's Gap Fastest Lap) P1's time at the size of every other row's (LAP_CAP)
                        ql = self.shown_null(f'{r}_{key}q', vis=leaf('laps'), neg=True)
                        qt = self.shown_null(f'{r}_{key}t', vis=leaf('laps'))
                        k(g, k(ql, t), k(qt, self.text(f'{r}_{key}lt', rx, mid + lap / 2, lap, 'OSD_24_regular',
                                                       'right', box, gap, textcase='mixed', vis=L('p1'))))
                    else:
                        k(g, t)
            else:
                # the lap time flash (leaves.md v8): while rNN_pb (a personal best) or rNN_ob (the session's
                # best) the DLL writes the car's new lap time into rNN_gap; a green or purple copy of the text shows
                # it and the white text hides (nested nulls give the AND).
                # every lap time at LAP_CAP_T, so "1:06.506" fits the box unsqueezed: P1's best lap (rNN_p1),
                # the flash's new lap and, with the spectator's Gap Fastest Lap (leaf flap), every row's (three
                # decimals); the gaps ("+0.029") and the other rows' words keep the number size
                lt = LAP_CAP_T * p
                fa = self.shown_null(f'{r}_{key}f', vis=L('pb'), neg=True)
                fb = self.shown_null(f'{r}_{key}h', vis=L('ob'), neg=True)
                if fa is not None and fb is not None:
                    nf = self.shown_null(f'{r}_{key}n', vis=leaf('flap'), neg=True)
                    if nf is not None:
                        na = self.shown_null(f'{r}_{key}a', vis=L('p1'), neg=True)
                        if na is not None:
                            k(nf, k(na, self.text(f'{r}_{key}x', rx, mid + num['cap'] / 2, num['cap'],
                                                  'OSD_24_regular', 'right', box, gap, textcase='mixed')))
                        k(nf, self.text(f'{r}_{key}xp', rx, mid + lt / 2, lt, 'OSD_24_regular', 'right', box, gap,
                                        textcase='mixed', vis=L('p1')))
                        k(fb, nf)
                    k(fb, self.text(f'{r}_{key}xl', rx, mid + lt / 2, lt, 'OSD_24_regular', 'right', box, gap,
                                    textcase='mixed', vis=leaf('flap')))
                    k(g, k(fa, fb))
                for sfx in ('pb', 'ob'):
                    k(g, self.text(f'{r}_{key}{sfx}', rx, mid + lt / 2, lt, 'OSD_24_regular', 'right', box, gap,
                                   textcase='mixed', vis=L(sfx), colour=FLASH_HEX[sfx]))
            k(g, self.quad(f'{r}_{key}na', 'na', (rx - 0.36 * p, mid - 0.03 * p, rx, mid + 0.03 * p),
                           LAYER['mark'], vis=L('gna')))
            k(mv, g)
        # tyre: one baked letter per compound (tyre colours), the dim bar while unavailable
        ty = self.shown_null(r + '_ty', vis=leaf('tyres'))
        if ty is not None:
            for c in 'SMHIW':
                k(ty, self.sprite(f'{r}_t{c}', 'ty_' + c, vis=L('t' + c)))
            k(ty, self.quad(r + '_tna', 'na', (G['tyreX'] - 0.12 * p, mid - 0.03 * p, G['tyreX'] + 0.12 * p,
                                               mid + 0.03 * p), LAYER['mark'], vis=L('tna')))
            # the spectator's Detail cell (docs/spectator-ui.md 10.4; detail()): the text the DLL writes
            # for the game's spectator menu's Detail, "" otherwise (nothing drawn)
            if self.game:
                self.detail(ty, r, L)
            k(mv, ty)
        # side boxes right of the panel: '!' penalty first, then 'P' (pit lane) in the next slot
        sd = G['side']
        top = mid + sd['dy'] - sd['h'] / 2
        slot = lambda j: W + j * (sd['w'] + sd['gap'])   # noqa: E731
        k(mv, self.sprite(r + '_pen', 'pen', slot(0), top, vis=L('pen')))
        q0 = self.shown_null(r + '_q0', vis=L('pen'), neg=True)
        q1 = self.shown_null(r + '_q1', vis=L('pen'))
        if q0 is not None:
            k(mv, k(q0, self.sprite(r + '_pit0', 'pit', slot(0), top, vis=L('pit'))))
        if q1 is not None:
            k(mv, k(q1, self.sprite(r + '_pit1', 'pit', slot(1), top, vis=L('pit'))))
        # the race's fastest lap (rNN_fl): a purple box with a stopwatch in the next free side slot, after the
        # '!' and the 'P' (nested nulls pick the slot: neither, one of them, both)
        for j, (npen, npit, s) in enumerate(((True, True, 0), (False, True, 1), (True, False, 1), (False, False, 2))):
            fa = self.shown_null(f'{r}_f{j}a', vis=L('pen'), neg=npen)
            fb = self.shown_null(f'{r}_f{j}b', vis=L('pit'), neg=npit)
            if fa is not None and fb is not None:
                k(mv, k(fa, k(fb, self.quad(f'{r}_fl{j}', 'fl', (slot(s), top, slot(s) + sd['w'], top + sd['h']),
                                             LAYER['mark'], vis=L('fl')))))
        # retired / DNF / DSQ / NC: the row at about 50 % (a half-opaque layer in the row's colours over it)
        out = self.shown_null(r + '_out', vis=L('out'))
        if out is not None:
            k(out, self.quad(r + '_os', 'dims', (0.0, 0.0, G['strip'], p), LAYER['dim']),
              self.quad(r + '_op', 'dimp', (G['strip'], 0.0, W, p), LAYER['dim']))
            k(mv, out)
        if self.game:
            k(row, self.debug(i))
        return row

    def detail(self, ty, r, L):
        """The spectator's Detail cell in the tyre cell `ty` (live tower only; leaves.md v10, rNN_det, rNN_dup,
        rNN_ddn): Penalties "5s", "10s", "DT", "SG"; Position Change the places gained or lost since the grid ("3") or
        "-"; Stops the game's count or "-"; "" otherwise. Sizes and fit: DET_CAP's comment.
        - races (tt_rNN_dr, shown while race): the white text centred on the tyre letter while neither rNN_dup nor
          rNN_ddn (nested nulls give the AND); while one of them, a green (P.up) or red (P.down) triangle and the
          count in the same colour as one group: an eCentre on the tyre letter over a left-to-right stacker (the
          header's lap line and the yellow block's pattern, both seen in game). The stacker starts where a one-digit
          group would be centred, in case the eCentre keeps its children in place;
        - timed sessions (tt_rNN_dm, shown while timed): the white text at DET_CAP_T, centred in their cell."""
        G, p, W, mid = self.G, self.G['p'], self.G['w'], self.G['mid']
        k = self.B.kids
        tx, rr, rt = G['tyreX'], G['num']['race']['r'], G['num']['timed']['r']
        det = (L('det'), 'stri')
        rc = self.shown_null(r + '_dr', vis=leaf('race'))
        cap = DET_CAP * p
        box = 2.0 * (min(tx - rr, W - tx) - DET_CLEAR * p)
        wa = self.shown_null(r + '_dwa', vis=L('dup'), neg=True)
        wb = self.shown_null(r + '_dwb', vis=L('ddn'), neg=True)
        k(rc, k(wa, k(wb, self.text(r + '_dt', tx, mid + cap / 2, cap, 'OSD_24_regular', 'centre', box, det,
                                    textcase='mixed'))))
        aw, ah = DET_ARROW[0] * p, DET_ARROW[1] * p
        one = aw + DET_GAP * p + DIGIT_CAPS * cap          # a one-digit group's width
        for key, sprite, col in (('dup', 'pcu', self.det_hex['up']), ('ddn', 'pcd', self.det_hex['down'])):
            s = self.sp[sprite]
            assert abs((s['x1'] - s['x0']) - aw) < 0.02 and abs((s['y1'] - s['y0']) - ah) < 0.02, (sprite, s, aw, ah)
            grp = self.shown_null(f'{r}_{key}', vis=L(key))
            line = self.B.centre(self.n(f'{r}_{key}c'), tx, 0.0)
            stk = self.B.stacker(self.n(f'{r}_{key}s'), -one / 2, mid + cap / 2, 'l', DET_GAP * p)
            k(stk, self.quad(f'{r}_{key}a', sprite, (0.0, -cap / 2 - ah / 2, aw, -cap / 2 + ah / 2), LAYER['mark']),
              self.text(f'{r}_{key}t', 0.0, 0.0, cap, 'OSD_24_regular', 'left', 3.0 * DIGIT_CAPS * cap, det,
                        textcase='mixed', colour=col))
            k(rc, k(grp, k(line, stk)))
        k(ty, rc)
        tm = self.shown_null(r + '_dm', vis=leaf('timed'))
        capt = DET_CAP_T * p
        k(tm, self.text(r + '_dtt', (rt + W) / 2, mid + capt / 2, capt, 'OSD_24_regular', 'centre',
                        (W - rt) - 2.0 * DET_CLEAR * p, det, textcase='mixed'))
        k(ty, tm)

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
        static template nodes hide it in game). The live tower's cards and rows: the clipped body (body());
        the HUD editor's copy keeps the older tree (the cards in the header, the rows under it)."""
        G = self.G
        root = self.B.null(ROOT if self.game else PV_ROOT, hidden=self.game)
        stack = self.B.stacker(self.n('tt_stack'), 0.0, 0.0, 't', 0.0)
        if not self.game:
            rows = self.null('tt_rows', 0.0, G['sep'] + G['band'])     # stored where the stacker puts it (header, no block)
            self.B.kids(rows, *[self.row(i) for i in range(NROWS)])
            self.B.kids(stack, self.header(), rows)
            return self.B.kids(root, stack)
        rows = self.null('tt_rows')                                     # stored where tt_bstk puts it (no card)
        self.B.kids(rows, *[self.row(i) for i in range(NROWS)])
        top = self.header()
        cards = self.shown_null('tt_cards', vis=leaf('hdr'))
        self.B.kids(cards, *[c for c in self.cards(0.0) if c is not None])
        self.B.kids(stack, top, self.body(cards, rows, self.ghosts()))
        return self.B.kids(root, stack, self.trial())


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
              debug_dropzone=False, mods_bytes=None):
    """the bottom cap scene with the live tower (tt_root) and the HUD editor's copy (tp_root); mods_bytes: dial_mods.idf
    (the clip window's model) -> (bytes, live Tower, preview Tower)"""
    assert mods_bytes is not None, 'build_cap needs dial_mods.idf (the clip window)'
    B = Scene(cap_bytes, dial_bytes, lapc_bytes, stacked_bytes, embs, row_bytes, logo_bytes, cat_bytes, mods_bytes)
    stock_ids = {e.path: e.element_id for e, _ in B.idf.scenes[0].root.walk()}
    T = Tower(B, meta, preview_state(), debug_dropzone)
    B.root['children'].items.append(T.build())
    PV = Tower(B, meta, preview_state(), mode='preview')
    B.root['children'].items.append(PV.build())
    assert not any(B.hidden[nm] for nm in B.names if nm.startswith('tp_')), 'the editor copy hides nothing'
    assert not any(nm.startswith('tp_') for rec in T.recs + T.trecs for nm in [rec['el']]), 'the editor copy is never bound'
    _ids_and_check(B.idf, B.entry, stock_ids, B.names)
    walked = [e for e, _ in I.Idf(B.idf.to_bytes()).scenes[0].root.walk()]
    # every element built is in the written scene (an element dropped from the tree stops the build). The only
    # exception, as without animations: in the editor copy, a fastest-lap slot's null pair where the preview state creates one
    # half (tp_rNN_fJa / fJb, empty) and the pair is left out
    lost = sorted(B.names - {e.name for e in walked})
    assert not [nm for nm in lost if not re.fullmatch(r'tp_r\d\d_f\d[ab]', nm)], ('built elements missing from the '
                                                                                    'scene', len(lost), lost[:5])
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
    T.body_info = check_body(B, T)
    return B.idf.to_bytes(), T, PV


def check_body(B, T):
    """the live tower's body as built, at rest. The tree: tt_stack holds tt_top and
    tt_clipn; tt_clipn > tt_clip (eWindow) > tt_clipo > tt_xin > tt_xout (anim nulls, nothing else on the way) >
    tt_ghost, then tt_bstk (tt_cards, tt_rows). The window's rect from tt_clipn's origin down, tt_clipo back at that origin (z
    too). Every drawn part of the cards and rows inside the window (rows under the tallest card too), nothing above its
    top edge; each card from that edge down, its height its size's BODY_PITCHES (the clips' start offsets); each copy the
    card's parts one card height higher, part by part, with the copy's own leaves only. HUD units, y down.
    -> info for tower_info.json"""
    p, KT_ = T.G['p'], KT
    root = H._find(B.root, ROOT)
    els = {}

    def walk(o, x, y, z, s, path):
        nm, pos, sc = I._val(o.get('name')), o['position'].value, o['scale'].value
        ax, ay, az = x + s * pos[0], y + s * pos[1], z + pos[2]
        els[nm] = {'o': o, 'path': path + [nm], 'x': ax, 'y': ay, 'z': az, 's': s, 'sc': sc,
                   'type': I._val(o.get('typeName')), 'kids': [I._val(c.get('name')) for c in o['children'].items]}
        for c in o['children'].items:
            walk(c, ax, ay, az, s * sc[0], path + [nm])
    walk(root, 0.0, 0.0, 0.0, 1.0, [])
    want = {'tt_stack': ['tt_top', 'tt_clipn'], 'tt_clipn': ['tt_clip'], 'tt_clip': ['tt_clipo'], 'tt_clipo': ['tt_xin'],
            'tt_xin': ['tt_xout'], 'tt_xout': ['tt_ghost', 'tt_bstk'], 'tt_bstk': ['tt_cards', 'tt_rows']}
    for nm, kids in want.items():
        assert els[nm]['kids'] == kids, ('body tree', nm, els[nm]['kids'])
    assert els['tt_clip']['type'] == 'eWindow' and els['tt_bstk']['type'] == 'eStacker'
    assert I.get_param(els['tt_bstk']['o'], 'stackerType') == 't' and abs(I.get_param(els['tt_bstk']['o'], 'gap')) < 1e-12
    for nm in ('tt_xin', 'tt_xout'):
        an = els[nm]['o']['anims'].items
        assert nm in B.anims and len(an) == 1 and an[0]['asset'].value == f'{CAP}/{nm}?context=animation', nm
        assert els[nm]['o']['position'].value[:3] == [0.0, 0.0, 0.0] and list(els[nm]['sc'][:3]) == [1.0, 1.0, 1.0]
    o0 = els['tt_clipn']

    def hud(e, dx=0.0, dy=0.0):                    # scene point -> HUD units from tt_clipn's origin (y down)
        return (e['x'] + dx - o0['x']) / KT_, -(e['y'] + dy - o0['y']) / KT_
    w, l = I.get_param(els['tt_clip']['o'], 'width'), I.get_param(els['tt_clip']['o'], 'length')
    cx, cy = hud(els['tt_clip'])
    rect = (cx - w / 2 / KT_, cy - l / 2 / KT_, cx + w / 2 / KT_, cy + l / 2 / KT_)
    assert all(abs(a - b) < 1e-4 for a, b in zip(rect, T.clip)) and abs(rect[1]) < 1e-4, (rect, T.clip)
    bx, by = hud(els['tt_clipo'])
    assert abs(bx) < 1e-9 and abs(by) < 1e-9 and abs(els['tt_clipo']['z'] - o0['z']) < 1e-12, ('tt_clipo', bx, by)

    def parts(top):                                # every drawn part under element `top`: (name, kind, rect / anchor)
        out = []
        for nm, e in els.items():
            if top not in e['path'][:-1]:
                continue
            o = e['o']
            if e['type'] == 'eNull' and o['geoms'].items:
                qw, qh = B.mesh_w * e['sc'][0] * e['s'], B.mesh_h * e['sc'][2] * e['s']
                qx, qy = hud(e)
                out.append((nm, 'quad', (qx - qw / 2 / KT_, qy - qh / 2 / KT_, qx + qw / 2 / KT_, qy + qh / 2 / KT_),
                            o['geoms'].items[0]['materialid'].value, I.get_param(o, 'eLayer.layer')))
            elif e['type'] == 'eXRef':
                ss = e['s'] * e['sc'][0]
                qx, qy = hud(e, ss * B.logo_c[0], ss * B.logo_c[1])
                h2 = ss * B.logo_side / 2 / KT_
                out.append((nm, 'logo', (qx - h2, qy - h2, qx + h2, qy + h2), None, None))
            elif e['type'] == 'eText':
                qx, qy = hud(e)
                out.append((nm, 'text', (qx, qy, qx, qy), tuple(I.get_param(o, k) for k in (
                    'style', 'halign', 'boxWidth', 'wrapping', 'textcase')), e['s']))
        return out
    m = 0.5 * p
    drawn = parts('tt_bstk')
    rows = [d for d in drawn if 'tt_rows' in els[d[0]]['path']]
    cards = [d for d in drawn if 'tt_cards' in els[d[0]]['path']]
    assert len(rows) + len(cards) == len(drawn) and rows and cards
    tallest = max(BODY_PITCHES.values()) * p
    row_names = {d[0] for d in rows}
    for nm, kind, r, *_ in drawn:
        low = r[3] + (tallest if nm in row_names else 0.0)
        assert rect[0] + m <= r[0] and r[2] <= rect[2] - m and r[1] >= -1e-6 and low <= rect[3] - m, \
            ('a part outside the clip window', nm, [round(v, 3) for v in r], [round(v, 3) for v in rect])
    # the cards from the window's top edge down, each as high as its size says; the copies part by part
    heights, ncopy = {}, 0
    for key in CARDS:
        mine = [d for d in cards if f'tt_{key}' in els[d[0]]['path']]
        q = [d for d in mine if d[1] == 'quad']
        top_, bot = min(d[2][1] for d in q), max(d[2][3] for d in q)
        h = T.sp[key]['y1'] - T.sp[key]['y0']
        assert abs(top_) < 1e-6 and abs(bot - h) < 1e-6, ('card extent', key, top_, bot, h)
        assert abs(h / p - BODY_PITCHES[CARD_SIZE[key]]) < 1e-9, ('card height vs its clip', key, h / p)
        assert all(-1e-6 <= d[2][1] and d[2][3] <= h + 1e-6 for d in mine), ('card part outside its card', key)
        heights[key] = h / p
        copy = {d[0]: d for d in parts(f'tt_gh_{key}')}
        assert len(copy) == len(mine), ('copy parts', key, len(copy), len(mine))
        for nm, kind, r, a, b in mine:
            g = copy[nm.replace('tt_', 'tt_gh_', 1)]
            assert g[1] == kind and g[3] == a and g[4] == b, ('copy part differs', nm)
            assert all(abs(gv - (rv - (h if j % 2 else 0.0))) < 1e-6 for j, (gv, rv) in enumerate(zip(g[2], r))), \
                ('copy part not one card height up', nm, g[2], r)
            ncopy += 1
    # bindings: the copies read only the copy leaves; hidden in the scene until the template shows them
    gh = {r['el']: r for r in T.recs if r['el'].startswith('tt_gh_') or r['el'] == 'tt_ghost'}
    copy_leaves = {leaf(f'gh_{k}') for k in CARDS} | {leaf('gh_ysec'), leaf('gh_ysna'), leaf('hdr')}
    for el, r in gh.items():
        dbs = ([r['vis'][0]] if r['vis'] else []) + ([r['text'][0]] if r['text'] and r['text'][0] != '=' else [])
        assert set(dbs) <= copy_leaves, ('a copy binds a live leaf', el, dbs)
    for key in CARDS:
        assert gh[f'tt_gh_{key}']['vis'] == (leaf(f'gh_{key}'), False) and B.hidden[f'tt_gh_{key}'], key
    assert gh['tt_gh_ysn']['text'] == (leaf('gh_ysec'), 'stri') and gh['tt_gh_ysn']['vis'] == (leaf('gh_ysna'), True)
    assert gh['tt_gh_ysna']['vis'] == (leaf('gh_ysna'), False) and gh['tt_ghost']['vis'] == (leaf('hdr'), False)
    cr = [r for r in T.recs if r['el'] == 'tt_cards']
    assert len(cr) == 1 and cr[0]['vis'] == (leaf('hdr'), False) and not B.hidden['tt_cards']
    return {'window_p': [round(v / p, 4) for v in rect], 'card_heights_p': heights, 'copy_parts': ncopy,
            'drawn_parts': len(drawn), 'rows_bottom_p': round(max(d[2][3] for d in rows) / p, 4)}


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


def lap_counter_visible():
    """visible <- NOT hud_tt_show: hidden while the standings or the Time Trial board show, whose header
    carries the lap line; true while the leaf is absent, so the counter is the game's own whenever the tower is off or
    the DLL is missing"""
    return H._bool_prop(True, leaf('show'), True)


def lap_counter_nodes():
    """hud_lap_counter: one group 'tt_lapc' whose children hide LAPC_HIDE and the panel's wrappers: elements no
    stock node targets"""
    kids = [U.node('v_tt_lapc_' + el, 'UIGP', [('visible', lap_counter_visible())], layout=[el],
                   behav=U.GROUP_BEHAVIOURS) for el in LAPC_HIDE + tuple(LAPC_WRAPPER + p for p in LAPC_WRAP)]
    return U.node('tt_lapc', 'UIGP', [], kids=kids, behav=U.GROUP_BEHAVIOURS)


def build_lapc_scene(lapc_bytes):
    """the lap counter scene with each LAPC_WRAP part in a new null of its own (LAPC_WRAPPER + part) at the
    part's place in Scene Root's children (order kept), at the origin (positions kept). Every stock element keeps its
    name, so the stock template nodes still find their parts (nodeidlookup holds name hashes); element ids follow the
    stock rule (djb2 of the dotted path): unchanged for every element outside a wrapper."""
    idf = I.Idf(lapc_bytes)
    entry = idf.scenes[0].entry
    root = entry['scene']
    assert idf.scenes[0].name == I.component_id(LAPC), 'not the stock lap counter scene'
    stock_ids = {e.path: e.element_id for e, _ in idf.scenes[0].root.walk()}
    kids = root['children'].items
    model = [c for c in kids if I._val(c.get('name')) == 'holder_formation']
    assert len(model) == 1 and not model[0]['geoms'].items, 'lap counter: no plain holder null to copy'
    for part in LAPC_WRAP:
        at = [i for i, c in enumerate(kids) if I._val(c.get('name')) == part]
        assert len(at) == 1, ('lap counter: panel part not a single child of Scene Root', part)
        name = LAPC_WRAPPER + part
        assert H._find(root, name) is None, ('lap counter: wrapper exists', name)
        w = I.clone_node(model[0])
        w.set('name', Val('stri', name))
        H._param(w, 'guid', H._guid(name))
        w.set('position', H._vec((0.0, 0.0, 0.0)))
        w.set('scale', H._vec((1.0, 1.0, 1.0)))
        w.set('rotation', Val('quat', [-0.0, -0.0, 0.0, -1.0]))
        for key in ('children', 'anims', 'geoms'):
            if w.get(key) is not None:
                w.set(key, Arr([], w[key].tag))
        pa = w['params']
        pa.items = [it for it in pa.items if I._val(it.get('name')) not in ('isHidden', 'eAnimationGroup.AnimGroup')]
        w['children'].items.append(kids[at[0]])
        kids[at[0]] = w
    ids = []
    for kid in root['children'].items:
        I.recompute_ids(kid, I._val(kid.get('name')), ids)
    I.relookup(entry)
    out = idf.to_bytes()
    back = I.Idf(out).scenes[0]
    after = {e.path: e.element_id for e, _ in back.root.walk()}
    kept = {k: v for k, v in stock_ids.items() if k.split('.')[0] not in LAPC_WRAP}
    assert all(after.get(k) == v for k, v in kept.items()), 'lap counter: a stock element id changed'
    assert len(set(ids)) == len(ids), 'lap counter: elementId collision'
    names = [e.name for e, _ in back.root.walk()]
    stock_names = [e.name for e, _ in I.Idf(lapc_bytes).scenes[0].root.walk()]
    assert sorted(names) == sorted(stock_names + [LAPC_WRAPPER + p for p in LAPC_WRAP]), 'lap counter: names'
    return out


def _drawn_outside(idf, hidden):
    """the elements that draw (a mesh, a text, a referenced unit) and lie in none of `hidden`"""
    trail, loose = [], []
    for e, d in idf.scenes[0].root.walk():
        del trail[d:]
        trail.append(e.name)
        g = e.obj.get('geoms')
        draws = (g is not None and len(g.items) > 0) or e.type in ('eText', 'eXRef')
        if draws and not hidden & set(trail):
            loose.append(e.name)
    return loose


def _stock_targets(root, els):
    """{element name: [stock nodes whose layout chain ends there]} below a template node. A chain through an eXRef of
    the scene (logo: car_category_logo > logo_icon) targets an element of the referenced unit, not one of these."""
    targets = {}

    def walk(n):
        for path in n.items[N.LAYOUT].items:
            chain = [b['debugName'].value for b in path.items]
            if not chain or chain == ['Scene Root']:
                continue
            assert chain[0] in els, ('a stock chain outside the scene', N.name(n), chain)
            if len(chain) > 1 and els[chain[0]].type == 'eXRef':
                continue
            assert all(c in els for c in chain), ('a stock chain outside the scene', N.name(n), chain)
            targets.setdefault(chain[-1], []).append(n)
        for c in N.children(n):
            walk(c)
    walk(root)
    return targets


def check_lap_counter(lapc_bytes, built_bytes, stock_ui_bytes):
    """The lap counter parts the tower hides (the wrapper rule): in the built scene every part that draws (a mesh, a text, a
    referenced unit) lies in a hidden element (LAPC_HIDE or a wrapper); no stock node targets a hidden element; each
    hidden element is unique and shown by default; every stock node's target still resolves to one element of its
    name (each panel part is still a stock node's target). -> (stock parts hidden, wrappers)"""
    idf = I.Idf(lapc_bytes)
    top = [I._val(c.get('name')) for c in idf.scenes[0].entry['scene']['children'].items]
    assert sorted(top) == sorted(LAPC_STOCK_KIDS), ('lap counter scene changed', top)
    built = I.Idf(built_bytes)
    wrappers = [LAPC_WRAPPER + p_ for p_ in LAPC_WRAP]
    hidden = set(LAPC_HIDE) | set(wrappers)
    assert len(hidden) == len(LAPC_HIDE) + len(LAPC_WRAP), 'a part hidden twice'
    names = [e.name for e, _ in built.scenes[0].root.walk()]
    els = {e.name: e for e, _ in built.scenes[0].root.walk()}
    assert all(names.count(nm) == 1 for nm in names), 'lap counter: an element name is not unique'
    for nm in hidden:
        assert names.count(nm) == 1, ('lap counter part missing or not unique', nm)
        assert not I.get_param(els[nm].obj, 'isHidden'), ('hidden by default', nm)
    for p_ in LAPC_WRAP:
        w = els[LAPC_WRAPPER + p_]
        assert [c.name for c in w.children] == [p_], ('wrapper holds exactly its part', p_)
        assert list(w.obj['position'].value[:3]) == [0.0, 0.0, 0.0], ('wrapper not at the origin', p_)
    loose = _drawn_outside(built, hidden)
    assert not loose, ('lap counter parts that draw while the tower shows', loose)
    root = H._node_at(Pkg(stock_ui_bytes).root, LAPC_TEMPLATE)
    targets = _stock_targets(root, els)
    shared = [(part, [N.name(n) for n in targets[part]]) for part in sorted(hidden) if part in targets]
    assert not shared, ('stock nodes target these lap counter parts: a tower node there would not hold', shared)
    for part in LAPC_WRAP:
        assert part in targets, ('lap counter panel part: no stock node targets it any more', part)
    return len(LAPC_HIDE), len(LAPC_WRAP)


def flag_message_node(visible=None):
    """one group 'tt_flagm' under a flag message's message node (whose layout is the flag message scene's root) with
    one child that hides FLAGM_PART: in hud_left_notification_dynamic while hud_tt_show; visible: another
    switch (the spectator screen's own flag message, while hud_tt_on)"""
    kid = U.node('v_tt_flagm_' + FLAGM_PART, 'UIGP',
                 [('visible', lap_counter_visible() if visible is None else visible)], layout=[FLAGM_PART],
                 behav=U.GROUP_BEHAVIOURS)
    return U.node(FLAGM_NODE, 'UIGP', [], kids=[kid], behav=U.GROUP_BEHAVIOURS)


def flag_scene_check(scene_bytes):
    """the stock flag message scene: FLAGM_PART unique, shown by default, the holder of everything the scene draws.
    -> elements it holds that draw"""
    idf = I.Idf(scene_bytes)
    assert idf.scenes[0].name == I.component_id(FLAGM_SCENE), 'not the stock flag message scene'
    names = [e.name for e, _ in idf.scenes[0].root.walk()]
    els = {e.name: e for e, _ in idf.scenes[0].root.walk()}
    assert names.count(FLAGM_PART) == 1, ('flag message: part missing or not unique', FLAGM_PART)
    assert not I.get_param(els[FLAGM_PART].obj, 'isHidden'), 'flag message part hidden by default'
    loose = _drawn_outside(idf, {FLAGM_PART})
    assert not loose, ('flag message parts outside', FLAGM_PART, loose)
    return len(_drawn_outside(idf, set()))


def check_flag_message(scene_bytes, stock_ui_bytes):
    """FLAGM_PART: unique in the flag message scene, shown by default, the holder of everything the scene draws, the
    target of no stock node of the element; the message node targets the scene's root. -> elements it holds that draw"""
    drawn = flag_scene_check(scene_bytes)
    p = Pkg(stock_ui_bytes)
    msg = H._node_at(p.root, FLAGM_TEMPLATE)
    assert H._type(msg) == 'F1HM', ('flag message node type', H._type(msg))
    lay = [[b['debugName'].value for b in g.items] for g in msg.items[N.LAYOUT].items]
    assert lay == [['Scene Root']], ('flag message node layout', lay)
    top = H._node_at(p.root, FLAGM_TEMPLATE.split('.')[0])
    hits = []

    def walk(n):
        for path in n.items[N.LAYOUT].items:
            chain = [b['debugName'].value for b in path.items]
            if FLAGM_PART in chain:
                hits.append((N.name(n), chain))
        for c in N.children(n):
            walk(c)
    walk(top)
    assert not hits, ('stock nodes target the flag message part', hits)
    return drawn


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
        if rec.get('tcol'):
            props.append(('colourOverride', U.prop('rgba', rec['tcol'])))   # static, as the stock
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
        if rec.get('tcol'):
            props.append(('colourOverride', U.prop('rgba', rec['tcol'])))   # static, as the stock
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


def anim_nodes(T, base):
    """the animations' template nodes for the tower under tt_ctl `base`, the same in the
    HUD, replay and spectator templates:
    - under tt_host_n, per row: a UIXA per anim null (tt_xa_rNN_<null>: signal-driven like the stock rival-state
      players, no props) and a UIMO per faded text (tt_mo_rNN_<text>: the stock fade-in's props on FADE_CURVE;
      overrideComplete -> its own deactivateOverride, as stock);
    - under tt_ctl, per row: an MVCD per code leaf (tt_an_rNN_<code>, leaves.md v12) with one event, '1': its motion.
      xuK / xdK put the other slide null at rest and play the null's K-row segment (goToFraction(a) +
      playToFraction(b)); xeu / xed play the arrow entry; xnf fades the number in, xff the flash copies; xrs puts the row
      at rest (every clip at fraction 1, every fade off). No '0' event: a code going false sends nothing. No trigger
      and no query between decisions: each decision fires on its own leaf (a registered decision fires when hud::set
      writes its leaf: rows moved by themselves [game]), and no two decisions of one packet touch the same node,
      so their order does not matter.
    - tt_ctl's trigger registers and queries every code decision (at rest every code is false: the query sends
      nothing), untrigger unregisters them.
    -> (host nodes, decision nodes, trigger signals, untrigger signals, info)"""
    host = f'{base}.tt_host_n'
    xa_behav = ('NBFC', 'NBXA', 'NBEL', 'NBDC', 'NBMG', 'NBVM', 'NBAN', 'NBAC', 'NBOS', 'NBMO')   # stock UIXA
    mo_behav = ('NBEL', 'NBMG', 'NBOS', 'NBXA')                                                   # stock UIMO
    curve = U.djb2(ANIM_CURVE)
    want = {f'tt_r{i:02d}_{nm}' for i in range(NROWS) for nm in ANIM_NULLS} | {f'tt_{nm}' for nm in BODY_NULLS}
    assert set(T.B.anims) == want and len(T.B.anims) == len(want), 'the scene\'s anim nulls'
    hosted, decisions, trig, untrig, leaves, nsig = [], [], [], [], [], 0
    for i in range(NROWS):
        r = f'r{i:02d}'
        xa = {nm: f'{host}.tt_xa_{r}_{nm}' for nm in ANIM_NULLS}
        mo = {t: f'{host}.tt_mo_{r}_{t}' for t in ANIM_FADES}
        for nm in ANIM_NULLS:
            hosted.append(U.node(f'tt_xa_{r}_{nm}', 'UIXA', [], layout=[f'tt_{r}_{nm}'], behav=xa_behav))
        for t in ANIM_FADES:
            assert f'tt_{r}_{t}' in T.B.names, ('a faded text is not in the scene', r, t)
            hosted.append(U.node(f'tt_mo_{r}_{t}', 'UIMO', [
                ('Cascade', U.prop('bool', True)), ('ParameterName', U.prop('stri', 'Alpha')),
                ('BlendType', U.prop('stri', 'Multiplicative')), ('Value', U.prop('fp32', 1.0)),
                ('StartingValue', U.prop('fp32', 0.0)), ('AnimationCurve', U.prop('stri', FADE_CURVE))],
                events=[U.event('overrideComplete', [U.sig(mo[t], 'deactivateOverride', 'overrideComplete')])],
                layout=[f'tt_{r}_{t}'], behav=mo_behav))

        def go(nm, f):
            return U.sig(xa[nm], 'goToFraction', '1', {'value': float(f)})

        def play(nm, f):
            return U.sig(xa[nm], 'playToFraction', '1', {'curveName': curve, 'value': float(f)})

        def fade(t, on):
            if on:
                return U.sig(mo[t], 'activateOverride', '1', {'overrideInstant': False})
            return U.sig(mo[t], 'deactivateOverride', '1')

        sigs = {'xrs': [go(nm, 1.0) for nm in ANIM_NULLS] + [fade(t, False) for t in ANIM_FADES],
                'xeu': [go('au', ANIM_ENTRY[0]), play('au', ANIM_ENTRY[1])],
                'xed': [go('ad', ANIM_ENTRY[0]), play('ad', ANIM_ENTRY[1])],
                'xnf': [fade('pos', True)], 'xff': [fade('gtpb', True), fade('gtob', True)]}
        for key, nm, other in (('u', 'mu', 'md'), ('d', 'md', 'mu')):
            for k, (a, b) in ANIM_SEGS.items():
                sigs[f'x{key}{k}'] = [go(other, 1.0), go(nm, a), play(nm, b)]
        assert sorted(sigs) == sorted(ANIM_CODES)
        # the codes one packet can hold (a slide, its entry, the fades; xrs always alone) touch no node twice
        for slide in [c for c in ANIM_CODES if c[1] in 'ud' and c[2] in '123']:
            seen = {}
            for c in (slide, 'xeu' if slide[1] == 'u' else 'xed', 'xnf', 'xff'):
                for sg in sigs[c]:
                    to = sg['to_object_name'].value
                    assert seen.setdefault(to, c) == c, ('two codes of one packet touch', to, seen[to], c)
        for c in ANIM_CODES:
            an = f'tt_an_{r}_{c}'
            decisions.append(U.node(an, 'MVCD', [('dbEntry', U.prop('stri', leaf(f'{r}_{c}')))],
                                    events=[U.event('1', sigs[c])]))
            leaves.append(leaf(f'{r}_{c}'))
            trig += [U.sig(f'{base}.{an}', 'register', 'trigger'), U.sig(f'{base}.{an}', 'query', 'trigger')]
            untrig.append(U.sig(f'{base}.{an}', 'unregister', 'untrigger'))
        nsig += sum(len(sg) for sg in sigs.values()) + len(ANIM_FADES)
    # the header's card motion: a UIXA per body null (tt_xa_xin, tt_xa_xout), and per
    # header code (leaves.md v13) an MVCD tt_an_<code> with one event '1': kinK puts tt_xout at rest and plays tt_xin's
    # segment K (the card's height up, eased to rest), koutK the same on tt_xout (the card's height down), krs puts both
    # at rest. One code a packet, so no two decisions of one packet touch one node.
    hx = {nm: f'{host}.tt_xa_{nm}' for nm in BODY_NULLS}
    for nm in BODY_NULLS:
        hosted.append(U.node(f'tt_xa_{nm}', 'UIXA', [], layout=[f'tt_{nm}'], behav=xa_behav))

    def hgo(nm, f):
        return U.sig(hx[nm], 'goToFraction', '1', {'value': float(f)})

    def hplay(nm, f):
        return U.sig(hx[nm], 'playToFraction', '1', {'curveName': curve, 'value': float(f)})

    hsigs = {'krs': [hgo(nm, 1.0) for nm in BODY_NULLS]}
    for k, (a, b) in ANIM_SEGS.items():
        hsigs[f'kin{k}'] = [hgo('xout', 1.0), hgo('xin', a), hplay('xin', b)]
        hsigs[f'kout{k}'] = [hgo('xin', 1.0), hgo('xout', a), hplay('xout', b)]
    assert sorted(hsigs) == sorted(HEAD_CODES)
    for c in HEAD_CODES:
        an = f'tt_an_{c}'
        decisions.append(U.node(an, 'MVCD', [('dbEntry', U.prop('stri', leaf(c)))], events=[U.event('1', hsigs[c])]))
        leaves.append(leaf(c))
        trig += [U.sig(f'{base}.{an}', 'register', 'trigger'), U.sig(f'{base}.{an}', 'query', 'trigger')]
        untrig.append(U.sig(f'{base}.{an}', 'unregister', 'untrigger'))
    nsig += sum(len(sg) for sg in hsigs.values())
    info = {'host_nodes': len(hosted), 'decisions': len(decisions), 'signals': nsig, 'trigger': len(trig),
            'untrigger': len(untrig), 'leaves': leaves}
    return hosted, decisions, trig, untrig, info


def check_anim_leaves(leaves, contract):
    """every leaf the animation decisions read is a bool of the contract (leaves.md v12), each read once;
    and the header's codes too (v13)"""
    bad = [db for db in leaves if contract.get(db) != 'bool']
    if bad:
        raise SystemExit(f'animation decisions read leaves that are not contract bools: {bad[:6]}')
    assert len(leaves) == len(set(leaves)) == NROWS * len(ANIM_CODES) + len(HEAD_CODES), len(leaves)


def djb2(s):
    h = 5381
    for c in s.encode():
        h = (h * 33 + c) & 0xffffffff
    return h


VM_NAME = re.compile(rb'#?(view_model_data|ui_menu_data)\.([A-Za-z0-9_]+)')


def check_vm_hashes(ours, blobs):
    """the game keys view-model nodes by the djb2 hash of their name (Swofty re/db/subsystems/vm.md), so two
    names under one parent with one hash are one node: a write to either is a write to both (v11's rNN_st, rNN_u2 and
    rNN_tS). ours: the addon's leaf paths ('#view_model_data.hud_tt_...'); blobs: built templates and stock files whose
    view_model_data / ui_menu_data names count too. Stops the build when a group of names with one hash holds an
    addon name (hud_tt_ / hud_halo_). -> (names, groups of stock names alone)"""
    names = {}
    for db in ours:
        parent, _, nm = db.lstrip('#').partition('.')
        names.setdefault(parent, set()).add(nm)
    for blob in blobs:
        for m in VM_NAME.finditer(blob):
            names.setdefault(m.group(1).decode(), set()).add(m.group(2).decode())
    bad, stock_groups, total = [], 0, 0
    for parent, nms in names.items():
        total += len(nms)
        by = {}
        for nm in nms:
            by.setdefault(djb2(nm), []).append(nm)
        for g in by.values():
            if len(g) < 2:
                continue
            if any(nm.startswith(('hud_tt_', 'hud_halo_')) for nm in g):
                bad.append(f'{parent}: {" = ".join(sorted(g))}')
            else:
                stock_groups += 1
    if bad:
        raise SystemExit('view-model names that share a djb2 hash (one node in game):\n  ' + '\n  '.join(bad[:12]))
    return total, stock_groups


def check_anim_readback(got, base, info):
    """in the built tt_ctl, every signal to an animation node (tt_xa_, tt_mo_, tt_an_) and every
    animation decision's signal hits a node of tt_ctl by path and id; the counts as built. -> number of such signals"""
    paths = {}

    def walk(n, path):
        paths[path] = n
        for c in N.children(n):
            if N.is_node(c):
                walk(c, f'{path}.{N.name(c)}')
    walk(got, base)
    ours = (f'{base}.tt_host_n.tt_xa_', f'{base}.tt_host_n.tt_mo_', f'{base}.tt_an_')
    n = 0
    for path, node in paths.items():
        for slot in (N.COMMANDS, N.EVENTS):
            for c in node.items[slot].items:
                if not isinstance(c, Obj):
                    continue
                for s in c['signals'].items:
                    to = s['to_object_name'].value
                    if to.startswith(ours) or path.startswith(ours):
                        assert to in paths, ('animation signal without its node', path, to)
                        assert s['to_object'].value == paths[to].items[N.PROPS]['id'].value, ('target id', to)
                        assert s['to_pin'].value == N.djb2(s['to_pin_name'].value), ('pin id', to)
                        n += 1
    an = [p for p in paths if p.startswith(f'{base}.tt_an_')]
    xa = [p for p in paths if p.startswith(ours[0])]
    mo = [p for p in paths if p.startswith(ours[1])]
    assert len(an) == info['decisions'] and len(xa) + len(mo) == info['host_nodes'], (len(an), len(xa), len(mo))
    assert all(H._type(paths[p]) == 'MVCD' for p in an) and all(H._type(paths[p]) == 'UIXA' for p in xa)
    assert all(H._type(paths[p]) == 'UIMO' for p in mo)
    assert n == info['signals'] + info['trigger'] + info['untrigger'], (n, info)
    # no two children of one node of tt_ctl share a name hash (a node's nameId is the djb2 of its name; v11's
    # tt_an_rNN_st and tt_an_rNN_u2 shared one)
    kids = {}
    for path, node in paths.items():
        parent = path.rsplit('.', 1)[0] if path != base else None
        if parent is not None:
            kids.setdefault(parent, []).append(N.name(node))
    for parent, names in kids.items():
        hashes = [djb2(nm) for nm in names]
        assert len(set(hashes)) == len(hashes), ('children with one name hash', parent,
                                                 [nm for nm in names if hashes.count(djb2(nm)) > 1][:6])
    return n


def hook(node, cmd, sig):
    """append signal `sig` to stock command `cmd` of `node` (the replay and spectator screens' open and close
    start and stop the animation decisions, beside the stock's own decision triggers)"""
    c = [x for x in node.items[N.COMMANDS].items if isinstance(x, Obj) and x['commandName'].value == cmd]
    assert len(c) == 1, (N.name(node), cmd, len(c))
    to = sig['to_object_name'].value
    assert not any(s['to_object_name'].value == to for s in c[0]['signals'].items), ('already hooked', cmd, to)
    c[0]['signals'].items.append(sig)


def anim_profile(t):
    """the motion's progress at t seconds into a play (0 at 0, 1 at ANIM_PLAY): the broadcast's ease-out, an exponential
    with time constant ANIM_TAU scaled to end exactly at ANIM_PLAY; on its extension for t < 0"""
    return (1.0 - math.exp(-t / ANIM_TAU)) / (1.0 - math.exp(-ANIM_PLAY / ANIM_TAU))


def anim_keys(nm, pitch):
    """null nm's translation keys -> (fractions, y offsets in scene units, max error in row pitches). Per segment
    (a, b) of start offset A: a rest key, a key on the profile's extension just before a, then ANIM_KEYS + 1 keys from a
    to b at times spaced so that linear interpolation errs alike everywhere (closer where the motion bends most, at
    the start), then a rest key just after b. The error: the keys' straight lines against the profile, sampled.
    The body's nulls (BODY_NULLS) have the rows' segments, segment K starting BODY_PITCHES[K] pitches away."""
    segs = list(ANIM_SEGS.items()) if nm in ('mu', 'md') + BODY_NULLS else [(1, ANIM_ENTRY)]
    ts, vs = [0.0], [0.0]
    err = 0.0
    w = 1.0 - math.exp(-ANIM_PLAY / (2 * ANIM_TAU))
    for k, (a, b) in segs:
        amp = BODY_SIGN[nm] * BODY_PITCHES[k] if nm in BODY_NULLS else ANIM_ROWS[nm] * k
        span = b - a
        if ts[-1] < a - 2 * ANIM_EPS - 1e-9:
            ts.append(a - 2 * ANIM_EPS)
            vs.append(0.0)
        ts.append(a - ANIM_EPS)
        vs.append(amp * (1.0 - anim_profile(-ANIM_EPS / span * ANIM_PLAY)))
        seg_t = [-2 * ANIM_TAU * math.log(1.0 - (j / ANIM_KEYS) * w) for j in range(ANIM_KEYS + 1)]
        assert abs(seg_t[-1] - ANIM_PLAY) < 1e-9 and seg_t == sorted(seg_t)
        for t in seg_t:
            ts.append(a + span * t / ANIM_PLAY)
            vs.append(amp * (1.0 - anim_profile(t)) if t < ANIM_PLAY - 1e-12 else 0.0)
        for j in range(len(seg_t) - 1):
            t0, t1 = seg_t[j], seg_t[j + 1]
            v0, v1 = amp * (1.0 - anim_profile(t0)), amp * (1.0 - anim_profile(t1))
            for q in range(1, 20):
                t = t0 + (t1 - t0) * q / 20
                err = max(err, abs(v0 + (v1 - v0) * q / 20 - amp * (1.0 - anim_profile(t))))
        if b < 1.0:
            ts.append(b + ANIM_EPS)
            vs.append(0.0)
    assert ts == sorted(ts) and len(set(ts)) == len(ts) and ts[0] == 0.0 and abs(ts[-1] - 1.0) < 1e-12, nm
    assert vs[0] == 0.0 and vs[-1] == 0.0
    return ts, [v * pitch for v in vs], err


def anim_clips(tmpl_clip_bytes, strtab_bytes, names, pitch):
    """the anim nulls' clips (translation keys from anim_keys; rotation and scale at rest: the halo's clip form,
    halo_native._clip) and the cap scene's string table with their names appended after its own, sorted (as the
    halo's). pitch: the row pitch in scene units. -> (string table bytes, {name: (temp, syst)}, key info)"""
    st = Pkg(strtab_bytes)
    strings = st.root['strings']
    have = [v.value for v in strings.items]
    names = sorted(names)
    assert have == [CAP_ANIM] and names and names[0] > have[-1] and len(set(names)) == len(names), (have, names[:2])
    for nm in names:
        strings.items.append(Val(strings.items[0].type, nm))
    ident, one = (0.0, 0.0, 0.0, -1.0), (1.0, 1.0, 1.0)
    assert abs(H.ANIM_T - 1.0) < 1e-9, 'a fraction f plays the clip at f x ANIM_T: the keys assume 1.0'
    clips, nkeys, err = {}, {}, 0.0
    for j, nm in enumerate(names):
        kind = nm.rsplit('_', 1)[1]
        ts, vs, e = anim_keys(kind, pitch)
        err = max(err, e)
        nkeys[kind] = len(ts)
        keys = [(0.0, v, 0.0) for v in vs]
        clips[nm] = H._clip(tmpl_clip_bytes, nm, len(have) + j, [
            (5, 3, 0x80, ts, keys), (2, 1, 0x84, [0.0], [ident]), (5, 2, 0x80, [0.0], [one])], CAP_STRTAB)
    return st.to_bytes(), clips, {'keys': nkeys, 'err_rows': err}


def clock_formatter(ui_root):
    """the session clock: the stock session timer's formatter (hud_dynamic_templates.ui), cloned as tt_clock_fmt (it
    writes time_remaining_str, which the timed header's clock text reads)"""
    fmt = [x for path, x in _find_node(ui_root, 'time_remaining_formatter') if path.startswith(CLOCK_MODEL + '.')]
    assert len(fmt) == 1, len(fmt)
    clock = I.clone_node(fmt[0])
    clock.items[N.PROPS]['name'].value = 'tt_clock_fmt'
    return clock


def rebind_clock_text(nodes, db):
    """the HUD header's clock text (t_tt_clk) reads db instead of the relative CLOCK_STR (the replay and
    spectator copies keep CLOCK_STR)"""
    hits = []

    def walk(n):
        if N.is_node(n):
            t = n.items[N.PROPS].get('text')
            if isinstance(t, Obj) and t.get('dbentry') is not None and t['dbentry'].value == CLOCK_STR:
                hits.append(n)
            for c in N.children(n):
                walk(c)
    for n in nodes:
        walk(n)
    assert [N.name(h) for h in hits] == ['t_tt_clk'], [N.name(h) for h in hits]
    hits[0].items[N.PROPS]['text']['dbentry'].value = db


def check_clock_start(stock_ui_bytes):
    """Each stock time_remaining_formatter receives exactly one signal: CLOCK_PIN, from an event of its timer's
    visibility decision (the pin the clone needs). -> number of stock formatters"""
    p = Pkg(stock_ui_bytes)
    fmts = [path for path, _ in _find_node(p.root, 'time_remaining_formatter')]
    assert len(fmts) >= 3 and any(f.startswith(CLOCK_MODEL + '.') for f in fmts), fmts
    got = {f: [] for f in fmts}

    def walk(x, trail):
        if N.is_node(x):
            t = trail + [N.name(x)]
            for idx in (N.COMMANDS, N.EVENTS):
                for c in x.items[idx].items:
                    if isinstance(c, Obj):
                        for sg in c['signals'].items:
                            if sg['to_object_name'].value in got:
                                got[sg['to_object_name'].value].append(('.'.join(t), sg['to_pin_name'].value,
                                                                        sg['to_pin'].value))
            for c in N.children(x):
                walk(c, t)
        elif isinstance(x, Arr):
            for c in x.items:
                walk(c, trail)
        elif isinstance(x, Obj):
            for k in x.keys():
                walk(x[k], trail)
    walk(p.root, [])
    for f, sigs in got.items():
        assert len(sigs) == 1, ('stock formatter signals', f, sigs)
        frm, pin, pin_id = sigs[0]
        assert pin == CLOCK_PIN and pin_id == U.djb2(CLOCK_PIN), ('stock formatter pin', f, sigs)
        assert frm == f.rsplit('.', 1)[0] + '.visibility_decision', ('stock formatter signal source', f, frm)
    return len(fmts)


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
    # the animations' nodes (anim_nodes); tt_ctl's trigger and untrigger (Track Position's enable and disable)
    # start and stop their decisions with the board's
    anim_host, anim_dec, anim_trig, anim_untrig, anim_info = anim_nodes(T, base)
    check_anim_leaves(anim_info['leaves'], contract)
    clock = clock_formatter(p.root)
    clock_out = leaf(CLOCK_OUT_KEY)
    assert clock_out in contract and contract[clock_out] == 'stri', 'leaves.md: the clock leaf (text)'
    out_prop = clock.items[N.PROPS]['database_output']
    assert out_prop['dbentry'].value == CLOCK_STR, 'the stock formatter writes time_remaining_str'
    out_prop['dbentry'].value = clock_out
    rebind_clock_text(nodes, clock_out)
    clock_mv = U.node(CLOCK_DECISION, 'MVCD', [('dbEntry', U.prop('stri', leaf('timed')))],
                      events=[U.event('1', [U.sig(f'{base}.tt_clock_fmt', CLOCK_PIN, '1')])])
    # the standings (tt_stack) hide and the Time Trial board (tt_trial) shows while hud_tt_trial; absent: standings
    switch = [U.node('v_tt_stack', 'UIGP', [('visible', H._bool_prop(True, leaf('trial'), True))], layout=['tt_stack'],
                     behav=U.GROUP_BEHAVIOURS),
              U.node('v_' + TRIAL_ROOT, 'UIGP', [('visible', H._bool_prop(False, leaf('trial')))], layout=[TRIAL_ROOT],
                     behav=U.GROUP_BEHAVIOURS)]
    host = U.node('tt_host_n', 'UIGP', [('visible', H._bool_prop(False, leaf('show')))],
                  kids=nodes + switch + tnodes + anim_host, layout=[HOST], behav=U.GROUP_BEHAVIOURS)
    mask = U.node('tt_mask', 'UIGP', [('visible', H._bool_prop(True, leaf('show'), True))], layout=[MASK],
                  behav=U.GROUP_BEHAVIOURS)
    ctl = U.node(CTL, 'UIGP', [], kids=[mask, host, clock] + decisions + [clock_mv] + anim_dec,
                 behav=U.GROUP_BEHAVIOURS)
    ctl.items[N.COMMANDS].items.extend(cmds)
    # the clock: the stock timers start their formatter with CLOCK_PIN when they turn visible; the clone gets it
    # from tt_ctl's trigger (Track Position's enable). The header shows the clock only in timed sessions.
    check_clock_start(stock_ui_bytes)
    trig = [c for c in ctl.items[N.COMMANDS].items if isinstance(c, Obj) and c['commandName'].value == 'trigger']
    assert len(trig) == 1, 'tt_ctl trigger'
    trig[0]['signals'].items.append(U.sig(f'{base}.tt_clock_fmt', CLOCK_PIN, 'trigger'))
    # the timed decision, registered and queried with the board's decisions, unregistered with them
    trig[0]['signals'].items += [U.sig(f'{base}.{CLOCK_DECISION}', 'register', 'trigger'),
                                 U.sig(f'{base}.{CLOCK_DECISION}', 'query', 'trigger')]
    untrig = [c for c in ctl.items[N.COMMANDS].items if isinstance(c, Obj) and c['commandName'].value == 'untrigger']
    assert len(untrig) == 1, 'tt_ctl untrigger'
    untrig[0]['signals'].items.append(U.sig(f'{base}.{CLOCK_DECISION}', 'unregister', 'untrigger'))
    trig[0]['signals'].items += anim_trig
    untrig[0]['signals'].items += anim_untrig
    # the stock cap instance never shows the tower (its root is hidden by default; this makes it explicit in game)
    # nor the editor's copy (shown by default: only these static nodes hide it in game)
    cap_off = [U.hidden('tt_cap_off', ROOT), U.hidden('tp_cap_off', PV_ROOT)]
    # the game's lap counter: hidden while the tower shows, back as the game has it while hud_tt_show is false or
    # absent; tower nodes on elements no stock node targets (the panel's parts through their wrappers in
    # the lap counter scene, build_lapc_scene); the stock nodes are the game's own again (an earlier build bound visible on five)
    lapc = lap_counter_nodes()
    lapc_node = H._node_at(p.root, LAPC_TEMPLATE)
    assert not any(N.name(c) == N.name(lapc) for c in N.children(lapc_node)), 'lap counter already has the tower node'
    # the game's flag message box at the lap counter's place: hidden the same way, by the element holding it
    flagm = flag_message_node()
    flagm_node = H._node_at(p.root, FLAGM_TEMPLATE)
    assert not any(N.name(c) == N.name(flagm) for c in N.children(flagm_node)), 'flag message already has the tower node'

    # every binding's type must be the type of the value it reads: a mismatch crashes the game
    bad, out = [], []
    for node, prop, t, db in (H._bindings(ctl, []) + [b for c in cap_off for b in H._bindings(c, [])] +
                              H._bindings(lapc, []) + H._bindings(flagm, [])):
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
    N.fix_ids(lapc, LAPC_TEMPLATE)
    lapc_node.items[N.CHILDREN].items.append(lapc)
    N.fix_ids(flagm, FLAGM_TEMPLATE)
    flagm_node.items[N.CHILDREN].items.append(flagm)
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
    # the clock's start: one CLOCK_PIN signal on tt_ctl's trigger, to the clone's id
    ts = [c for c in got.items[N.COMMANDS].items if isinstance(c, Obj) and c['commandName'].value == 'trigger']
    clk = [sg for sg in ts[0]['signals'].items if sg['to_pin_name'].value == CLOCK_PIN]
    fmt_path = f'{base}.tt_clock_fmt'
    assert len(ts) == 1 and len(clk) == 1 and clk[0]['to_object_name'].value == fmt_path, 'clock start signal'
    assert clk[0]['to_object'].value == paths[fmt_path].items[N.PROPS]['id'].value, 'clock start signal: target id'
    # the clone writes hud_tt_clock, the header's clock text reads it; the timed decision starts the clone
    fmt_id = paths[fmt_path].items[N.PROPS]['id'].value
    assert paths[fmt_path].items[N.PROPS]['database_output']['dbentry'].value == clock_out, 'clock output'
    texts = [n for n in paths.values() if H._type(n) == 'UILB' and isinstance(n.items[N.PROPS].get('text'), Obj)
             and n.items[N.PROPS]['text'].get('dbentry') is not None]
    assert [N.name(n) for n in texts if n.items[N.PROPS]['text']['dbentry'].value == clock_out] == ['t_tt_clk'], \
        'the clock text'
    assert not [n for n in texts if n.items[N.PROPS]['text']['dbentry'].value == CLOCK_STR], 'a relative clock text'
    mvp = f'{base}.{CLOCK_DECISION}'
    mv = paths[mvp]
    assert H._type(mv) == 'MVCD' and mv.items[N.PROPS]['dbEntry']['value'].value == leaf('timed'), 'clock decision'
    evs = [e for e in mv.items[N.EVENTS].items if isinstance(e, Obj)]
    assert len(evs) == 1 and evs[0]['eventName'].value == '1', 'clock decision event'
    sg = evs[0]['signals'].items
    assert len(sg) == 1 and sg[0]['to_pin_name'].value == CLOCK_PIN and sg[0]['to_object'].value == fmt_id, \
        'clock decision signal'
    tsig = [(x['to_object_name'].value, x['to_pin_name'].value, x['to_object'].value) for x in ts[0]['signals'].items]
    mv_id = mv.items[N.PROPS]['id'].value
    assert (mvp, 'register', mv_id) in tsig and (mvp, 'query', mv_id) in tsig, 'clock decision: trigger'
    us = [c for c in got.items[N.COMMANDS].items if isinstance(c, Obj) and c['commandName'].value == 'untrigger']
    assert len(us) == 1 and (mvp, 'unregister', mv_id) in [(x['to_object_name'].value, x['to_pin_name'].value,
                                                          x['to_object'].value) for x in us[0]['signals'].items], \
        'clock decision: untrigger'
    for ev in switches.values():
        for sigs in ev.values():
            assert all(path in paths for path, _pin in sigs), 'a decision signal without its node'
    assert len(decisions) == len(switches) == 2 * NPILLS, ('Time Trial decision nodes', len(decisions))
    T.trial_info = {'nodes': len(tnodes) + len(switch), 'decisions': len(decisions),
                    'signals': sum(len(s) for ev in switches.values() for s in ev.values()),
                    'values': sorted(switches)}
    # the animations' nodes and signals as built
    anim_info['readback_signals'] = check_anim_readback(got, base, anim_info)
    T.anim_info = {k: v for k, v in anim_info.items() if k != 'leaves'}
    T.anim_leaves = list(anim_info['leaves'])
    return data, (len(nodes) + len(switch) + len(tnodes) + len(decisions) + 6 + len(N.children(lapc)) + 1 +
                  len(anim_host) + len(anim_dec)), out


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
# is_video_sting_enabled is not "a sting plays": the game writes it once when the screen opens, true in every
# replay mode but instant replay and broadcast (highlights reel, snapshot, terminal damage; F1_25.exe 0x141bd31c5).
# There tt_sting hides the tower for the whole screen, so the stock board must stay. The masks are plain groups now
# (shown), and two decision nodes send them the groups' built-in hide / show (stock: 15 + 14 uses in this template):
#   tt_rp_on    SVCD hud_tt_on = true:  yes -> query tt_rp_mode;  no -> show both masks
#   tt_rp_mode  SVCD is_video_sting_enabled = true (only queried):  yes -> show both masks;  no -> hide both masks
# So the stock board is hidden exactly while the tower shows (on AND NOT the flag), and is the unmodded board
# otherwise. SVCD yes / no to a node's show / hide is the halo's ERS-mode route (halo_native.py), seen in game.
REPLAY_DEC_ON, REPLAY_DEC_MODE = 'tt_rp_on', 'tt_rp_mode'
# a highlights clip (the DLL's hud_tt_rclip, and its inverse hud_tt_nrclip so that both directions arrive as a
# 'yes'). The replay screen's whole visibility is decided by decision nodes now:
#   tower shown  = hud_tt_on AND (clip OR (show_drivers_list AND NOT is_video_sting_enabled))
#   game's board = shown exactly when the tower is not (its two masks)
# The second term is the instant replay as before (list on, flag off). tt_sting keeps its name and element
# (tt_host>Scene Root) but binds nothing: the chain shows and hides it. v_tt_root is a constant true as in the HUD.
#   triggers (registered, each 'yes' and 'no' -> query tt_rp_c_on): tt_rp_on (hud_tt_on), tt_rp_hl, tt_rp_nhl
#   chain (only queried): tt_rp_c_on -> tt_rp_c_hl -> tt_rp_c_list -> tt_rp_mode
REPLAY_HL, REPLAY_NHL = VM + 'rclip', VM + 'nrclip'   # not 'hl': that is the highlight-my-row leaf
REPLAY_CHAIN = ('tt_rp_c_on', 'tt_rp_c_hl', 'tt_rp_c_list', REPLAY_DEC_MODE)
REPLAY_TRIGGERS = (REPLAY_DEC_ON, 'tt_rp_hl', 'tt_rp_nhl')


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


def trial_off():
    """The replay and spectator screens' static node that hides the Time Trial board (tt_trial) in their bottom-cap
    instance. A scene's isHidden does not hide an element in game (docs/spectator-ui.md 10.1), so without it the board's
    five rows and header drew over the standings' top five rows (an in-game test: a lighter panel, a white bar, a
    dim bar after the gap, a second FIA badge). The HUD switches it with v_tt_trial (on hud_tt_trial) instead."""
    return U.hidden('v_' + TRIAL_ROOT, TRIAL_ROOT)


def build_replay_template(ui_bytes, hud_stock_ui_bytes, T, contract):
    """replays_and_highlights.ui plus the tower: under the screen root one group tt_ctl with
      tt_mask_table, tt_mask_header  driver_table>Scene Root, session_timer>Scene Root: no binding (shown); hidden
                                     and shown by tt_rp_on / tt_rp_mode (see REPLAY_DEC_ON)
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

    nodes = tower_nodes(T, hud, badge_tag, series=(REPLAY_SERIES, series_tag)) + [trial_off()]   # root constant
    host = U.node('tt_host_n', 'UIGP', [('visible', H._bool_prop(False, leaf('on')))], kids=nodes, layout=[HOST],
                  behav=U.GROUP_BEHAVIOURS)
    masks = [U.node(nm, 'UIGP', [], layout=[el, SCENE_ROOT], behav=U.GROUP_BEHAVIOURS) for nm, el in REPLAY_MASKS]
    sting = U.node(REPLAY_STING_NODE, 'UIGP', [], layout=[HOST, SCENE_ROOT], behav=U.GROUP_BEHAVIOURS)   # no binding
    clock = clock_formatter(hud_p.root)
    # the animations (anim_nodes), started by the screen's open and stopped by its close through tt_ctl's
    # trigger and untrigger (the HUD's: Track Position's enable and disable)
    base = f'{REPLAY_ROOT}.{CTL}'
    anim_host, anim_dec, anim_trig, anim_untrig, anim_info = anim_nodes(T, base)
    check_anim_leaves(anim_info['leaves'], contract)
    host.items[N.CHILDREN].items.extend(anim_host)
    # the screen's visibility decisions (REPLAY_HL). Registered and queried when the screen opens, after the
    # animations' signals; unregistered when it closes
    # the two clip leaves are written by the DLL outside the tower's leaf table: their names must not be in it
    assert REPLAY_HL not in contract and REPLAY_NHL not in contract, 'a clip leaf name is a tower leaf'
    for db_ in (leaf('on'), REPLAY_STING, REPLAY_SHOW):      # a decision compares a bool with a bool value
        assert replay_binding_type(db_, contract, hud, replay) == {'bool'}, (db_, replay_binding_type(db_, contract, hud, replay))

    def sg(to, pin, ev):
        return U.sig(f'{base}.{to}', pin, ev)

    def tower(ev):
        return [sg(REPLAY_STING_NODE, 'show', ev)] + [sg(nm, 'hide', ev) for nm, _el in REPLAY_MASKS]

    def game(ev):
        return [sg(REPLAY_STING_NODE, 'hide', ev)] + [sg(nm, 'show', ev) for nm, _el in REPLAY_MASKS]

    def svcd(name, db, yes, no):
        return U.node(name, 'SVCD', [('value', U.prop('bool', True)), ('dbEntry', U.prop('stri', db))],
                      events=[U.event('yes', yes), U.event('no', no)])
    c_on, c_hl, c_list, c_mode = REPLAY_CHAIN
    rp_nodes = [svcd(c_on, leaf('on'), [sg(c_hl, 'query', 'yes')], game('no')),
                svcd(c_hl, REPLAY_HL, tower('yes'), [sg(c_list, 'query', 'no')]),
                svcd(c_list, REPLAY_SHOW, [sg(c_mode, 'query', 'yes')], game('no')),
                svcd(c_mode, REPLAY_STING, game('yes'), tower('no'))]
    for nm, db in zip(REPLAY_TRIGGERS, (leaf('on'), REPLAY_HL, REPLAY_NHL)):
        rp_nodes.append(svcd(nm, db, [sg(c_on, 'query', 'yes')], [sg(c_on, 'query', 'no')]))
    rp_trig = [U.sig(f'{base}.{nm}', 'register', 'trigger') for nm in REPLAY_TRIGGERS] + [sg(c_on, 'query', 'trigger')]
    rp_untrig = [U.sig(f'{base}.{nm}', 'unregister', 'untrigger') for nm in REPLAY_TRIGGERS]
    ctl = U.node(CTL, 'UIGP', [], kids=masks + [host, sting, clock] + anim_dec + rp_nodes, behav=U.GROUP_BEHAVIOURS)
    ctl.items[N.COMMANDS].items.extend([U.command('trigger', anim_trig + rp_trig),
                                        U.command('untrigger', anim_untrig + rp_untrig)])

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
    hook(root, 'open', U.sig(base, 'trigger', 'open'))
    hook(root, 'close', U.sig(base, 'untrigger', 'close'))
    data = p.to_bytes()

    # read back: the group once under the root, its children in order, ids by path; outside tt_ctl the stock .ui but
    # for the two hook signals
    q = Pkg(data)
    got = H._node_at(q.root, f'{REPLAY_ROOT}.{CTL}')
    kids = [N.name(c) for c in N.children(got)]
    assert kids == ([nm for nm, _ in REPLAY_MASKS] + ['tt_host_n', REPLAY_STING_NODE, 'tt_clock_fmt'] +
                    [N.name(d) for d in anim_dec] + list(REPLAY_CHAIN) + list(REPLAY_TRIGGERS)), kids
    # the masks and the tower's gate bind nothing; every decision signal hits a node of tt_ctl by path
    # and id; the truth table over (tower on, clip, the game's list, the sting flag)
    by = {N.name(c): c for c in N.children(got)}
    for nm in [m for m, _el in REPLAY_MASKS] + [REPLAY_STING_NODE]:
        assert not H._bindings(by[nm], []) and by[nm].items[N.PROPS].get('visible') is None, ('still bound', nm)
    dbs = {REPLAY_CHAIN[0]: leaf('on'), REPLAY_CHAIN[1]: REPLAY_HL, REPLAY_CHAIN[2]: REPLAY_SHOW, REPLAY_CHAIN[3]: REPLAY_STING,
           REPLAY_TRIGGERS[0]: leaf('on'), REPLAY_TRIGGERS[1]: REPLAY_HL, REPLAY_TRIGGERS[2]: REPLAY_NHL}
    for d, db in dbs.items():
        pr = by[d].items[N.PROPS]
        assert U._type(by[d]) == 'SVCD' and pr['value']['value'].type == 'bool' and pr['value']['value'].value is True
        assert pr['dbEntry']['value'].value == db, (d, db)

    def fires(node, ev):
        e = [x for x in node.items[N.EVENTS].items if isinstance(x, Obj) and x['eventName'].value == ev]
        assert len(e) == 1, (N.name(node), ev)
        out_ = []
        for sg_ in e[0]['signals'].items:
            to = sg_['to_object_name'].value
            assert to.startswith(base + '.') and to[len(base) + 1:] in by, ('signal leaves tt_ctl', to)
            assert sg_['to_object'].value == by[to[len(base) + 1:]].items[N.PROPS]['id'].value, ('target id', to)
            out_.append((to[len(base) + 1:], sg_['to_pin_name'].value))
        return out_

    def screen(val, start):
        """the gate's and the masks' state after node `start` fires for the leaf values `val`"""
        st = {REPLAY_STING_NODE: 'shown', 'masks': 'shown'}
        todo, steps = fires(by[start], 'yes' if val[dbs[start]] else 'no'), 0
        while todo:
            to, pin = todo.pop(0)
            steps += 1
            assert steps < 40, 'the decisions loop'
            if pin == 'query':
                todo += fires(by[to], 'yes' if val[dbs[to]] else 'no')
            else:
                assert pin in ('show', 'hide'), (to, pin)
                st[to if to == REPLAY_STING_NODE else 'masks'] = 'shown' if pin == 'show' else 'hidden'
        return st
    table = {}
    for on in (True, False):
        for hl in (True, False):
            for lst in (True, False):
                for flag in (True, False):
                    val = {leaf('on'): on, REPLAY_HL: hl, REPLAY_NHL: not hl, REPLAY_SHOW: lst, REPLAY_STING: flag}
                    want = on and (hl or (lst and not flag))
                    for start in (REPLAY_CHAIN[0],) + REPLAY_TRIGGERS:       # the open's query and every trigger
                        st = screen(val, start)
                        assert st == {REPLAY_STING_NODE: 'shown' if want else 'hidden', 'masks': 'hidden' if want else 'shown'}, (val, start, st)
                    table[f'on={int(on)} clip={int(hl)} list={int(lst)} sting={int(flag)}'] = 'tower' if want else "game's board"
    assert H._canon(H._strip_ours(q.root, (CTL,))) == H._canon(Pkg(ui_bytes).root), 'replay: a node outside tt_ctl changed'
    hooks = [(cmd, s['to_object_name'].value, s['to_pin_name'].value, s['to_object'].value)
             for cmd in ('open', 'close') for x in H._node_at(q.root, REPLAY_ROOT).items[N.COMMANDS].items
             if isinstance(x, Obj) and x['commandName'].value == cmd for s in x['signals'].items
             if s['to_object_name'].value == base]
    assert hooks == [('open', base, 'trigger', got.items[N.PROPS]['id'].value),
                     ('close', base, 'untrigger', got.items[N.PROPS]['id'].value)], hooks
    anim_info['readback_signals'] = check_anim_readback(got, base, anim_info)
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
            'stock_visible_nodes': len(stock_vis), 'replay_vm': sorted(db for db, _ in out if db.startswith(REPLAY_VM)),
            'visibility_table': table,
            'anim': {k: v for k, v in anim_info.items() if k != 'leaves'}}
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
# the spectator screen's own flag message. Seen in game (2026-11-11, spectating): the game's box
# (LAP 4 / CAUTION / SECTOR 1) drew over the tower's yellow card (YELLOW FLAG / SECTOR 1). The screen scene holds its
# own reference to the flag message scene (SPECT_FLAGM_EL, top level, at (-9.09, 4.89): on the tower's header); the
# stock node SPECT_FLAGM (dataContext the left message queue, visible <- show_left_side) holds the message node
# left_message [F1HM] on that scene's root, as the HUD element's does. The HUD's tower node is in the HUD template
# (FLAGM_TEMPLATE): another .ui and another instance of the scene, so it never reached this one. The screen gets the
# same node, hiding FLAGM_PART while hud_tt_on, the spectator tower's own switch (tt_host_n shows on it, the stock
# board's masks hide on it): with the tower off the game's box draws as before.
SPECT_FLAGM_EL = 'race_condition_flag_message'
SPECT_FLAGM = SPECT_PARENT + '.left_notification'
SPECT_FLAGM_MSG = SPECT_FLAGM + '.left_message'


def check_spect_flag_message(scene_bytes, screen_bytes, stock_ui_bytes):
    """the spectator screen's flag message. The screen scene references the stock flag message scene once, at
    its top level (SPECT_FLAGM_EL, shown by default); the stock node SPECT_FLAGM targets that reference, switched by
    SPECT_SHOW; its message node SPECT_FLAGM_MSG [F1HM] targets the scene's root; no other stock node of the screen
    targets the reference or anything in it, and no stock node targets FLAGM_PART; FLAGM_PART holds everything the
    scene draws (flag_scene_check). -> (elements FLAGM_PART holds that draw, stock nodes in the message node)"""
    drawn = flag_scene_check(scene_bytes)
    scr = I.Idf(screen_bytes)
    assert len(scr.scenes) == 1 and scr.scenes[0].name == I.component_id(SPECT_SCREEN), 'not the stock spectator scene'
    refs = [e for e, _ in scr.scenes[0].root.walk() if e.type == 'eXRef' and e.file_ref == FLAGM_SCENE]
    assert len(refs) == 1, ('spectator scene: flag message references', [e.path for e in refs])
    ref = refs[0]
    assert ref.name == SPECT_FLAGM_EL and ref.path == SPECT_FLAGM_EL, ('spectator flag message reference', ref.path)
    assert [e.name for e, _ in scr.scenes[0].root.walk()].count(SPECT_FLAGM_EL) == 1, 'flag message name not unique'
    assert not I.get_param(ref.obj, 'isHidden'), 'spectator flag message hidden by default'
    p = Pkg(stock_ui_bytes)
    ln = H._node_at(p.root, SPECT_FLAGM)
    assert H._type(ln) == 'UIGP' and _chains(ln) == [(SPECT_PREFIX, SPECT_FLAGM_EL)], \
        ('spectator flag message node', H._type(ln), _chains(ln))
    vis = ln.items[N.PROPS].get('visible')
    neg = vis.get('dbentrynegate') if vis is not None else None
    assert vis is not None and vis.get('dbentry') is not None and vis['dbentry'].value == SPECT_SHOW and \
        (neg is None or neg.value is False), 'spectator flag message: not switched by ' + SPECT_SHOW
    msg = H._node_at(p.root, SPECT_FLAGM_MSG)
    assert H._type(msg) == 'F1HM' and _chains(msg) == [(SCENE_ROOT,)], \
        ('spectator flag message: message node', H._type(msg), _chains(msg))
    assert not any(N.is_node(c) and N.name(c) == FLAGM_NODE for c in N.children(msg)), 'a stock ' + FLAGM_NODE
    others, hits = [], []

    def walk(n, path, chains):
        mine = [c + own for c in chains for own in _chains(n)] or chains
        inside = path == SPECT_FLAGM or path.startswith(SPECT_FLAGM + '.')
        for c in mine:
            if c[:2] == (SPECT_PREFIX, SPECT_FLAGM_EL) and not inside:
                others.append((path, c))
            if inside and FLAGM_PART in c:
                hits.append((path, c))
        for k in N.children(n):
            if N.is_node(k):
                walk(k, f'{path}.{N.name(k)}', mine)

    for k in N.children(H._node_at(p.root, SPECT_ROOT)):
        if N.is_node(k):
            walk(k, f'{SPECT_ROOT}.{N.name(k)}', [()])
    assert not others, ('other stock nodes target the spectator flag message', others[:6])
    assert not hits, ('stock nodes target the flag message part', hits[:6])
    return drawn, sum(1 for k in N.children(msg) if N.is_node(k))


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

    nodes = tower_nodes(T, hud, badge_tag, root_visible=U.prop('bool', True, SPECT_SHOW),
                        series=(SPECT_SERIES, series_tag)) + [trial_off()]
    host = U.node('tt_host_n', 'UIGP', [('visible', H._bool_prop(False, leaf('on')))], kids=nodes,
                  layout=[SPECT_PREFIX, SPECT_TABLE_EL, HOST], behav=U.GROUP_BEHAVIOURS)
    masks = [U.node(nm, 'UIGP', [('visible', H._bool_prop(True, leaf('on'), True))], layout=list(chain),
                    behav=U.GROUP_BEHAVIOURS) for nm, chain in SPECT_MASKS]
    clock = clock_formatter(hud_p.root)
    # the animations (anim_nodes), started when the screen opens and stopped when it closes (the content's own
    # on_screen_opened / on_screen_closed, which trigger the stock driver list panel the same way)
    base = f'{SPECT_PARENT}.{CTL}'
    anim_host, anim_dec, anim_trig, anim_untrig, anim_info = anim_nodes(T, base)
    check_anim_leaves(anim_info['leaves'], contract)
    host.items[N.CHILDREN].items.extend(anim_host)
    ctl = U.node(CTL, 'UIGP', [], kids=masks + [host, clock] + anim_dec, behav=U.GROUP_BEHAVIOURS)
    ctl.items[N.COMMANDS].items.extend([U.command('trigger', anim_trig), U.command('untrigger', anim_untrig)])

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
    hook(content, 'on_screen_opened', U.sig(base, 'trigger', 'on_screen_opened'))
    hook(content, 'on_screen_closed', U.sig(base, 'untrigger', 'on_screen_closed'))
    # the screen's own flag message box hides while the tower shows (check_spect_flag_message): the HUD's
    # node, switched by the tower's own leaf (NOT hud_tt_on; true while the leaf is absent)
    flagm = flag_message_node(H._bool_prop(True, leaf('on'), True))
    msg = H._node_at(p.root, SPECT_FLAGM_MSG)
    assert H._type(msg) == 'F1HM', 'spectator flag message node'
    sibs = [N.name(c) for c in N.children(msg) if N.is_node(c)]
    assert FLAGM_NODE not in sibs, 'the spectator flag message already has the tower node'
    assert djb2(FLAGM_NODE) not in [djb2(nm) for nm in sibs], 'a stock message node shares the name hash of ' + FLAGM_NODE
    for node, prop, t, db in H._bindings(flagm, []):
        want = spectator_binding_type(db, contract, hud, spect)
        if not want or t not in want:
            raise SystemExit(f'spectator flag message binding {node}.{prop} <- {db}: {t}, the value is {want}')
        out.append((db, t))
    N.fix_ids(flagm, SPECT_FLAGM_MSG)
    msg.items[N.CHILDREN].items.append(flagm)
    data = p.to_bytes()

    # read back: the group once under content, its children in order, ids by path; outside tt_ctl the halo's .ui as given
    q = Pkg(data)
    got = H._node_at(q.root, f'{SPECT_PARENT}.{CTL}')
    kids = [N.name(c) for c in N.children(got)]
    assert kids == [nm for nm, _ in SPECT_MASKS] + ['tt_host_n', 'tt_clock_fmt'] + [N.name(d) for d in anim_dec], kids
    hooks = [(cmd, s['to_object_name'].value, s['to_pin_name'].value, s['to_object'].value)
             for cmd in ('on_screen_opened', 'on_screen_closed')
             for x in H._node_at(q.root, SPECT_PARENT).items[N.COMMANDS].items
             if isinstance(x, Obj) and x['commandName'].value == cmd for s in x['signals'].items
             if s['to_object_name'].value == base]
    assert hooks == [('on_screen_opened', base, 'trigger', got.items[N.PROPS]['id'].value),
                     ('on_screen_closed', base, 'untrigger', got.items[N.PROPS]['id'].value)], hooks
    anim_info['readback_signals'] = check_anim_readback(got, base, anim_info)
    # the flag message node, the last child of the message node, one switch on FLAGM_PART
    qmsg = H._node_at(q.root, SPECT_FLAGM_MSG)
    qk = [c for c in N.children(qmsg) if N.is_node(c)]
    assert N.name(qk[-1]) == FLAGM_NODE and [N.name(c) for c in qk].count(FLAGM_NODE) == 1, 'spectator flag node'
    fm = qk[-1]
    fk = [c for c in N.children(fm) if N.is_node(c)]
    assert not _chains(fm) and [N.name(c) for c in fk] == ['v_tt_flagm_' + FLAGM_PART], 'spectator flag node kids'
    assert _chains(fk[0]) == [(FLAGM_PART,)], ('spectator flag node layout', _chains(fk[0]))
    fv = fk[0].items[N.PROPS]['visible']
    assert fv['dbentry'].value == leaf('on') and fv['dbentrynegate'].value is True and fv['value'].value is True, \
        'spectator flag node switch'
    fpath = f'{SPECT_FLAGM_MSG}.{FLAGM_NODE}'
    assert fm.items[N.PROPS]['id'].value == N.djb2(fpath), 'spectator flag node id'
    assert fk[0].items[N.PROPS]['id'].value == N.djb2(f'{fpath}.v_tt_flagm_{FLAGM_PART}'), 'spectator flag kid id'
    assert H._canon(H._strip_ours(q.root, (CTL, FLAGM_NODE))) == H._canon(Pkg(ui_bytes).root), \
        'a node outside tt_ctl and the flag message node changed'
    assert H._canon(H._strip_ours(q.root, H.OUR_GROUPS + (CTL, FLAGM_NODE))) == H._canon(stock_root), \
        'a stock node changed'
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
            'stock_visible_nodes': len(stock_vis), 'screen_vm': sorted({db for db, _ in out if not db.startswith('#')}),
            'anim': {k: v for k, v in anim_info.items() if k != 'leaves'},
            'flag_message': {'node': fpath, 'hides': FLAGM_PART, 'switch': 'NOT ' + leaf('on'),
                             'stock_siblings': len(qk) - 1}}
    return data, info, out
