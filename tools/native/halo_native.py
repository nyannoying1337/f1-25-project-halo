"""Game-native halo HUD: the dial_om_xm scene with the halo built in, its anim clips and string table, and the
hud_dynamic_templates.ui nodes that drive it (native VM values + the addon DLL's view_model_data.hud_halo_* leaves).
Plus the HUD editor's preview: a static copy of the halo in dial_complete, its .uipre, and the template nodes that
keep that copy out of the game (see PREVIEW_SCENE).

Coordinates: HUD units (u, v) = 1 px of the reference drawing's 640x360 frame, origin at the dial centre, v down.
Scene units: the OSD scene (1 unit = screen width / 19.2), y up. A HUD point maps to (K*u, -K*v) relative to the
'halo' null, which sits so the base sprite's bottom edge is on the stock dial's bottom customisation point.
"""
import copy
import hashlib
import math
import os
import re
import struct
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SWL = os.environ.get('SWOFTY_TOOLS', '')
sys.path.insert(0, SWL)
sys.path.insert(0, HERE)
from pkg import Pkg, Obj, Arr, Val  # noqa: E402
import idf as I  # noqa: E402
import uiops as U  # noqa: E402
import uinode as N  # noqa: E402

K = 0.018                    # scene units per HUD unit
BR_Y = -0.288                # stock br_customisation y: the base sprite's bottom edge
SCENE = 'eaid://ui_package/art/osd/components/dial/dial_om_xm.idf'
MESH = SCENE + '/central_bg_fill?context=render'
STRTAB = SCENE + '?context=animstringtable&file=0'
VM = '#view_model_data.hud_halo_'
TEAM = '#session.current_car.nub_colour'
# The game's own view-model values the halo binds (dial-relative unless they start with '#'). Each one is what a
# stock 2026-dial node binds (see build/all_bind.txt); docs/internal-state/fields.md records what is verified.
NATIVE = {
    'speed_text': 'speed_str',                     # stock speedo text, in the player's unit setting
    'revs': 'revs',                                # stock radial rev slider, 0..1
    'battery': 'ers_stored',                       # stock battery radial, 0..1
    # 2026 Overtake Mode in effect (= CarErs+0x1a62; ERS sub-VM 0x141766b30, 2026 cars only): the stock dial's
    # mode tests read it. NOT ers_overtake_show_title, which only says the Boost control is shown
    # (docs/internal-state/re-findings.md §2, §3)
    'overtake_on': 'om_active',
    'aero_straight': 'is_xm_active',               # X-mode (low-drag straight mode) engaged: rear wing state 4/5
    'own_pos': '#session.current_car.position',    # stock timing tower position
    'own_name': '#session.current_car.driver.second_name',   # stock driver tags: car.driver.second_name
    # the session car list, looked up BY NAME: element "car<vid>" is the car with that vehicle id (OnSessionEnter
    # 0x1414ad0bb). "cars[i]" would pick the i-th element by list position (Vm_Resolve_RegistryNode 0x1442b1b60)
    'car_pos': '#session.cars.car{i}.position',
    'car_name': '#session.cars.car{i}.driver.second_name',
}
RIVAL_SLOTS = 24             # rival lane slots: one per #session.cars index, shown by the DLL's rvNN leaf
# A bound property's value type must be the type of the value it reads: the game takes the property's type on trust.
# A 'stri' text bound to the ui32 '#session.current_car.position' made the game read the position number as a string
# pointer and crash while creating the HUD (first test drive, 2026-11-09: access violation reading 0xa / 0xe).
# check_binding_types() enforces this at build time against the stock template, the DLL's leaf kinds and this table
# (game values that no stock node in hud_dynamic_templates.ui binds):
KNOWN_TYPES = {
    'om_active': 'bool',                                # stock dial SVCD tests has_om / has_om_after compare it to a bool
    '#session.current_car.driver.second_name': 'stri',  # VM string (re-findings.md 4c: row builder 0x1424be430)
}
DLL_TEXT_LEAVES = {'kmh', 'mph', 'tnum'}               # native/src/leaves.hpp: these are text, every other leaf is bool


def leaf(key):
    """A view_model_data.hud_halo_* leaf the addon DLL writes (native/src/leaves.hpp)."""
    return VM + key


CAP_EM = 0.672              # game font cap height / em (measured in game on OSD_24_bold and 17_bold)
CAP_OFF = 0.336             # cap centre above the eText origin; the origin is the baseline (measured in game)
ANIM_T = 1.0                 # clip length: a UIXA fraction f plays the clip at f * ANIM_T
TEMPLATE_PARENT = 'hud_f1_dial_om_xm.osd_visibility_option.f1_om_xm_dial_child'
ANIM_NODES = ['zh_batt_ctr_anim', 'zh_batt_win_anim', 'zh_rpm_anim', 'zh_rpm_core_anim']   # sorted: appended to the table
STOCK_KIDS = ('frame', 'fuel', 'holder_central', 'pit_indicator')
NLEVEL = 16

# HUD editor preview. The editor (screens/hud_customisation.ui) shows the dial group's leader, hud_layouts.uidl's
# dial_f1 = dial_complete.idf, with no template driving it: the scene's own state plus its .uipre preview data. So the
# halo is drawn into dial_complete as a static copy ('halo_pv', the PREVIEW state below), the .uipre hides the stock
# dial's four parts and fills the copy's texts, and in game the hud_f1_dial template (and the spectator HUD's
# modern_dial) hide the copy and show the stock parts again.
PREVIEW_SCENE = 'eaid://ui_package/art/osd/components/dial/dial_complete.idf'
PREVIEW_UIPRE = 'eaid://ui_package/art/osd/components/dial/dial_complete.uipre'
PREVIEW_ROOT = 'halo_pv'
PREVIEW_CTL = 'halo_pv_ctl'
PREVIEW_PARENTS = {'hud_f1_dial': 'hud_f1_dial.osd_visibility_option.f1_dial_child',
                   'hud_spectator_2': 'hud_spectator_2.content.bottom_right.modern_dial'}
