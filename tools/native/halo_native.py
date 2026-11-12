"""Game-native halo HUD: the dial_om_xm scene with the halo built in, its anim clips and string table, and the
hud_dynamic_templates.ui nodes that drive it (native VM values + the addon DLL's view_model_data.hud_halo_* leaves).
Plus the HUD editor's preview: a static copy of the halo in dial_complete, its .uipre, and the template nodes that
keep that copy out of the game (see PREVIEW_SCENE).

Coordinates: HUD units (u, v) = 1 px of the 640x360 mock-up frame, origin at the dial centre, v down.
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
    # car classes (docs/halo-car-classes.md 2.2): what the stock 2025 and F2 dials read
    'has_ers': 'has_ers',                          # the stock 2025 dial's ers group: enabled / visible (bool)
    'ers_mode': 'ers_mode',                        # ui32, view-model order: 0 None, 1 Medium, 2 Hotlap, 3 Overtake
    'drs': 'drs_pit_state',                        # MVCD only (the stock DRS widget's ers_state): never a typed property
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
PREVIEW_STRTAB = PREVIEW_SCENE + '?context=animstringtable&file=0'

# Car classes (design decisions): the halo in F1 25's own 2025 cars and in F2 cars
# too. The template the game runs tells the car class (doc 2.1), so each class has its own live copy of the halo in
# the scene its dial template drives (hud_f1_dial: dial_complete, beside the editor copy halo_pv; hud_f2_dial:
# dial_f2_complete). The copy is hidden in the scene, so the HUD editor and the spectator HUD never show it; its own
# template group halo_ctl under the dial's [F1HD] shows it while the DLL's leaf cls (setting all_cars) is on, and the
# stock dial's four parts while it is off. Element names start with the copy's root name; the anim nulls keep the
# 2026 names (zh_*), one live halo per scene.
#   2025: the DRS pill in place of the active-aero symbol; in the pill area the ERS MODE caption and the current
#         deploy mode; battery and capsules (120 kW scale: DLL leaves rk / dk) while the game says the car has ERS.
#   f2:   the DRS pill; no battery, capsules or pills (the F2 base has no capsules). Nothing else moves.
F2_SCENE = 'eaid://ui_package/art/osd/components/dial/dial_f2_complete.idf'
F2_STRTAB = F2_SCENE + '?context=animstringtable&file=0'
CLASSES = {
    '2025': dict(scene=PREVIEW_SCENE, strtab=PREVIEW_STRTAB, parent=PREVIEW_PARENTS['hud_f1_dial'], root='h25',
                 quad='central_bg_fill', base='base', ers=True),
    # the F2 scene's fill quad has its pivot off the mesh centre: its edge quad (centred, slot central_bg_edge) is
    # cloned instead, through bindings of its own slot (resources.EMB_EDGE)
    'f2': dict(scene=F2_SCENE, strtab=F2_STRTAB, parent='hud_f2_dial.osd_visibility_option.f2_dial_child', root='hf2',
               quad='central_bg_edge', base='base_f2', ers=False),
}
DRS_LOOKS = ('off', 'avail', 'open')
# drs_pit_state -> the DRS pill's look (design decisions): grey = unavailable, also the pit
# limiter states; outline = DRS enabled (the zone ahead or available now); green = open. In the stock MVCD's order.
DRS_STATES = {'invalid': 'off', 'drs_unavailable': 'off', 'drs_distance': 'avail', 'drs_active': 'avail',
              'drs_live': 'open', 'pit_distance': 'off', 'pit_active': 'off', 'pit_live': 'off'}
# the 2025 deploy mode pills: (ers_mode value, key, sprite); OVERTAKE is the 2026 OVERTAKE pill
ERS_MODES = [(0, 'none', 'ers_none'), (1, 'medium', 'ers_medium'), (2, 'hotlap', 'ers_hotlap'), (3, 'ot', 'ot_on')]


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
    def __init__(self, scene_bytes, mods_bytes, bar_bytes, embs, tex, scene=SCENE, remap=None, quad='central_bg_fill',
                 text_from=None):
        """quad: the scene's own quad element the sprite quads clone (its mesh's material slot has the same name;
        embs must bind that slot). text_from: another scene's bytes whose speedo_number the texts clone (default:
        this scene's)."""
        self.idf = I.Idf(scene_bytes)
        self.entry = self.idf.scenes[0].entry
        self.root = self.entry['scene']
        self.scene = scene
        assert self.idf.scenes[0].name == I.component_id(scene), scene
        mods_root = I.Idf(mods_bytes).scenes[0].entry['scene']
        bar_root = I.Idf(bar_bytes).scenes[0].entry['scene']
        self.T_quad = _find(self.root, quad)
        self.T_text = _find(I.Idf(text_from).scenes[0].entry['scene'] if text_from else self.root, 'speedo_number')
        self.T_null = _find(mods_root, 'mod_1_icon_fill_mask_anim')
        self.T_win = _find(mods_root, 'mod_1_icon_fill_mask')
        self.T_mask = _find(bar_root, 'ers_battery_fill_mask')
        assert all(x is not None for x in (self.T_quad, self.T_text, self.T_null, self.T_win, self.T_mask))
        g = self.T_quad['geoms'].items[0]
        mesh = f'{scene}/{quad}?context=render'   # the scene's own quad mesh (material slot named like the element)
        assert g['resourceid'].value == mesh
        assert g['asset'].value == int.from_bytes(hashlib.md5(mesh.encode()).digest()[:8], 'big')
        # the mesh: a quad in the x-z plane, centred on its pivot (checked); its size from the element's extents
        lo, hi = I.get_param(self.T_quad, 'minExtents'), I.get_param(self.T_quad, 'maxExtents')
        piv = I.get_param(self.T_quad, 'pivotTrans')
        assert abs(lo[0] + hi[0]) < 1e-4 and abs(lo[2] + hi[2]) < 1e-4 and abs(piv[0]) < 1e-4 and abs(piv[2]) < 1e-4, \
            (quad, lo, hi, piv)
        if quad == 'central_bg_fill':
            # the dial scenes' fill quad: 4.48 x 1.92, the exact values every build since 0.1.0 divides by
            assert abs(hi[0] - lo[0] - 4.48) < 1e-4 and abs(hi[2] - lo[2] - 1.92) < 1e-4, (lo, hi)
            self.mesh_w, self.mesh_h = 4.48, 1.92
        else:
            self.mesh_w, self.mesh_h = hi[0] - lo[0], hi[2] - lo[2]
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

    def null(self, name, pos, rot_deg=None, scale=(1, 1, 1), anim=False, hidden=False):
        o = self._base(self.T_null, name, pos, quat_z(rot_deg) if rot_deg is not None else None, scale)
        if anim:
            entry = I.clone_node(self.T_null['anims'].items[0])
            entry.set('asset', Val('stri', f'{self.scene}/{name}?context=animation'))
            o.set('anims', Arr([entry], self.T_null['anims'].tag))
        if hidden:
            # hidden in the scene itself: only a template's bound visible shows it. Stock does the same:
            # dial_om_xm's speedo_number and anti_stall_text are isHidden, and hud_dynamic_templates.ui shows them
            # (visible bound to speed_visible / anti_stall_visible)
            _param(o, 'isHidden', True, 'bool')
        return o

    def quad(self, name, sprite, pos, w, h, layer):
        """A textured quad of w x h scene units centred on pos, showing sprite's material."""
        o = self._base(self.T_quad, name, pos, [-0.707107, -0.0, 0.0, -0.707107], (w / self.mesh_w, 1.0, h / self.mesh_h))
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