PREVIEW_TEAM = '#27F4D2'     # halo.js's default team colour: no template tints the preview, so its sprites are pre-tinted
PREVIEW_SPRITES = {'rails': 'rails_pv', 'solid_white': 'solid_team_pv'}
PV_RIVAL = 5
UIPRE_TEXT, UIPRE_VISIBLE = 4045306521, 839438211   # .uipre setter keys (stock speedo_number '135', fuel_icon_empty False)

# The fixed state the HUD editor shows, keyed by the bindings that drive each part in game: the stock preview's numbers
# (gear 5, 135 mph = 217 km/h, 75 % battery), full throttle, deploying, turn 4 left, the player and one rival.
PREVIEW = {leaf('g5'): True, leaf('spd'): True, leaf('kmh'): '217', leaf('mph'): '135',
           NATIVE['battery']: 0.75, NATIVE['revs']: 0.62, leaf('dp10'): True,
           leaf('turn'): True, leaf('tnum'): '4', leaf('tl'): True,
           leaf('nm'): True, NATIVE['own_pos']: '1', NATIVE['own_name']: 'Driver Name',
           leaf(f'rv{PV_RIVAL:02d}'): True, NATIVE['car_pos'].format(i=PV_RIVAL): '2',
           NATIVE['car_name'].format(i=PV_RIVAL): 'Rival Name'}
PREVIEW.update({leaf(f'th{i:02d}'): True for i in range(1, 11)})


def deg(r):
    return r * 180.0 / math.pi


def quat_z(theta_deg):
    """Rotation by theta (degrees, counter-clockwise on screen) about z, written with w <= 0 like the stock files."""
    h = math.radians(theta_deg) / 2
    q = [0.0, 0.0, math.sin(h), math.cos(h)]
    if q[3] > 0:
        q = [-x for x in q]
    return q


# ---------------------------------------------------------------- geometry (mirrors halo.js)
class Geo:
    def __init__(self, meta):
        self.G, self.sp = meta['G'], meta['sprites']
        self.T0, self.T1 = meta['RPM_T0'], meta['RPM_T1']
        self.CS = self.G['centreScale']
        self.halo_y = BR_Y + K * self.sp['base']['y1']

    @staticmethod
    def S(u, v):
        return (K * u, -K * v)

    def rect(self, name):
        s = self.sp[name]
        return s['x0'], s['y0'], s['x1'], s['y1']

    def bez(self, t):
        q = self.G['gears']
        p0, p1, p2 = q['p0'], q['p1'], q['p2']
        u = 1 - t
        return (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0], u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])

    def bez_tan(self, t):
        q = self.G['gears']
        p0, p1, p2 = q['p0'], q['p1'], q['p2']
        u = 1 - t
        dx = 2 * u * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0])
        dy = 2 * u * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1])
        l = math.hypot(dx, dy)
        return dx / l, dy / l

    def gear_pt(self, t, off):
        p, (tx, ty) = self.bez(t), self.bez_tan(t)
        return (p[0] - ty * off, p[1] + tx * off)

    def lane_point(self, u, v, bend=True):
        n = self.G['names']
        a = math.radians(n['rot'])
        ux, uy = math.cos(a), math.sin(a)
        vx, vy = -uy, ux
        vv = v + (n['bend'] * u * u if (bend and u < 0) else 0.0)
        return (n['x'] + ux * u + vx * vv, n['y'] + uy * u + vy * vv)

    def name_line(self, u_end, v, length):
        """Straight line that best fits the bent lane over [u_end - length, u_end]: (anchor at u_end, canvas angle)."""
        n = self.G['names']
        b = n['bend']
        m = b * (2 * u_end - length)                 # chord slope dv/du of v + b u^2
        shift = -b * length * length / 8             # move the chord halfway toward the parabola
        v_end = v + (b * u_end * u_end if u_end < 0 else 0.0) + shift
        a = math.radians(n['rot'])
        ux, uy = math.cos(a), math.sin(a)
        vx, vy = -uy, ux
        anchor = (n['x'] + ux * u_end + vx * v_end, n['y'] + uy * u_end + vy * v_end)
        dx, dy = ux + m * vx, uy + m * vy
        return anchor, math.degrees(math.atan2(dy, dx))

    def lane_chord(self, ua, ub, v, u_at):
        """Straight line that best fits the bent lane (offset v) over [ua, ub]: (its point at u_at, canvas angle).
        Same fit as name_line: the chord between the lane's ends, moved halfway toward the curve."""
        n = self.G['names']

        def f(u):
            return n['bend'] * u * u if u < 0 else 0.0

        m = (f(ub) - f(ua)) / (ub - ua)
        mid = (ua + ub) / 2
        shift = -((f(ua) + m * (mid - ua)) - f(mid)) / 2
        v_at = v + f(ua) + m * (u_at - ua) + shift
        a = math.radians(n['rot'])
        ux, uy = math.cos(a), math.sin(a)
        vx, vy = -uy, ux
        anchor = (n['x'] + ux * u_at + vx * v_at, n['y'] + uy * u_at + vy * v_at)
        dx, dy = ux + m * vx, uy + m * vy
        return anchor, math.degrees(math.atan2(dy, dx))

    def rpm(self, nkeys=41):
        """RPM sweep: pivot C (HUD), start angle (scene deg), signed sweep per key, sweep sign, reach (scene)."""
        tr = self.G['gears']['track']
        T0, T1 = self.T0, self.T1
        a, b, c = self.gear_pt(T0, tr), self.gear_pt((T0 + T1) / 2, tr), self.gear_pt(T1, tr)
        d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
        ux = ((a[0] ** 2 + a[1] ** 2) * (b[1] - c[1]) + (b[0] ** 2 + b[1] ** 2) * (c[1] - a[1]) + (c[0] ** 2 + c[1] ** 2) * (a[1] - b[1])) / d
        uy = ((a[0] ** 2 + a[1] ** 2) * (c[0] - b[0]) + (b[0] ** 2 + b[1] ** 2) * (a[0] - c[0]) + (c[0] ** 2 + c[1] ** 2) * (b[0] - a[0])) / d
        C = (ux, uy)
        Cs = self.S(*C)

        def phi(t):
            p = self.S(*self.gear_pt(t, tr))
            return math.atan2(p[1] - Cs[1], p[0] - Cs[0])

        phi0 = phi(T0)
        keys, prev = [], 0.0
        for j in range(nkeys):
            f = j / (nkeys - 1)
            al = phi(T0 + (T1 - T0) * f) - phi0
            while al - prev > math.pi:
                al -= 2 * math.pi
            while al - prev < -math.pi:
                al += 2 * math.pi
            keys.append((f, al))
            prev = al
        sigma = 1.0 if keys[-1][1] > 0 else -1.0
        x0, y0, x1, y1 = self.rect('rpm_team')
        reach = max(math.hypot(K * x - Cs[0], -K * y - Cs[1]) for x in (x0, x1) for y in (y0, y1)) * 1.15
        return C, deg(phi0), keys, sigma, reach