def _halo(B, geo, halo, pv=None, cls=None):
    """Add the halo's elements under the null `halo`.

    pv None (the game's dial_om_xm): every element, and the template bindings that drive them.
    pv a state (PREVIEW; dial_complete in the HUD editor, where no template runs): only what that state shows, the
    battery window and rpm sweep at static positions, and the texts it shows (for the .uipre).
    cls None: the 2026 halo. cls '2025' / 'f2': that car class's live halo (CLASSES): element names start with its
    root's name; the DRS pill replaces the active-aero symbol; 2025 cars show the ERS mode in the pill area and the
    capsules on the 120 kW scale, F2 cars no battery, capsules or pills.
    -> (vis, texts, xas, colours, rpm keys, battery keys, preview texts [(element, text)], shows, decisions)"""
    G, CS, S = geo.G, geo.CS, geo.S
    game = pv is None
    cl = CLASSES[cls] if cls else None
    assert game or cl is None, 'the editor preview is the 2026 halo'
    pfx = cl['root'] + '_' if cl else 'halo_'
    energy = cl is None or cl['ers']
    vis = []      # (template node name, element, bool binding, negate, value while the binding is absent)
    texts = []    # (template node name, element, text binding, visible binding or None, visible default, negate)
    xas = []      # (template node name, anim element, VM fraction binding)
    colours = []  # (template node name, element)
    shows = []    # (template node name, element, static visible): parts a decision node shows and hides
    decisions = []  # the decision nodes (car classes): MVCD / SVCD, their bindings and their events' show / hide
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

    def shown(key, sprite, db=None, neg=False, parent=None, layer=22):
        """A sprite quad (element pfx + key); with db, a template node 'v_' + key shows it while db (negated: while
        not db) is true. A hidden parent null hides everything under it, so nesting gives AND."""
        name = pfx + key
        if game or lit(db, neg):
            B.kids(parent if parent is not None else halo, sprite_quad(name, sprite, layer))
        if db and game:
            vis.append(('v_' + key, name, db, neg, neg))

    def group(key, db, neg=False, default=None, parent=None, hidden=False):
        """A null a template node shows while db (negated: while not db) is true; what is under it shows only while
        it does. hidden: hidden in the scene too, so it stays hidden where no halo template runs (the spectator HUD,
        docs/qa/discrepancies.md D10). Preview: None when the preview state hides it."""
        if not game and not lit(db, neg):
            return None
        name = pfx + key
        g = B.null(name, (0.0, 0.0, 0.0), hidden=hidden and game)
        B.kids(parent if parent is not None else halo, g)
        if game:
            vis.append(('v_' + key, name, db, neg, neg if default is None else default))
        return g

    def switched(key, sprite, default, parent=None, layer=22):
        """A sprite quad a decision node shows and hides: template node 'v_' + key, static visible `default` until
        the node's first event."""
        name = pfx + key
        B.kids(parent if parent is not None else halo, sprite_quad(name, sprite, layer))
        shows.append(('v_' + key, name, default))
        return 'v_' + key

    # the G-force meter's switch (setting g_meter = leaf gm; docs/gmeter/design.md). The meter replaces the
    # centre's speed, Boost, Overtake, battery and capsules: halo_std holds those and shows while gm is off or absent;
    # halo_gmeter holds the meter (at the end) and is hidden in the scene too. The editor preview shows the standard
    # halo with no group null, so its scene is as before.
    std = group('std', leaf('gm'), True, default=True) if game else halo
    gmv = group('gmeter', leaf('gm'), hidden=True) if game else None
    # a 2025 car's energy parts (battery, capsules, ERS mode) show while the game says the car has ERS: the stock
    # 2025 dial's ers group binds has_ers the same way (bool, default False)
    ers = group('ers', NATIVE['has_ers'], default=False, parent=std) if cl and cl['ers'] else std

    # 2. static layers
    shown('base', cl['base'] if cl else 'base', parent=std, layer=20)
    shown('rails', 'rails')
    if game:
        colours.append(('halo_c_rails', pfx + 'rails'))
    shown('arrow_l', 'arrow_l', leaf('tl'))
    shown('arrow_r', 'arrow_r', leaf('tr'))
    shown('turn_lbl', 'turn_lbl', leaf('turn'))   # TURN shows with its number (was part of the base)
    if cl is None:
        shown('boost_off', 'boost_off', leaf('boost'), True, parent=std)
        shown('boost_on', 'boost_on', leaf('boost'), parent=std)
        shown('ot_off', 'ot_off', NATIVE['overtake_on'], True, parent=std)
        shown('ot_on', 'ot_on', NATIVE['overtake_on'], parent=std)
    elif cl['ers']:
        # the ERS deploy mode (2025 cars, doc 2.4): the caption in the Boost slot, one pill per mode in the Overtake
        # slot, each shown by its own SVCD on the game's ers_mode (ui32, the stock tag); none shows until one fires
        shown('ers_cap', 'ers_cap', parent=ers)
        for value, key, sprite in ERS_MODES:
            node = switched('ers_' + key, sprite, False, parent=ers)
            decisions.append(dict(type='SVCD', name='ers_mode_' + key, db=NATIVE['ers_mode'], value=['ui32', value],
                                  events=[['yes', [[node, 'show']]], ['no', [[node, 'hide']]]]))
    if energy:
        shown('batt', 'batt_idle', parent=ers)
    if cl is None:
        # Active Aero: '=' in straight mode, '//' in corner mode, white in both (docs/research 3.9)
        straight = NATIVE['aero_straight']
        shown('aero_lbl', 'aero_lbl_w')
        shown('aero_eq', 'aero_eq_w', straight)
        shown('aero_sl', 'aero_sl', straight, True)
    else:
        # the DRS pill in the active-aero spot (doc 2.3): one sprite per look, shown by an MVCD on the game's
        # drs_pit_state like the stock DRS widget's; grey until the first state arrives
        nodes = {look: switched('drs_' + look, 'drs_' + look, look == 'off') for look in DRS_LOOKS}
        decisions.append(dict(type='MVCD', name='drs_state', db=NATIVE['drs'],
                              events=[[state, [[nodes[x], 'show' if x == look else 'hide'] for x in DRS_LOOKS]]
                                      for state, look in DRS_STATES.items()]))
    for i in range(9):   # unlit digit while not engaged (shown when the leaf is absent), lit digit while engaged
        shown(f'go{i}', f'gear_off_{i}', leaf(f'g{i}'), True)
        shown(f'g{i}', f'gear_{i}', leaf(f'g{i}'))

    # 3. recharge / deploy capsules: one static window per fill level, one of them shown at a time. 2025 cars: the
    # DLL's 120 kW leaves rk / dk (docs/halo-car-classes.md 7), the same windows
    c = G['caps']
    sides = (('rc', 'rc', 'cap_l_on'), ('dp', 'dp', 'cap_r_on')) if cl is None else (('rc', 'rk', 'cap_l_on'), ('dp', 'dk', 'cap_r_on'))
    for side, lv, sprite in (sides if energy else ()):
        x0, y0, x1, y1 = geo.rect(sprite)
        for i in range(1, NLEVEL + 1):
            if not game and not lit(leaf(f'{lv}{i:02d}')):
                continue
            top = y0 if i == NLEVEL else CS * (c['yBot'] + (c['yTop'] - c['yBot']) * i / NLEVEL)
            wc = at((x0 + x1) / 2, (top + y1) / 2, -0.12)
            w = B.window(f'{pfx}{side}_w{i:02d}', wc, K * (x1 - x0), K * (y1 - top))
            B.kids(w, sprite_quad(f'{pfx}{side}_q{i:02d}', sprite, 22, (wc[0], wc[1], -0.12)))
            B.kids(ers, w)
            if game:
                vis.append((f'v_{side}{i:02d}', w['name'].value, leaf(f'{lv}{i:02d}'), False, False))

    # 4. brake / throttle slats: one lit sprite per slat (slat 1 = bottom), lit cumulatively by the DLL's leaves.
    # The Interlagos slats are tilted parallelograms, so per-level horizontal windows would cut through them.
    s = G['stripes']
    for side, lr in (('br', 'l'), ('th', 'r')):
        for i in range(s['n']):
            shown(f'{side}_s{i + 1:02d}', f'str_{lr}_{i}', leaf(f'{side}{i + 1:02d}'))

    # 5. battery: a window slides right over the fill as the charge rises (stock mods icon fill pattern).
    # The preview has no clips: its window sits where the clip would put it for the preview's charge.
    batt_keys = []
    if energy:
        b = G['batt']
        fx0, fy0, fx1, fy1 = geo.rect('batt_fill')
        xs = CS * (b['x'] - b['w'] / 2 + 0.9) - 0.5
        span = CS * (b['w'] - 1.8) + 0.9
        ww, wh = (fx1 - fx0) + 2.0, (fy1 - fy0) + 1.0
        cy = (fy0 + fy1) / 2
        batt_keys = [at(xs + span * f - ww / 2, cy) for f in (0.0, 1.0)]
        bp = batt_keys[0] if game else at(xs + span * pv[NATIVE['battery']] - ww / 2, cy)
        win_anim = B.null('zh_batt_win_anim' if game else 'zs_batt_win', bp, anim=game)
        win = B.window(pfx + 'batt_win', (0.0, 0.0, -0.12), K * ww, K * wh)
        ctr = B.null('zh_batt_ctr_anim' if game else 'zs_batt_ctr', (-bp[0], -bp[1], 0.12), anim=game)
        B.kids(ctr, sprite_quad(pfx + 'batt_fill', 'batt_fill', 23))
        B.kids(ers, B.kids(win_anim, B.kids(win, ctr)))
        shown('bolt', 'bolt', parent=ers, layer=25)
        if game:
            xas += [('x_batt_win', 'zh_batt_win_anim', NATIVE['battery']), ('x_batt_ctr', 'zh_batt_ctr_anim', NATIVE['battery'])]

    # 6. rpm: static texture masks (the bar's shape) over a solid quad that sweeps round the arc's centre.
    # The preview turns the sweep to the preview's revs once, without a clip.
    C, phi0, rkeys, sigma, reach = geo.rpm()
    for mkey, msprite, aname, fkey, fsprite, layer in (('rpm_mask', 'rpm_team', 'zh_rpm_anim', 'rpm_fill', 'solid_white', 22),
                                                        ('rpm_core_mask', 'rpm_core', 'zh_rpm_core_anim', 'rpm_core_fill', 'solid_core', 23)):
        x0, y0, x1, y1 = geo.rect(msprite)
        mc = at((x0 + x1) / 2, (y0 + y1) / 2)
        m = B.mask(pfx + mkey, mc, K * (x1 - x0), K * (y1 - y0), B.tex[msprite])
        cs = at(*C)
        if game:
            anim = B.null(aname, (cs[0] - mc[0], cs[1] - mc[1], 0.0), anim=True)
        else:
            anim = B.null(aname.replace('zh_', 'zs_'), (cs[0] - mc[0], cs[1] - mc[1], 0.0),
                          rot_deg=deg(rpm_angle(rkeys, pv[NATIVE['revs']])))
        frame = B.null(pfx + aname[3:] + '_frame', (0.0, 0.0, 0.0), rot_deg=phi0)
        B.kids(frame, B.quad(pfx + fkey, fsprite, (0.0, -sigma * reach / 2, 0.0), 2 * reach, reach, layer))
        B.kids(halo, B.kids(m, B.kids(anim, frame)))
        if game:
            xas.append(('x_' + aname[3:], aname, NATIVE['revs']))
    if game:
        colours.append(('halo_c_rpm', pfx + 'rpm_fill'))

    # 7. text: a rotated, scaled null carries each eText (stock texts are never scaled themselves)
    def text_at(key, cap_pt, angle_canvas, cap_hud, style, halign, box_hud, wrapping, parent=None):
        sh = STYLE_H[style]
        sc = (K * cap_hud / CAP_EM) / (sh / 100.0)
        holder = B.null(f'{pfx}{key}_n', at(*cap_pt), rot_deg=-angle_canvas, scale=(sc, sc, 1.0))
        box = K * box_hud / sc
        # the game puts the eText origin on the alignment anchor: the left edge ('left'), the right edge ('right')
        # or the centre ('centre'), and boxWidth runs from there (measured in game). So the holder point is the anchor itself.
        t = B.text(pfx + key, (0.0, -CAP_OFF * sh / 100.0, 0.0), style, halign, box, 40, wrapping)
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
        label((f't_{key}_pos', f'{pfx}{key}_pos', pos_db, None, True, False, 'ui32'),     # the game's position is a ui32
              key + '_pos', anchor, ang, CAP * fs, '17_bold', 'right', num_box, 'none', parent=parent)
        anchor, ang = geo.lane_chord(ue - num_box, ue + gap + name_box, v, ue + gap)
        label((f't_{key}_name', f'{pfx}{key}_name', name_db, None, True, False, 'stri'),
              key + '_name', anchor, ang, CAP * fs, '17_bold', 'left', name_box, 'clampwidth', parent=parent)

    me = group('me', leaf('nm'), default=True)
    name_line('me', n.get('drvV', 0.0), 0.0, n['drvFs'], NATIVE['own_pos'], NATIVE['own_name'], me)
    for i in range(RIVAL_SLOTS):
        slot = group(f'rv{i:02d}', leaf(f'rv{i:02d}'))
        name_line(f'rv{i:02d}', -n['laneGap'], n['rivShift'], n['rivFs'],
                  NATIVE['car_pos'].format(i=i), NATIVE['car_name'].format(i=i), slot)
    tn = G['turn']['num']
    label(('t_tnum', pfx + 'tnum', leaf('tnum'), leaf('turn'), False, False),
          'tnum', (tn['x'], tn['y']), tn['rot'], CAP * tn['fs'], '17_bold', 'centre', 24.0, 'none')
    # speed: the DLL's km/h and mph while it reads the car; otherwise the game's own speedo text
    sp, mp = G['speed'], G['mph']
    label(('t_kmh', pfx + 'kmh', leaf('kmh'), leaf('spd'), False, False),
          'kmh', (0.0, CS * sp['y']), 0.0, CAP * sp['fs'] * CS, 'OSD_24_bold', 'centre', 44.0, 'none', parent=std)
    label(('t_mph', pfx + 'mph', leaf('mph'), leaf('spd'), False, False),
          'mph', (0.0, CS * mp['y']), 0.0, CAP * mp['fs'] * CS, 'OSD_24_bold', 'centre', 36.0, 'none', parent=std)
    label(('t_kmhx', pfx + 'kmhx', NATIVE['speed_text'], leaf('spd'), True, True),
          'kmhx', (0.0, CS * sp['y']), 0.0, CAP * sp['fs'] * CS, 'OSD_24_bold', 'centre', 44.0, 'none', parent=std)

    # the G-force meter (under halo_gmeter): its base (the halo with the meter's centre: no capsules, speed labels,
    # Boost, Overtake or battery; the three rings), the label (lit while the DLL reads the car's g, dimmed while not),
    # the cyan segments, the white and red bars on the nearest axis, and the value from one sprite per digit and place
    # (white, or red while the flash runs). The DLL lights one units and one tenths digit (native/src/leaves.hpp).
    if gmv is not None:
        shown('gbase', 'base_g', parent=gmv, layer=20)
        shown('glbl', 'g_lbl', leaf('gok'), parent=gmv, layer=24)
        shown('glbld', 'g_lbl_dim', leaf('gok'), True, parent=gmv, layer=24)
        for k in range(8):                                   # segment k is centred on k * 45 degrees (0 right, 90 down)
            shown(f'gs{k}', f'g_seg_{k}', leaf(f'gs{k}'), parent=gmv)
        for a in range(4):                                   # axis 0 right, 1 down, 2 left, 3 up
            shown(f'gw{a}', f'g_w_{a}', leaf(f'gw{a}'), parent=gmv)
            shown(f'gr{a}', f'g_r_{a}', leaf(f'gr{a}'), parent=gmv)
        val = group('gval', leaf('gok'), parent=gmv)
        for r, sub in (('', group('gvw', leaf('gred'), True, parent=val)), ('r', group('gvr', leaf('gred'), parent=val))):
            for d in range(10):
                shown(f'gu{r}{d}', f'g_u{r}_{d}', leaf(f'gu{d}'), parent=sub, layer=26)
                shown(f'gt{r}{d}', f'g_t{r}_{d}', leaf(f'gt{d}'), parent=sub, layer=26)
            shown('gdot' + r, 'g_dot' + ('_r' if r else ''), parent=sub, layer=26)
    return vis, texts, xas, colours, rkeys, batt_keys, pv_texts, shows, decisions