# ---------------------------------------------------------------- scene
def _find(obj, name):
    if I._val(obj.get('name')) == name:
        return obj
    for c in (obj.get('children').items if obj.get('children') is not None else []):
        r = _find(c, name)
        if r is not None:
            return r
    return None


def _guid(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'nick.f1-2026-halo/' + name))


def _vec(v):
    return Val('vec3', [float(v[0]), float(v[1]), float(v[2]), 0.0])


def _param(o, name, value, vtype='stri'):
    """Set a param, keeping the template's value type when the param exists."""
    for it in o['params'].items:
        if I._val(it.get('name')) == name:
            it.set('value', Val(it['value'].type, value))
            return
    I.set_param(o, name, value, vtype)


class SceneBuilder:
    def __init__(self, scene_bytes, mods_bytes, bar_bytes, embs, tex, scene=SCENE, remap=None):
        self.idf = I.Idf(scene_bytes)
        self.entry = self.idf.scenes[0].entry
        self.root = self.entry['scene']
        assert self.idf.scenes[0].name == I.component_id(scene), scene
        mods_root = I.Idf(mods_bytes).scenes[0].entry['scene']
        bar_root = I.Idf(bar_bytes).scenes[0].entry['scene']
        self.T_quad = _find(self.root, 'central_bg_fill')
        self.T_text = _find(self.root, 'speedo_number')
        self.T_null = _find(mods_root, 'mod_1_icon_fill_mask_anim')
        self.T_win = _find(mods_root, 'mod_1_icon_fill_mask')
        self.T_mask = _find(bar_root, 'ers_battery_fill_mask')
        assert all(x is not None for x in (self.T_quad, self.T_text, self.T_null, self.T_win, self.T_mask))
        g = self.T_quad['geoms'].items[0]
        mesh = scene + '/central_bg_fill?context=render'   # the scene's own quad mesh (material slot central_bg_fill)
        assert g['resourceid'].value == mesh
        assert g['asset'].value == int.from_bytes(hashlib.md5(mesh.encode()).digest()[:8], 'big')
        self.embs, self.tex, self.remap = embs, tex, remap or {}
        self.names = set()

    def _base(self, tmpl, name, pos, rot=None, scale=(1, 1, 1)):
        if name in self.names:
            raise KeyError('duplicate element ' + name)
        self.names.add(name)
        o = I.clone_node(tmpl)
        o.set('name', Val('stri', name))
        _param(o, 'guid', _guid(name))
        o.set('position', _vec(pos))
        o.set('scale', _vec(scale))
        o.set('rotation', Val('quat', rot if rot is not None else [-0.0, -0.0, 0.0, -1.0]))
        o.set('children', Arr([], o['children'].tag))
        o.set('anims', Arr([], o['anims'].tag))
        return o

    def kids(self, o, *children):
        o['children'].items.extend(children)
        return o

    def null(self, name, pos, rot_deg=None, scale=(1, 1, 1), anim=False):
        o = self._base(self.T_null, name, pos, quat_z(rot_deg) if rot_deg is not None else None, scale)
        if anim:
            entry = I.clone_node(self.T_null['anims'].items[0])
            entry.set('asset', Val('stri', f'{SCENE}/{name}?context=animation'))
            o.set('anims', Arr([entry], self.T_null['anims'].tag))
        return o

    def quad(self, name, sprite, pos, w, h, layer):
        """A textured quad of w x h scene units centred on pos, showing sprite's material."""
        o = self._base(self.T_quad, name, pos, [-0.707107, -0.0, 0.0, -0.707107], (w / 4.48, 1.0, h / 1.92))
        o['geoms'].items[0].set('materialid', Val('stri', self.embs[self.remap.get(sprite, sprite)]))
        _param(o, 'eLayer.layer', int(layer), 'si32')
        return o

    def window(self, name, pos, w, l):
        o = self._base(self.T_win, name, pos)
        _param(o, 'width', float(w), 'fp32')
        _param(o, 'length', float(l), 'fp32')
        _param(o, 'minExtents', [-w / 2, -l / 2, -0.0, 0.0], 'vec3')
        _param(o, 'maxExtents', [w / 2, l / 2, -0.0, 0.0], 'vec3')
        return o

    def mask(self, name, pos, w, h, tex):
        o = self._base(self.T_mask, name, pos)
        _param(o, 'width', float(w), 'fp32')
        _param(o, 'height', float(h), 'fp32')
        _param(o, 'minExtents', [-w / 2, -h / 2, 5e-05, 0.0], 'vec3')
        _param(o, 'maxExtents', [w / 2, h / 2, 5e-05, 0.0], 'vec3')
        _param(o, 'eMaskTexture.maskHalfVec', [w / 2, h / 2, 0.0, 0.0], 'vec3')
        _param(o, 'eMaskTexture.maskTextureResource', tex)
        return o

    def text(self, name, pos, style, halign, box, layer, wrapping):
        o = self._base(self.T_text, name, pos)
        pa = o['params']
        pa.items = [it for it in pa.items if I._val(it.get('name')) != 'isHidden']
        _param(o, 'boxWidth', float(box), 'fp32')
        _param(o, 'halign', halign)
        _param(o, 'style', style)
        _param(o, 'wrapping', wrapping)
        _param(o, 'textcase', 'upper')
        _param(o, 'eLayer.layer', int(layer), 'si32')
        return o