def _box_and_ids(B, geo, stock_ids):
    """8. customisation box = the halo's footprint; 9. element ids (stock ids must not move)."""
    root = B.root
    x0, y0, x1, y1 = geo.rect('base')
    # the box points: children of the scene root (dial_om_xm, dial_complete) or of ui_visibility_hook (the F2 dial)
    tl, br = _find(root, 'tl_customisation'), _find(root, 'br_customisation')
    assert tl is not None and br is not None
    tl.set('position', _vec((K * x0, geo.halo_y + K * -y0, -0.0)))
    br.set('position', _vec((K * x1, BR_Y, -0.0)))
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
    vis, texts, xas, colours, rkeys, batt_keys, *_ = _halo(B, geo, halo)
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
    pv_texts = _halo(B, geo, pv, PREVIEW)[6]
    _box_and_ids(B, geo, stock_ids)
    return B.idf.to_bytes(), {'texts': pv_texts, 'n_new': len(B.names)}


def build_class_scene(scene_bytes, mods_bytes, bar_bytes, text_bytes, geo, embs, tex, cls):
    """A car class's live halo (CLASSES[cls]) in its dial scene: the null <root> under boundless_customisation,
    hidden in the scene (only the class's template group shows it). The stock dial stays as it is (the template hides
    its four parts while the halo shows); the box becomes the halo's footprint, as in the other dial scenes.
    dial_complete arrives with the editor copy halo_pv in it. text_bytes: dial_om_xm, whose speedo_number the texts
    clone, like the 2026 halo's.
    -> (scene bytes, info dict: build_scene's keys plus cls, root, shows, decisions, anims)"""
    cl = CLASSES[cls]
    B = SceneBuilder(scene_bytes, mods_bytes, bar_bytes, embs, tex, scene=cl['scene'], quad=cl['quad'],
                     text_from=text_bytes)
    bc = _find(B.root, 'boundless_customisation')
    stock_ids = {e.path: e.element_id for e, _ in B.idf.scenes[0].root.walk()}
    assert {I._val(k.get('name')) for k in bc['children'].items} >= set(STOCK_KIDS)
    root = B.null(cl['root'], (0.0, geo.halo_y, 0.0), hidden=True)
    bc['children'].items.append(root)
    vis, texts, xas, colours, rkeys, batt_keys, _, shows, decisions = _halo(B, geo, root, cls=cls)
    _box_and_ids(B, geo, stock_ids)
    anims = [a for a in ANIM_NODES if a in B.names]
    # the class's switch (setting all_cars = leaf cls, default on): the halo's root shows while it is on; the F2
    # dial's four stock parts while it is off (hud_f1_dial's are in halo_pv_ctl: add_preview_control bound)
    ctl = [('v_halo', cl['root'], leaf('cls'), False, True)]
    if cls == 'f2':
        ctl += [('v_' + nm, nm, leaf('cls'), True, False) for nm in STOCK_KIDS]
    info = dict(cls=cls, root=cl['root'], ctl=ctl, vis=vis, texts=texts, xas=xas, colours=colours, shows=shows,
                decisions=decisions, rpm_keys=rkeys, batt_keys=batt_keys, anims=anims,
                rpm_static={a: None for a in ('zh_rpm_anim', 'zh_rpm_core_anim')}, n_new=len(B.names))
    for e, _ in I.Idf(B.idf.to_bytes()).scenes[0].root.walk():
        nm = I._val(e.obj.get('name'))
        if nm in info['rpm_static']:
            assert info['rpm_static'][nm] is None, ('two', nm)
            info['rpm_static'][nm] = tuple(e.obj['position'].value[:3])
    return B.idf.to_bytes(), info


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
def _clip(tmpl_bytes, node, name_index, chans, strtab=STRTAB):
    """chans: [(interp, type, flags, times, keys)] -> (temp, syst) of an AnimClip that animates `node` (strtab: the
    string table of the node's scene)."""
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
    p.root['string_table'].value = strtab
    return p.to_bytes(), bytes(syst)