STYLE_H = {'17_bold': 17, '24_bold': 24, 'OSD_24_bold': 24, 'OSD_17_bold': 17}


def rpm_angle(keys, f):
    """The rpm sweep's angle (radians) at revs fraction f: the clip's keys, linearly interpolated."""
    f = min(max(f, 0.0), 1.0)
    for (f0, a0), (f1, a1) in zip(keys, keys[1:]):
        if f <= f1:
            return a0 + (a1 - a0) * (f - f0) / (f1 - f0)
    return keys[-1][1]


def _halo(B, geo, halo, pv=None):
    """Add the halo's elements under the null `halo`.

    pv None (the game's dial_om_xm): every element, and the template bindings that drive them.
    pv a state (PREVIEW; dial_complete in the HUD editor, where no template runs): only what that state shows, the
    battery window and rpm sweep at static positions, and the texts it shows (for the .uipre).
    -> (vis, texts, xas, colours, rpm keys, battery keys, preview texts [(element, text)])"""
    G, CS, S = geo.G, geo.CS, geo.S
    game = pv is None
    vis = []      # (template node name, element, bool binding, negate, value while the binding is absent)
    texts = []    # (template node name, element, text binding, visible binding or None, visible default, negate)
    xas = []      # (template node name, anim element, VM fraction binding)
    colours = []  # (template node name, element)
    pv_texts = []

    def lit(db, neg=False):
        """preview: does the part bound to db (negated: to not db) show"""
        return db is None or bool(pv.get(db, False)) != neg

    def at(u, v, z=0.0):
        x, y = S(u, v)
        return (x, y, z)

    def sprite_quad(name, sprite, layer, origin=(0.0, 0.0, 0.0)):
        x0, y0, x1, y1 = geo.rect(sprite)
        c = at((x0 + x1) / 2, (y0 + y1) / 2)
        return B.quad(name, sprite, (c[0] - origin[0], c[1] - origin[1], -origin[2]), K * (x1 - x0), K * (y1 - y0), layer)

    def shown(name, sprite, db=None, neg=False, parent=None, layer=22):
        """A sprite quad; with db, a template node shows it while db (negated: while not db) is true.
        A hidden parent null hides everything under it, so nesting gives AND."""
        if game or lit(db, neg):
            B.kids(parent if parent is not None else halo, sprite_quad(name, sprite, layer))
        if db and game:
            vis.append(('v_' + name[5:], name, db, neg, neg))

    def group(name, db, neg=False, default=None):
        if not game and not lit(db, neg):
            return None
        g = B.null(name, (0.0, 0.0, 0.0))
        B.kids(halo, g)
        if game:
            vis.append(('v_' + name[5:], name, db, neg, neg if default is None else default))
        return g

    # 2. static layers
    shown('halo_base', 'base', layer=20)
    shown('halo_rails', 'rails')
    if game:
        colours.append(('halo_c_rails', 'halo_rails'))
    shown('halo_arrow_l', 'arrow_l', leaf('tl'))
    shown('halo_arrow_r', 'arrow_r', leaf('tr'))
    shown('halo_boost_off', 'boost_off', leaf('boost'), True)
    shown('halo_boost_on', 'boost_on', leaf('boost'))
    shown('halo_ot_off', 'ot_off', NATIVE['overtake_on'], True)
    shown('halo_ot_on', 'ot_on', NATIVE['overtake_on'])
    shown('halo_batt', 'batt_idle')
    # Active Aero: '=' in straight mode, '//' in corner mode, white in both (docs/research 3.9)
    straight = NATIVE['aero_straight']
    shown('halo_aero_lbl', 'aero_lbl_w')
    shown('halo_aero_eq', 'aero_eq_w', straight)
    shown('halo_aero_sl', 'aero_sl', straight, True)
    for i in range(9):   # unlit digit while not engaged (shown when the leaf is absent), lit digit while engaged
        shown(f'halo_go{i}', f'gear_off_{i}', leaf(f'g{i}'), True)
        shown(f'halo_g{i}', f'gear_{i}', leaf(f'g{i}'))

    # 3. recharge / deploy capsules: one static window per fill level, one of them shown at a time
    c = G['caps']
    for side, sprite in (('rc', 'cap_l_on'), ('dp', 'cap_r_on')):
        x0, y0, x1, y1 = geo.rect(sprite)
        for i in range(1, NLEVEL + 1):
            if not game and not lit(leaf(f'{side}{i:02d}')):
                continue
            top = y0 if i == NLEVEL else CS * (c['yBot'] + (c['yTop'] - c['yBot']) * i / NLEVEL)
            wc = at((x0 + x1) / 2, (top + y1) / 2, -0.12)
            w = B.window(f'halo_{side}_w{i:02d}', wc, K * (x1 - x0), K * (y1 - top))
            B.kids(w, sprite_quad(f'halo_{side}_q{i:02d}', sprite, 22, (wc[0], wc[1], -0.12)))
            B.kids(halo, w)
            if game:
                vis.append((f'v_{side}{i:02d}', w['name'].value, leaf(f'{side}{i:02d}'), False, False))

    # 4. brake / throttle slats: one lit sprite per slat (slat 1 = bottom), lit cumulatively by the DLL's leaves.
    # The Interlagos slats are tilted parallelograms, so per-level horizontal windows would cut through them.
    s = G['stripes']
    for side, lr in (('br', 'l'), ('th', 'r')):
        for i in range(s['n']):
            shown(f'halo_{side}_s{i + 1:02d}', f'str_{lr}_{i}', leaf(f'{side}{i + 1:02d}'))

    # 5. battery: a window slides right over the fill as the charge rises (stock mods icon fill pattern).
    # The preview has no clips: its window sits where the clip would put it for the preview's charge.
    b = G['batt']
    fx0, fy0, fx1, fy1 = geo.rect('batt_fill')
    xs = CS * (b['x'] - b['w'] / 2 + 0.9) - 0.5
    span = CS * (b['w'] - 1.8) + 0.9
    ww, wh = (fx1 - fx0) + 2.0, (fy1 - fy0) + 1.0
    cy = (fy0 + fy1) / 2
    batt_keys = [at(xs + span * f - ww / 2, cy) for f in (0.0, 1.0)]
    bp = batt_keys[0] if game else at(xs + span * pv[NATIVE['battery']] - ww / 2, cy)
    win_anim = B.null('zh_batt_win_anim' if game else 'zs_batt_win', bp, anim=game)
    win = B.window('halo_batt_win', (0.0, 0.0, -0.12), K * ww, K * wh)
    ctr = B.null('zh_batt_ctr_anim' if game else 'zs_batt_ctr', (-bp[0], -bp[1], 0.12), anim=game)
    B.kids(ctr, sprite_quad('halo_batt_fill', 'batt_fill', 23))
    B.kids(halo, B.kids(win_anim, B.kids(win, ctr)))
    shown('halo_bolt', 'bolt', layer=25)
    if game:
        xas += [('x_batt_win', 'zh_batt_win_anim', NATIVE['battery']), ('x_batt_ctr', 'zh_batt_ctr_anim', NATIVE['battery'])]

    # 6. rpm: static texture masks (the bar's shape) over a solid quad that sweeps round the arc's centre.
    # The preview turns the sweep to the preview's revs once, without a clip.
    C, phi0, rkeys, sigma, reach = geo.rpm()
    for mname, msprite, aname, fname, fsprite, layer in (('halo_rpm_mask', 'rpm_team', 'zh_rpm_anim', 'halo_rpm_fill', 'solid_white', 22),
                                                          ('halo_rpm_core_mask', 'rpm_core', 'zh_rpm_core_anim', 'halo_rpm_core_fill', 'solid_core', 23)):
        x0, y0, x1, y1 = geo.rect(msprite)
        mc = at((x0 + x1) / 2, (y0 + y1) / 2)
        m = B.mask(mname, mc, K * (x1 - x0), K * (y1 - y0), B.tex[msprite])
        cs = at(*C)
        if game:
            anim = B.null(aname, (cs[0] - mc[0], cs[1] - mc[1], 0.0), anim=True)
        else:
            anim = B.null(aname.replace('zh_', 'zs_'), (cs[0] - mc[0], cs[1] - mc[1], 0.0),
                          rot_deg=deg(rpm_angle(rkeys, pv[NATIVE['revs']])))
        frame = B.null(aname.replace('zh_', 'halo_') + '_frame', (0.0, 0.0, 0.0), rot_deg=phi0)
        B.kids(frame, B.quad(fname, fsprite, (0.0, -sigma * reach / 2, 0.0), 2 * reach, reach, layer))
        B.kids(halo, B.kids(m, B.kids(anim, frame)))
        if game:
            xas.append(('x_' + aname[3:], aname, NATIVE['revs']))
    if game:
        colours.append(('halo_c_rpm', 'halo_rpm_fill'))

    # 7. text: a rotated, scaled null carries each eText (stock texts are never scaled themselves)
    def text_at(key, cap_pt, angle_canvas, cap_hud, style, halign, box_hud, wrapping, parent=None):
        sh = STYLE_H[style]
        sc = (K * cap_hud / CAP_EM) / (sh / 100.0)
        holder = B.null(f'halo_{key}_n', at(*cap_pt), rot_deg=-angle_canvas, scale=(sc, sc, 1.0))
        box = K * box_hud / sc
        # the game puts the eText origin on the alignment anchor: the left edge ('left'), the right edge ('right')
        # or the centre ('centre'), and boxWidth runs from there (measured in game). So the holder point is the anchor itself.
        t = B.text(f'halo_{key}', (0.0, -CAP_OFF * sh / 100.0, 0.0), style, halign, box, 40, wrapping)
        B.kids(parent if parent is not None else halo, B.kids(holder, t))
        return t

    def label(entry, *args, parent=None):
        """A text and its template binding (game), or the text the preview shows (preview: only if it shows one)."""
        _node, el, tdb, vdb, vdef, neg = entry[:6]
        if game:
            text_at(*args, parent=parent)
            texts.append(entry)
        elif pv.get(tdb) is not None and (vdb is None or lit(vdb, neg)):
            text_at(*args, parent=parent)
            pv_texts.append((el, pv[tdb]))

    # names: "<position> <surname>" along the left lane, the player's line below the rival's (2026 broadcast)
    n, CAP = G['names'], 0.688
    num_end = n.get('numEnd', -58.0)     # lane u where the position number ends (player's line)
    gap = n.get('numGap', 3.0)           # between the number and the surname
    num_box, name_box = n.get('numBox', 14.0), n.get('nameBox', 62.0)

    def name_line(key, v, shift, fs, pos_db, name_db, parent):
        if parent is None:
            return
        ue = num_end + shift
        anchor, ang = geo.lane_chord(ue - num_box, ue + gap + name_box, v, ue)
        label((f't_{key}_pos', f'halo_{key}_pos', pos_db, None, True, False, 'ui32'),     # the game's position is a ui32
              key + '_pos', anchor, ang, CAP * fs, '17_bold', 'right', num_box, 'none', parent=parent)
        anchor, ang = geo.lane_chord(ue - num_box, ue + gap + name_box, v, ue + gap)
        label((f't_{key}_name', f'halo_{key}_name', name_db, None, True, False, 'stri'),
              key + '_name', anchor, ang, CAP * fs, '17_bold', 'left', name_box, 'clampwidth', parent=parent)

    me = group('halo_me', leaf('nm'), default=True)
    name_line('me', n.get('drvV', 0.0), 0.0, n['drvFs'], NATIVE['own_pos'], NATIVE['own_name'], me)
    for i in range(RIVAL_SLOTS):
        slot = group(f'halo_rv{i:02d}', leaf(f'rv{i:02d}'))
        name_line(f'rv{i:02d}', -n['laneGap'], n['rivShift'], n['rivFs'],
                  NATIVE['car_pos'].format(i=i), NATIVE['car_name'].format(i=i), slot)
    tn = G['turn']['num']
    label(('t_tnum', 'halo_tnum', leaf('tnum'), leaf('turn'), False, False),
          'tnum', (tn['x'], tn['y']), tn['rot'], CAP * tn['fs'], '17_bold', 'centre', 24.0, 'none')
    # speed: the DLL's km/h and mph while it reads the car; otherwise the game's own speedo text
    sp, mp = G['speed'], G['mph']
    label(('t_kmh', 'halo_kmh', leaf('kmh'), leaf('spd'), False, False),
          'kmh', (0.0, CS * sp['y']), 0.0, CAP * sp['fs'] * CS, 'OSD_24_bold', 'centre', 44.0, 'none')
    label(('t_mph', 'halo_mph', leaf('mph'), leaf('spd'), False, False),
          'mph', (0.0, CS * mp['y']), 0.0, CAP * mp['fs'] * CS, 'OSD_24_bold', 'centre', 36.0, 'none')
    label(('t_kmhx', 'halo_kmhx', NATIVE['speed_text'], leaf('spd'), True, True),
          'kmhx', (0.0, CS * sp['y']), 0.0, CAP * sp['fs'] * CS, 'OSD_24_bold', 'centre', 44.0, 'none')
    return vis, texts, xas, colours, rkeys, batt_keys, pv_texts