def build_clips(tmpl_clip_bytes, strtab_bytes, info, strtab=STRTAB, anims=ANIM_NODES):
    """The anim nulls' clips and the scene's string table with their names appended (anims: the nulls this scene
    has; the F2 halo has no battery, so only the rpm sweeps)."""
    anims = list(anims)
    st = Pkg(strtab_bytes)
    strings = st.root['strings']
    have = [v.value for v in strings.items]
    assert have == sorted(have) and all(n > have[-1] for n in anims) and anims == sorted(anims)
    for nm in anims:
        strings.items.append(Val(strings.items[0].type, nm))
    index = {nm: len(have) + i for i, nm in enumerate(anims)}
    ident = (0.0, 0.0, 0.0, -1.0)
    one = (1.0, 1.0, 1.0)
    clips = {}
    bk = info['batt_keys']
    win = [tuple(k) for k in bk]
    ctr = [(-k[0], -k[1], 0.12) for k in bk]
    for nm, keys in (('zh_batt_win_anim', win), ('zh_batt_ctr_anim', ctr)):
        if nm not in index:
            continue
        clips[nm] = _clip(tmpl_clip_bytes, nm, index[nm], [
            (5, 3, 0x80, [0.0, ANIM_T], keys),
            (2, 1, 0x84, [0.0], [ident]),
            (5, 2, 0x80, [0.0], [one])], strtab)
    for nm in ('zh_rpm_anim', 'zh_rpm_core_anim'):
        pos = info['rpm_static'][nm]
        times = [f * ANIM_T for f, _ in info['rpm_keys']]
        quats = [tuple(quat_z(deg(a))) for _, a in info['rpm_keys']]
        clips[nm] = _clip(tmpl_clip_bytes, nm, index[nm], [
            (5, 3, 0x80, [0.0], [pos]),
            (2, 1, 0x84, times, quats),
            (5, 2, 0x80, [0.0], [one])], strtab)
    assert set(clips) == set(anims), (sorted(clips), anims)
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