def _box_and_ids(B, geo, stock_ids):
    """8. customisation box = the halo's footprint; 9. element ids (stock ids must not move)."""
    root = B.root
    x0, y0, x1, y1 = geo.rect('base')
    for kid in root['children'].items:
        nm = I._val(kid.get('name'))
        if nm == 'tl_customisation':
            kid.set('position', _vec((K * x0, geo.halo_y + K * -y0, -0.0)))
        elif nm == 'br_customisation':
            kid.set('position', _vec((K * x1, BR_Y, -0.0)))
    ids = []
    for kid in root['children'].items:
        I.recompute_ids(kid, I._val(kid.get('name')), ids)
    I.relookup(B.entry)
    after = {e.path: e.element_id for e, _ in I.Idf(B.idf.to_bytes()).scenes[0].root.walk()}
    changed = [k for k, v in stock_ids.items() if after.get(k) != v]
    assert not changed, ('stock element ids changed', changed[:5])
    assert len(set(ids)) == len(ids), 'elementId collision'
    names = [I._val(e.obj.get('name')) for e, _ in I.Idf(B.idf.to_bytes()).scenes[0].root.walk()]
    dup = {x for x in names if names.count(x) > 1}
    assert not (dup & B.names), ('leaf name reused', dup & B.names)


def build_scene(scene_bytes, mods_bytes, bar_bytes, geo, embs, tex):
    """dial_om_xm with the halo -> (scene bytes, info dict with the clip keys and the template bindings)"""
    B = SceneBuilder(scene_bytes, mods_bytes, bar_bytes, embs, tex)
    bc = _find(B.root, 'boundless_customisation')
    stock_ids = {e.path: e.element_id for e, _ in B.idf.scenes[0].root.walk()}

    # 1. park the stock dial: tiny and far below the screen (the template still drives it, unseen)
    for kid in bc['children'].items:
        nm = I._val(kid.get('name'))
        if nm in STOCK_KIDS:
            p = kid['position'].value
            kid.set('position', _vec((p[0], p[1] - 60.0, p[2])))
            kid.set('scale', _vec((1e-3, 1e-3, 1e-3)))
    halo = B.null('halo', (0.0, geo.halo_y, 0.0))
    bc['children'].items.append(halo)
    vis, texts, xas, colours, rkeys, batt_keys, _ = _halo(B, geo, halo)
    _box_and_ids(B, geo, stock_ids)

    info = dict(vis=vis, texts=texts, xas=xas, colours=colours, rpm_keys=rkeys, batt_keys=batt_keys,
                rpm_static={a: None for a in ('zh_rpm_anim', 'zh_rpm_core_anim')}, n_new=len(B.names))
    # static positions of the anim nodes (their clips keep translation fixed)
    for e, _ in I.Idf(B.idf.to_bytes()).scenes[0].root.walk():
        nm = I._val(e.obj.get('name'))
        if nm in ('zh_rpm_anim', 'zh_rpm_core_anim'):
            info['rpm_static'][nm] = tuple(e.obj['position'].value[:3])
    return B.idf.to_bytes(), info


def build_preview(scene_bytes, mods_bytes, bar_bytes, geo, embs, tex):
    """dial_complete with a static copy of the halo in the PREVIEW state (null 'halo_pv'), for the HUD editor.
    The stock dial stays as it is (the .uipre hides it in the editor only); the box becomes the halo's footprint.
    -> (scene bytes, {'texts': [(element, preview text)], 'n_new': ...})"""
    B = SceneBuilder(scene_bytes, mods_bytes, bar_bytes, embs, tex, scene=PREVIEW_SCENE, remap=PREVIEW_SPRITES)
    bc = _find(B.root, 'boundless_customisation')
    stock_ids = {e.path: e.element_id for e, _ in B.idf.scenes[0].root.walk()}
    assert {I._val(k.get('name')) for k in bc['children'].items} >= set(STOCK_KIDS)
    pv = B.null(PREVIEW_ROOT, (0.0, geo.halo_y, 0.0))
    bc['children'].items.append(pv)
    *_, pv_texts = _halo(B, geo, pv, PREVIEW)
    _box_and_ids(B, geo, stock_ids)
    return B.idf.to_bytes(), {'texts': pv_texts, 'n_new': len(B.names)}


def build_preview_uipre(uipre_bytes, pv_texts):
    """dial_complete's editor preview data: the stock dial's four parts hidden, the halo copy's texts filled in.
    The .uipre names each element by djb2 of its name (stock: 1073894029 = speedo_number '135')."""
    p = Pkg(uipre_bytes)
    assert p.root['TargetId'].value == I.component_id(PREVIEW_SCENE)
    els = p.root['Elements']

    def model(key, vtype):
        for el in els.items:
            for st in (el.get('Setters').items if el.get('Setters') is not None else []):
                if st['Key'].value == key and st['Value'].type == vtype:
                    return el, st
        raise KeyError(f'no stock {vtype} setter {key}')

    have = {el['Id'].value for el in els.items}
    for name, key, vtype, value in ([(nm, UIPRE_VISIBLE, 'bool', False) for nm in STOCK_KIDS] +
                                    [(el, UIPRE_TEXT, 'stri', s) for el, s in pv_texts]):
        el_m, st_m = model(key, vtype)
        el, st = I.clone_node(el_m), I.clone_node(st_m)
        el['Id'].value = N.djb2(name)
        st['Value'].value = value
        el['Setters'].items = [st]
        assert el['Id'].value not in have, ('preview element id reused', name)
        have.add(el['Id'].value)
        els.items.append(el)
    return p.to_bytes(), len(STOCK_KIDS) + len(pv_texts)