def _tags(root, skip='halo_ctl'):
    """{dbentry: the value tags the nodes under root bind it with}, our halo_ctl groups left out."""
    out = {}
    for _n, _k, t, db in _bindings(root, [], skip=skip):
        out.setdefault(db, set()).add(t)
    return out


def check_binding_types(stock_root, kids, scope=None, fallback=None):
    """Fail the build if a halo property's value type differs from the type of the value it is bound to.
    scope (the spectator dials): the [F1HD] whose own stock nodes give a name's tag first, then the whole template
    (the spectator .ui binds the same relative names under two view-model contexts); fallback: the race HUD's tags
    (_race_tags) for the names no spectator node binds. Where both bind a name, the tags must agree."""
    stock = _tags(stock_root)
    near = _tags(_node_at(stock_root, scope)) if scope else {}
    fallback = fallback or {}
    bad, checked, borrowed = [], 0, set()
    for kid in kids:
        for node, prop, t, db in _bindings(kid, []):
            if db.startswith(VM):
                want = {'stri'} if db[len(VM):] in DLL_TEXT_LEAVES else {'bool'}
            else:
                key = re.sub(r'#session\.cars\.car\d+\.', '#session.current_car.', db)
                here = near.get(key) or stock.get(key)
                if here and key in fallback and fallback[key] != here:
                    bad.append(f'{node}.{prop} <- {db}: this template binds it as {sorted(here)}, the race HUD as '
                               f'{sorted(fallback[key])}')
                    continue
                if not here and key in fallback:
                    borrowed.add(key)
                want = here or fallback.get(key) or ({KNOWN_TYPES[key]} if key in KNOWN_TYPES else None)
            if not want:
                bad.append(f'{node}.{prop} <- {db}: type unknown (no stock binding, not in KNOWN_TYPES)')
            elif t not in want:
                bad.append(f'{node}.{prop} <- {db}: {t}, the value is {"/".join(sorted(want))}')
            checked += 1
    if bad:
        raise SystemExit('template binding types:\n  ' + '\n  '.join(bad))
    where = f' ({scope}; tags from the race HUD for {", ".join(sorted(borrowed))})' if scope else ''
    print(f'binding types: {checked} halo bindings match their values{where}')




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