# ---------------------------------------------------------------- clips + string table
def _clip(tmpl_bytes, node, name_index, chans):
    """chans: [(interp, type, flags, times, keys)] -> (temp, syst) of an AnimClip that animates `node`."""
    p = Pkg(tmpl_bytes)
    pk_t = p.root['packets'].items[0]
    syst = bytearray()
    packets = []

    def align():
        while len(syst) % 16:
            syst.extend(b'\0')

    for interp, typ, flags, times, keys in chans:
        align()
        tp = len(syst)
        syst += struct.pack(f'<{len(times)}f', *times)
        align()
        kp = len(syst)
        for k in keys:
            syst += struct.pack(f'<{len(k)}f', *k)
        pk = I.clone_node(pk_t)
        pk['maxtime'].value, pk['mintime'].value, pk['interpolator'].value = float(ANIM_T), 0.0, interp
        ch = pk['channels'].items[0]
        ch['name_index'].value = name_index
        ch['mins'].value = 0
        ch['misc'].value = (0x80210 << 32) | (flags << 24) | (typ << 16) | len(times)
        ch['name'].value = node
        ch['keyptr'].value, ch['timesptr'].value = kp, tp
        pk['channels'].items = [ch]
        packets.append(pk)
    align()
    p.root['packets'].items = packets
    p.root['string_table'].value = STRTAB
    return p.to_bytes(), bytes(syst)


def build_clips(tmpl_clip_bytes, strtab_bytes, info):
    st = Pkg(strtab_bytes)
    strings = st.root['strings']
    have = [v.value for v in strings.items]
    assert have == sorted(have) and all(n > have[-1] for n in ANIM_NODES) and ANIM_NODES == sorted(ANIM_NODES)
    for nm in ANIM_NODES:
        strings.items.append(Val(strings.items[0].type, nm))
    index = {nm: len(have) + i for i, nm in enumerate(ANIM_NODES)}
    ident = (0.0, 0.0, 0.0, -1.0)
    one = (1.0, 1.0, 1.0)
    clips = {}
    bk = info['batt_keys']
    win = [tuple(k) for k in bk]
    ctr = [(-k[0], -k[1], 0.12) for k in bk]
    for nm, keys in (('zh_batt_win_anim', win), ('zh_batt_ctr_anim', ctr)):
        clips[nm] = _clip(tmpl_clip_bytes, nm, index[nm], [
            (5, 3, 0x80, [0.0, ANIM_T], keys),
            (2, 1, 0x84, [0.0], [ident]),
            (5, 2, 0x80, [0.0], [one])])
    for nm in ('zh_rpm_anim', 'zh_rpm_core_anim'):
        pos = info['rpm_static'][nm]
        times = [f * ANIM_T for f, _ in info['rpm_keys']]
        quats = [tuple(quat_z(deg(a))) for _, a in info['rpm_keys']]
        clips[nm] = _clip(tmpl_clip_bytes, nm, index[nm], [
            (5, 3, 0x80, [0.0], [pos]),
            (2, 1, 0x84, times, quats),
            (5, 2, 0x80, [0.0], [one])])
    return st.to_bytes(), clips


# ---------------------------------------------------------------- template
def _bool_prop(default, db, negate=False):
    items = [('value', Val('bool', bool(default)))]
    if db:
        items.append(('dbentry', U.S(db)))
    if negate:
        items.insert(0, ('dbentrynegate', Val('bool', True)))
    return U.obj(*items)


def _bindings(x, out, skip=None):
    """(prop name, value type, dbentry) of every bound property under x; skip: a node name to leave out."""
    if N.is_node(x):
        if skip and N.name(x) == skip:
            return
        for k, v in x.items[N.PROPS].items:
            if isinstance(v, Obj) and v.get('dbentry') is not None:
                val = v.get('value')
                out.append((N.name(x), k.value, val.type if isinstance(val, Val) else None, v.get('dbentry').value))
        for c in N.children(x):
            _bindings(c, out, skip)
    elif isinstance(x, Arr):
        for c in x.items:
            _bindings(c, out, skip)
    elif isinstance(x, Obj):
        for _k, v in x.items:
            _bindings(v, out, skip)
    return out


def check_binding_types(stock_root, kids):
    """Fail the build if a halo property's value type differs from the type of the value it is bound to."""
    stock = {}
    for _n, _k, t, db in _bindings(stock_root, [], skip='halo_ctl'):
        stock.setdefault(db, set()).add(t)
    bad, checked = [], 0
    for kid in kids:
        for node, prop, t, db in _bindings(kid, []):
            if db.startswith(VM):
                want = {'stri'} if db[len(VM):] in DLL_TEXT_LEAVES else {'bool'}
            else:
                key = re.sub(r'#session\.cars\.car\d+\.', '#session.current_car.', db)
                want = stock.get(key) or ({KNOWN_TYPES[key]} if key in KNOWN_TYPES else None)
            if not want:
                bad.append(f'{node}.{prop} <- {db}: type unknown (no stock binding, not in KNOWN_TYPES)')
            elif t not in want:
                bad.append(f'{node}.{prop} <- {db}: {t}, the value is {"/".join(sorted(want))}')
            checked += 1
    if bad:
        raise SystemExit('template binding types:\n  ' + '\n  '.join(bad))
    print(f'binding types: {checked} halo bindings match their values')




def _node_at(root, path):
    """The UI node at a dotted path (root name first); its id must be djb2 of the path."""
    found = []

    def walk(x, trail):
        if N.is_node(x):
            t = trail + [N.name(x)]
            if '.'.join(t) == path:
                found.append(x)
            for c in N.children(x):
                walk(c, t)
        elif isinstance(x, Arr):
            for c in x.items:
                walk(c, trail)
        elif isinstance(x, Obj):
            for k, v in x.items:
                walk(v, trail)

    walk(root, [])
    assert len(found) == 1, (path, len(found))
    assert found[0].items[N.PROPS]['id'].value == N.djb2(path), path
    return found[0]


def build_template(ui_bytes, info):
    p = Pkg(ui_bytes)
    target = _node_at(p.root, TEMPLATE_PARENT)
    assert not any(N.name(c) == 'halo_ctl' for c in N.children(target)), 'template already has the halo'

    kids = []
    for nm, el, db, neg, default in info['vis']:
        kids.append(U.node(nm, 'UIGP', [('visible', _bool_prop(default, db, neg))], layout=[el], behav=U.GROUP_BEHAVIOURS))
    for nm, el in info['colours']:
        kids.append(U.node(nm, 'UIGP', [('colourOverride', U.obj(('value', Val('rgba', '#ffffffff')), ('dbentry', U.S(TEAM))))],
                           layout=[el], behav=U.GROUP_BEHAVIOURS))
    for nm, el, text_db, vis_db, vis_default, neg, *vtype in info['texts']:
        vtype = vtype[0] if vtype else 'stri'
        props = [('text', U.prop(vtype, 1 if vtype == 'ui32' else '', text_db))]   # ui32 default 1, as the stock labels
        if vis_db:
            props.insert(0, ('visible', _bool_prop(vis_default, vis_db, neg)))
        kids.append(U.node(nm, 'UILB', props, layout=[el], behav=U.LABEL_BEHAVIOURS))
    xa_behav = ('NBFC', 'NBXA', 'NBEL', 'NBDC', 'NBMG', 'NBVM', 'NBAN', 'NBAC', 'NBOS', 'NBMO')
    for nm, el, db in info['xas']:
        kids.append(U.node(nm, 'UIXA', [('fraction', U.prop('fp32', 0.0, db))], layout=[el], behav=xa_behav))
    grp = U.node('halo_ctl', 'UIGP', [], kids=kids, behav=U.GROUP_BEHAVIOURS)
    check_binding_types(p.root, kids)
    N.fix_ids(grp, TEMPLATE_PARENT)
    target.items[N.CHILDREN].items.append(grp)
    return p.to_bytes(), len(kids)


def add_preview_control(ui_bytes, parent):
    """Under a node that drives dial_complete in game (PREVIEW_PARENTS: the hud_f1_dial template, the spectator HUD's
    modern_dial), a group that hides the editor's halo copy and shows the stock dial's four parts. Static values,
    no bindings: in game the F1 25 dial looks as before even if the game also applied the .uipre there."""
    p = Pkg(ui_bytes)
    target = _node_at(p.root, parent)
    assert not any(N.name(c) == PREVIEW_CTL for c in N.children(target)), 'already has the preview control'
    kids = [U.hidden('v_' + PREVIEW_ROOT, PREVIEW_ROOT)]
    kids += [U.node('v_' + nm, 'UIGP', [('visible', U.prop('bool', True))], layout=[nm], behav=U.GROUP_BEHAVIOURS)
             for nm in STOCK_KIDS]
    grp = U.node(PREVIEW_CTL, 'UIGP', [], kids=kids, behav=U.GROUP_BEHAVIOURS)
    assert not _bindings(grp, []), 'the preview control binds nothing'
    check_binding_types(p.root, kids)
    N.fix_ids(grp, parent)
    target.items[N.CHILDREN].items.append(grp)
    return p.to_bytes(), len(kids)