def build_template(ui_bytes, info, parent=TEMPLATE_PARENT, fallback=None):
    """The 2026 halo's group 'halo_ctl' under its dial's [F1HD]: the race HUD's (TEMPLATE_PARENT) or, with a
    spectator parent, the spectator HUD's f1_26_dial (types checked in that dial's scope, fallback: _race_tags)."""
    p = Pkg(ui_bytes)
    target = _node_at(p.root, parent)
    assert not any(N.name(c) == 'halo_ctl' for c in N.children(target)), 'template already has the halo'

    kids = _binding_nodes(info)
    grp = U.node('halo_ctl', 'UIGP', [], kids=kids, behav=U.GROUP_BEHAVIOURS)
    if parent == TEMPLATE_PARENT:
        check_binding_types(p.root, kids)
    else:
        check_binding_types(p.root, kids, parent, fallback)
    N.fix_ids(grp, parent)
    target.items[N.CHILDREN].items.append(grp)
    return p.to_bytes(), len(kids)


def _binding_nodes(info):
    """The template nodes that drive a live halo's elements: bound visible, team colour, texts, anim fractions."""
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
    return kids


def _stock_parts_nodes():
    """The stock dial's four parts, shown while the setting all_cars (leaf cls) is off: in a 2025 or F2 car the
    class's halo shows instead while it is on (or while the leaf is absent: the setting's default)."""
    return [U.node('v_' + nm, 'UIGP', [('visible', _bool_prop(False, leaf('cls'), True))], layout=[nm],
                   behav=U.GROUP_BEHAVIOURS) for nm in STOCK_KIDS]


def add_preview_control(ui_bytes, parent, bound=False):
    """Under a node that drives dial_complete in game (PREVIEW_PARENTS: the hud_f1_dial template, the spectator HUD's
    modern_dial), a group that hides the editor's halo copy and shows the stock dial's four parts. Static values,
    no bindings: in game the F1 25 dial looks as before even if the game also applied the .uipre there.
    bound (hud_f1_dial since the car classes): the four parts show while the setting all_cars is off, the 2025 halo
    (build_class_template) while it is on; the copy stays hidden."""
    p = Pkg(ui_bytes)
    target = _node_at(p.root, parent)
    assert not any(N.name(c) == PREVIEW_CTL for c in N.children(target)), 'already has the preview control'
    kids = [U.hidden('v_' + PREVIEW_ROOT, PREVIEW_ROOT)]
    if bound:
        kids += _stock_parts_nodes()
    else:
        kids += [U.node('v_' + nm, 'UIGP', [('visible', U.prop('bool', True))], layout=[nm], behav=U.GROUP_BEHAVIOURS)
                 for nm in STOCK_KIDS]
    grp = U.node(PREVIEW_CTL, 'UIGP', [], kids=kids, behav=U.GROUP_BEHAVIOURS)
    assert bound or not _bindings(grp, []), 'the preview control binds nothing'
    check_binding_types(p.root, kids)
    N.fix_ids(grp, parent)
    target.items[N.CHILDREN].items.append(grp)
    return p.to_bytes(), len(kids)


# ---------------------------------------------------------------- car classes: template
def _walk_paths(x, trail=(), out=None):
    """[(dotted path, node)] of every UI node under x."""
    out = [] if out is None else out
    if N.is_node(x):
        t = trail + (N.name(x),)
        out.append(('.'.join(t), x))
        for c in N.children(x):
            _walk_paths(c, t, out)
    elif isinstance(x, Arr):
        for c in x.items:
            _walk_paths(c, trail, out)
    elif isinstance(x, Obj):
        for _k, v in x.items:
            _walk_paths(v, trail, out)
    return out


def _type(n):
    return struct.pack('<I', n.items[N.PROPS]['type'].value).decode()


def check_decisions(stock_root, parent, decisions):
    """Fail the build unless each decision node reads its value the way the stock dial does: an MVCD's dbEntry is a
    stock MVCD's dbEntry under the same [F1HD], with every state the halo uses among that MVCD's events; an SVCD's
    value has the tag the same dial's stock nodes bind its dbEntry with (relative names resolve in the dial's own
    view model; one tag only)."""
    nodes = [(path, n) for path, n in _walk_paths(stock_root) if 'halo_ctl' not in path.split('.')]
    stock_tags = {}
    for _n, _k, t, db in _bindings(_node_at(stock_root, parent), [], skip='halo_ctl'):
        stock_tags.setdefault(db, set()).add(t)
    for d in decisions:
        if d['type'] == 'MVCD':
            same = [n for path, n in nodes if path.startswith(parent + '.') and _type(n) == 'MVCD'
                    and n.items[N.PROPS].get('dbEntry') is not None
                    and n.items[N.PROPS]['dbEntry']['value'].value == d['db']]
            assert len(same) == 1, ('stock MVCD on', d['db'], 'under', parent, len(same))
            have = {e['eventName'].value for e in same[0].items[N.EVENTS].items if isinstance(e, Obj)}
            used = {ev for ev, _ in d['events']}
            assert used == have, ('MVCD states', d['db'], sorted(used ^ have))
        else:
            assert d['type'] == 'SVCD'
            tags = stock_tags.get(d['db'])
            assert tags == {d['value'][0]}, ('SVCD', d['name'], d['db'], 'stock tags', tags, 'value', d['value'][0])
    print(f'decision nodes: {len(decisions)} read their values with the stock tags / MVCD states ({parent})')


def _decision_nodes(info, base):
    """The decision nodes (props as the stock ones: MVCD dbEntry; SVCD value + dbEntry, no comparison_op = equal)
    and halo_ctl's commands: trigger registers and queries each node, untrigger unregisters it (the stock DRS
    widget's drs_and_pit_distance.trigger / untrigger pattern). base: halo_ctl's path."""
    nodes, trig, untrig = [], [], []
    for d in info['decisions']:
        evs = [U.event(ev, [U.sig(f'{base}.{tgt}', pin, ev) for tgt, pin in sigs]) for ev, sigs in d['events']]
        props = [('dbEntry', U.prop('stri', d['db']))]
        if d['type'] == 'SVCD':
            props.insert(0, ('value', U.prop(*d['value'])))
        nodes.append(U.node(d['name'], d['type'], props, events=evs))
        path = f'{base}.{d["name"]}'
        trig += [U.sig(path, 'register', 'trigger'), U.sig(path, 'query', 'trigger')]
        untrig.append(U.sig(path, 'unregister', 'untrigger'))
    return nodes, [U.command('trigger', trig), U.command('untrigger', untrig)]


def build_class_template(ui_bytes, info, parent=None, fallback=None):
    """A car class's halo group 'halo_ctl' under its dial's [F1HD] (CLASSES[cls]['parent']): the halo's root shown
    while the setting all_cars is on (leaf cls; default on) and for the F2 dial its stock parts while it is off
    (info['ctl']; hud_f1_dial's are in halo_pv_ctl, add_preview_control bound), the bound parts as in the 2026 halo,
    the parts the decision nodes switch, and the decision nodes. The [F1HD]'s show command triggers halo_ctl (register + query) and hide untriggers
    it, beside the stock DRS widget's group. parent: the spectator HUD's dial of the class instead (types checked in
    that dial's scope, fallback: _race_tags)."""
    cls = info['cls']
    cl = CLASSES[cls]
    scope = parent
    parent = parent or cl['parent']
    base = parent + '.halo_ctl'
    p = Pkg(ui_bytes)
    target = _node_at(p.root, parent)
    assert _type(target) == 'F1HD', (parent, _type(target))
    assert not any(N.name(c) == 'halo_ctl' for c in N.children(target)), 'template already has the class halo'
    kids = [U.node(nm, 'UIGP', [('visible', _bool_prop(default, db, neg))], layout=[el], behav=U.GROUP_BEHAVIOURS)
            for nm, el, db, neg, default in info['ctl']]
    kids += _binding_nodes(info)
    for nm, el, default in info['shows']:
        kids.append(U.node(nm, 'UIGP', [('visible', U.prop('bool', bool(default)))], layout=[el], behav=U.GROUP_BEHAVIOURS))
    dnodes, cmds = _decision_nodes(info, base)
    kids += dnodes
    grp = U.node('halo_ctl', 'UIGP', [], kids=kids, behav=U.GROUP_BEHAVIOURS)
    grp.items[N.COMMANDS].items.extend(cmds)
    if scope:
        check_binding_types(p.root, kids, scope, fallback)
    else:
        check_binding_types(p.root, kids)
    check_decisions(p.root, parent, info['decisions'])
    N.fix_ids(grp, parent)
    target.items[N.CHILDREN].items.append(grp)
    names = {N.name(k) for k in kids}
    assert len(names) == len(kids), 'template node name reused'
    for d in info['decisions']:
        for _ev, sigs in d['events']:
            assert all(tgt in names for tgt, _pin in sigs), d['name']
    for cmd, pin in (('show', 'trigger'), ('hide', 'untrigger')):
        c = [x for x in target.items[N.COMMANDS].items if isinstance(x, Obj) and x['commandName'].value == cmd]
        assert len(c) == 1, (parent, cmd, len(c))
        c[0]['signals'].items.append(U.sig(base, pin, cmd))
    return p.to_bytes(), len(kids)


# ---------------------------------------------------------------- spectator HUD (docs/spectator-ui.md)
# hud_spectator_2.ui has its own three dials ([F1HD], picked by the MVCD dial_decision on dial_type). They drive the
# same dial scenes as the race HUD's dial templates and find their elements by name, as those do, but none of the
# halo's template groups runs there. The scenes' isHidden flag does NOT keep an element hidden in game: on
# 2026-11-10 04:12 the spectator's f2_dial showed every part of the F2 copy hf2 (isHidden at its root and at its
# G-meter group), its G-meter's static "7.4" included. Only a template node's visible property hides a part.
# Each spectator dial runs the race HUD's halo groups of its class (build_spectator), G-meter nodes
# included: v_std / v_gmeter decide which centre shows, and the DLL publishes the meter off while spectating.
SPECTATOR_DIALS = {'2026': 'hud_spectator_2.content.bottom_right.f1_26_dial',
                   '2025': PREVIEW_PARENTS['hud_spectator_2'],
                   'f2': 'hud_spectator_2.content.bottom_right.f2_dial'}
SPECTATOR_RACE = {'2026': TEMPLATE_PARENT, '2025': CLASSES['2025']['parent'], 'f2': CLASSES['f2']['parent']}
SPECTATOR_SAFE = 'halo_safe'
SPECTATOR_ROOTS = {'2026': 'halo', '2025': CLASSES['2025']['root'], 'f2': CLASSES['f2']['root']}


def _race_tags(race_root, cls):
    """The tags the race HUD's stock nodes give each name, for a spectator dial of class cls: the race dial's own
    nodes first (the same view-model type: the dials are the same [F1HD] component), then the whole template."""
    tags = _tags(race_root)
    tags.update(_tags(_node_at(race_root, SPECTATOR_RACE[cls])))
    return tags


def build_spectator(ui_bytes, race_bytes, info, info25, infof2):
    """The halo in the spectator HUD's three dials (docs/spectator-ui.md 3.2), each with the race HUD's groups of its
    class: f1_26_dial the 2026 halo_ctl; modern_dial the bound preview control (the editor copy hidden, the stock
    parts while all_cars is off) and the 2025 halo_ctl; f2_dial the F2 halo_ctl (its stock parts while all_cars is
    off). The class groups' trigger / untrigger hang on the spectator [F1HD]'s own show / hide. race_bytes: the stock
    hud_dynamic_templates.ui, for the tags no spectator node gives."""
    race = Pkg(race_bytes).root
    out, n = ui_bytes, {}
    out, n['pv'] = add_preview_control(out, SPECTATOR_DIALS['2025'], bound=True)
    out, n['2026'] = build_template(out, info, SPECTATOR_DIALS['2026'], _race_tags(race, '2026'))
    out, n['2025'] = build_class_template(out, info25, SPECTATOR_DIALS['2025'], _race_tags(race, '2025'))
    out, n['f2'] = build_class_template(out, infof2, SPECTATOR_DIALS['f2'], _race_tags(race, 'f2'))
    check_stock_kept(ui_bytes, out, 'hud_spectator_2.ui')
    return out, n


def _relative(x, parent):
    """A copy of one of our groups with every path relative to parent (node ids zeroed, signal targets as
    '<P>.rest'), to compare the same group under two dials."""
    y = copy.deepcopy(x)

    def walk(n):
        if isinstance(n, Obj):
            if n.get('to_object_name') is not None:
                to = n['to_object_name'].value
                assert to.startswith(parent + '.'), (parent, to)
                n['to_object_name'].value = '<P>' + to[len(parent):]
                n['to_object'].value = 0
            for _k, v in n.items:
                walk(v)
        elif isinstance(n, Arr):
            for v in n.items:
                walk(v)

    walk(y)
    for _path, nd in _walk_paths(y):
        if nd.items[N.PROPS].get('id') is not None:
            nd.items[N.PROPS]['id'].value = 0
    return y


def check_spectator_same(race_built, spec_built):
    """Fail the build unless each spectator dial carries the same groups as its race dial, node for node and binding
    for binding (paths aside), and its show / hide signal them as the race dial's do."""
    r, s = Pkg(race_built).root, Pkg(spec_built).root
    for cls, sp in SPECTATOR_DIALS.items():
        rp = SPECTATOR_RACE[cls]
        rt, st = _node_at(r, rp), _node_at(s, sp)
        rg = {N.name(c): c for c in N.children(rt) if N.name(c) in OUR_GROUPS}
        sg = {N.name(c): c for c in N.children(st) if N.name(c) in OUR_GROUPS}
        assert sorted(rg) == sorted(sg), (cls, sorted(rg), sorted(sg))
        for nm in rg:
            assert _canon(_relative(rg[nm], rp)) == _canon(_relative(sg[nm], sp)), (cls, nm, 'differs from the race HUD')

        def ours(t, path):
            return sorted((c['commandName'].value, x['to_object_name'].value[len(path):], x['to_pin_name'].value)
                          for c in t.items[N.COMMANDS].items if isinstance(c, Obj) for x in c['signals'].items
                          if x['to_object_name'].value.rsplit('.', 1)[-1] in OUR_GROUPS)
        assert ours(rt, rp) == ours(st, sp), (cls, ours(rt, rp), ours(st, sp))
        print(f'spectator {cls}: {sp.rsplit(".", 1)[-1]} carries {sorted(sg)} as {rp.split(".", 1)[0]} '
              f'({sum(len(_walk_paths(g)) for g in sg.values())} nodes, {len(ours(st, sp))} show/hide signals)')


def add_spectator_safe(ui_bytes, classes=('2026', '2025', 'f2')):
    """An older fallback (not used by the build): under each spectator dial in `classes`, a group with one
    static node (no binding) that hides our halo copy in
    that dial's scene: the 2026 halo 'halo' (dial_om_xm), the 2025 copy h25 (dial_complete), the F2 copy hf2
    (dial_f2_complete). The 2025 and F2 spectator dials then show the game's own dial; the 2026 one shows no dial
    (its stock parts are parked in dial_om_xm)."""
    p = Pkg(ui_bytes)
    n = 0
    for cls in classes:
        parent = SPECTATOR_DIALS[cls]
        target = _node_at(p.root, parent)
        assert _type(target) == 'F1HD', (parent, _type(target))
        assert not any(N.name(c) in (SPECTATOR_SAFE, 'halo_ctl') for c in N.children(target)), parent
        root = SPECTATOR_ROOTS[cls]
        grp = U.node(SPECTATOR_SAFE, 'UIGP', [], kids=[U.hidden('v_' + root, root)], behav=U.GROUP_BEHAVIOURS)
        assert not _bindings(grp, []), 'the spectator safe group binds nothing'
        N.fix_ids(grp, parent)
        target.items[N.CHILDREN].items.append(grp)
        n += 1
    return p.to_bytes(), n


OUR_GROUPS = ('halo_ctl', PREVIEW_CTL, SPECTATOR_SAFE)


def _strip_ours(x, ours=OUR_GROUPS):
    """A copy of a template subtree without our groups and without the signals that target them."""
    y = copy.deepcopy(x)

    def walk(n, trail):
        if N.is_node(n):
            t = trail + [N.name(n)]
            n.items[N.CHILDREN].items = [c for c in n.items[N.CHILDREN].items
                                         if not (N.is_node(c) and N.name(c) in ours)]
            for c in n.items[N.COMMANDS].items:
                if isinstance(c, Obj):
                    c['signals'].items = [s for s in c['signals'].items
                                          if s['to_object_name'].value.rsplit('.', 1)[-1] not in ours]
            for c in N.children(n):
                walk(c, t)
        elif isinstance(n, Arr):
            for c in n.items:
                walk(c, trail)
        elif isinstance(n, Obj):
            for _k, v in n.items:
                walk(v, trail)

    walk(y, [])
    return y


def check_stock_kept(before_bytes, after_bytes, label):
    """Fail the build unless the built template, without our groups (halo_ctl, halo_pv_ctl, halo_safe) and the
    signals that target them, equals the stock one node for node, value for value."""
    a, b = Pkg(before_bytes).root, _strip_ours(Pkg(after_bytes).root)
    assert _canon(a) == _canon(b), f'{label}: a stock node changed'
    print(f'stock kept: {label} ({len(_walk_paths(a))} stock nodes unchanged outside our groups)')


def _canon(x):
    """A comparable form of a template subtree (values with their tags)."""
    if isinstance(x, Val):
        return ('V', x.type, repr(x.value))
    if isinstance(x, Obj):
        return ('O', tuple((k.value, _canon(v)) for k, v in x.items))
    if isinstance(x, Arr):
        return ('A', tuple(_canon(v) for v in x.items))
    return ('?', repr(x))


def check_unchanged(before_bytes, after_bytes, path):
    """Fail the build if the template node at `path` (and everything under it) differs between the two templates."""
    a = _node_at(Pkg(before_bytes).root, path)
    b = _node_at(Pkg(after_bytes).root, path)
    assert _canon(a) == _canon(b), f'{path} changed'
    print(f'unchanged: {path} ({len(_walk_paths(a))} nodes)')
