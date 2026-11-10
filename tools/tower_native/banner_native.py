"""Race Control banner (decision 6): the game's own top-centre toast restyled in place, for every message in it.

The toast is the HUD element message_system (template hud_notifications_dynamic, anchored top centre). Every message
the game queues there (message_data/hud_messages.uimsg; map in docs/timing-tower/ui-build.md) keeps the game's own
queue, timing, texts, icons and animations. Only the look changes, scene by scene. No element is added, moved or
renamed (element ids are hashes of their paths, so every stock id stays):

1. Size: message_system's four parts (the main toast 'centre' and the safety car, red flag and safety rating boxes)
   are scaled by S = 22 / 28.67 about their own top edge: the box is about 24 % lower (decision 6), its top stays.
2. Fills: every box fill shows the banner navy (tower.js P.banner, sprite bn_m) through one new material binding
   that maps the fill meshes' own slots to the bn_m material (the halo's mechanism: own-scene mesh, new binding).
   A fill the toast template animates (its fade clip, played by a UIXA with playChildren) at an offset layer drew
   nothing in game (round 2: SLOW CAR AHEAD showed no fill while the flags box beside it was navy). Each such fill
   gets a twin '<fill>_bn' beside it: the same mesh and binding, no clip, the absolute layer 60 of the flags box
   that works. The stock fill stays (bn_m: navy or nothing). The race winner icon keeps the game's artwork.
3. The stock edge lines, colour stripes and dividers are hidden: isHidden, and static template nodes (visible =
   false) in both toast instances. isHidden alone did not hold in game (round 2: two grey lines over the box); the
   game itself hides toast parts only with template nodes (stock HIDDEN_incident_icon).
4. Texts: the main toast (central_message: title + second line of nearly every message) becomes one line, title in a
   bold style, the second line in a regular style after a phrase gap (no light weight exists among the game's
   styles), at the F1 TV baseline. The RACE CONTROL label box: the same bold style, its fill stretched to the
   bar's height, and the label white: its colour is set by its clip (label_clip), and the stock dark navy was made for
   the game's white box.
Functional colours stay the game's: the pit-lane speed box (its fill turns red when speeding), the SC / red-flag
countdown boxes, the safety-rating colour line, flag icons, the FIA badge.

Coordinates here are scene units (y up). Stock values this file relies on are asserted, so a game update that moves
them stops the build instead of building a wrong banner.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tower_native as T  # noqa: E402  (paths, idf helpers)

I, H, Val, N, U = T.I, T.H, T.Val, T.N, T.U
Arr, Pkg = T.Arr, T.Pkg

OSD = 'eaid://ui_package/art/osd/'
MS = OSD + 'components/message_system/message_system.idf'
CM = OSD + 'units/message_system/central_message.idf'
FLAGS = OSD + 'units/message_system/flags.idf'
FIA = OSD + 'components/message_system/ms_fia_logo.idf'
RCI = OSD + 'units/message_system/race_control_icon.idf'
RWI = OSD + 'units/message_system/race_winner_icon.idf'
PIT = OSD + 'units/message_system/pit_lane_icon.idf'
IO = OSD + 'components/illegal_overtake/illegal_overtake.idf'
CMW = OSD + 'components/message_system/central_message_winner.idf'
SC = OSD + 'components/message_system/ms_safety_car.idf'
RF = OSD + 'components/message_system/ms_red_flag.idf'
SR = OSD + 'components/message_system/ms_safety_rating.idf'

EDGES = ['edge_border', 'edge_base']
# scene: ({fill element: its mesh's material slot}, [decorations to hide])
RESTYLE = {
    CM: ({'pill': 'central_message_bg'}, EDGES + ['ms_colour']),
    FLAGS: ({'bg': 'central_message_bg_start'}, EDGES + ['ms_colour', 'divider']),
    FIA: ({'bg': 'central_message_bg_start'}, EDGES + ['ms_colour', 'divider']),
    RCI: ({'icon': 'race_control_icon'}, EDGES + ['ms_colour', 'bg_frame']),
    RWI: ({}, EDGES + ['ms_colour', 'bg_frame']),                   # its fill is the game's winner artwork
    PIT: ({}, EDGES + ['ms_colour', 'bg_frame']),                    # black_bg kept: it turns red when speeding
    IO: ({'pill': 'illegal_overtake_bg'}, EDGES + ['ms_colour', 'bg_frame']),
    CMW: ({'pill_bg': 'central_message_bg'}, EDGES + ['ms_colour', 'bg_frame']),
    SC: ({'content_bg': 'bg_1'}, EDGES + ['sc_divider', 'bg_frame', 'divider_1']),   # timer box, SC icon kept
    RF: ({'content_bg': 'bg_1'}, EDGES + ['sc_divider', 'bg_frame', 'divider_1']),
    SR: ({'content_bg': 'bg_1'}, EDGES + ['bg_frame', 'divider_1']),                 # sr_colour (rating) kept
}
SCENES = [MS] + list(RESTYLE)
# fills drawn through a played clip at an offset layer: each gets a clip-free twin at an absolute layer (point 2)
TWIN = {CM: 'pill', FIA: 'bg', RCI: 'icon', IO: 'pill', CMW: 'pill_bg'}
TWIN_LAYER = 60
# the template group that shows each restyled scene in the toast, under each toast instance (point 3)
TOASTS = ('hud_notifications_dynamic', 'hud_notifications_dynamic_p2')
GROUP = {
    CM: 'notification_0.hud_message.right.central_message',
    CMW: 'notification_0.hud_message.right.central_message_winner',
    FLAGS: 'notification_0.hud_message.left.flags',
    IO: 'notification_0.hud_message.left.illegal_overtake_icon',
    PIT: 'notification_0.hud_message.left.pit_speed_icon',
    RWI: 'notification_0.hud_message.left.race_winner_icon',
    RCI: 'notification_0.hud_message.left.race_control_icon',
    FIA: 'notification_0.hud_message.left.fia_icon',
    SC: 'safety_car_notifications.hud_message.content',
    RF: 'red_flag_notifications.hud_message.content',
    SR: 'safety_rating_notifications.hud_message.content',
}
HIDE_NODE = 'tt_bn_hide_'
SLOTS = sorted({s for fills, _ in RESTYLE.values() for s in fills.values()})
# The RACE CONTROL label's colour comes from its own clip (a DiffuseColour channel), not from its text style: the
# stock clip holds a dark navy (12, 32, 60) made for the game's white label box. On the banner navy that label was
# unreadable (seen in game 2026-11-09). The restyled clip holds the game's title white instead (central_message's
# text_line_1 clip: 255, 255, 255); its Alpha fade channel is unchanged.
RC_TEXT_CLIP = RCI + '/text?context=animation'
RC_STOCK_RGB = (12, 32, 60)
RC_LABEL_RGB = (1.0, 1.0, 1.0)

STOCK_H = 0.86                 # the stock box height, scene units (fill meshes: z extents +-0.43)
BANNER_HUD = 22.0              # decision 6: about 24 % below the stock box (28.67 HUD)
S = BANNER_HUD * T.KT / STOCK_H
TITLE_STYLE, LINE2_STYLE = 'OSD_34_bold', '34_regular'
# resting y of the slide-in nulls (their clips end there: anim_null / icon_null / timer_null 0.5 -> 0;
# anim_movement of the SC, red flag and safety rating boxes rests at its authored -1.5)
REST = {'anim_null': 0.0, 'icon_null': 0.0, 'timer_null': 0.0}


def mesh_resource(scene, mesh):
    return f'{scene}/{mesh}?context=render&lod=0&mesh'


def fill_meshes():
    """[(scene, element, mesh resource, slot)] for build_tower.py to read and check"""
    return [(sc, el, mesh_resource(sc, el), slot) for sc, (fills, _) in RESTYLE.items() for el, slot in fills.items()]


class _Scene:
    def __init__(self, path, data):
        self.path = path
        self.idf = I.Idf(data)
        assert self.idf.scenes[0].name == I.component_id(path), path
        self.entry = self.idf.scenes[0].entry
        self.root = self.entry['scene']
        self.stock_ids = {e.path: e.element_id for e, _ in self.idf.scenes[0].root.walk()}
        self.names = [I._val(e.obj.get('name')) for e, _ in self.idf.scenes[0].root.walk()]
        self.new = []
        self.parent = {}

        def walk(o):
            for c in (o['children'].items if o.get('children') is not None else []):
                self.parent[id(c)] = o
                walk(c)
        walk(self.root)

    def one(self, name):
        n = self.names.count(name)
        assert n == 1, f'{self.path}: {n} elements named {name}'
        return H._find(self.root, name)

    def y(self, name, rest=True):
        o = self.one(name)
        v = o['position'].value[1]
        return REST.get(name, v) if rest else v

    def chain_y(self, *names):
        """sum of the resting y of a chain of nested elements (asserted to be parent -> child)"""
        for a, b in zip(names, names[1:]):
            assert self.parent[id(self.one(b))] is self.one(a), f'{self.path}: {b} is not a child of {a}'
        return sum(self.y(n) for n in names)

    def half_h(self, name):
        """half the height of a quad (its z extent: the quads are turned about x), times its z scale"""
        o = self.one(name)
        return I.get_param(o, 'maxExtents')[2] * o['scale'].value[2]

    def set(self, name, **kw):
        o = self.one(name)
        for k, v in kw.items():
            if k == 'y':
                p = list(o['position'].value)
                p[1] = float(v)
                o.set('position', Val(o['position'].type, p))
            elif k == 'x':
                p = list(o['position'].value)
                p[0] = float(v)
                o.set('position', Val(o['position'].type, p))
            elif k == 'scale':
                o.set('scale', Val(o['scale'].type, [float(v[0]), float(v[1]), float(v[2]), 0.0]))
            elif k == 'fp32':
                for pk, pv in v.items():
                    H._param(o, pk, float(pv), 'fp32')
            else:
                H._param(o, k, v, 'bool' if isinstance(v, bool) else 'stri')
        return o

    def twin(self, name, layer):
        """a copy '<name>_bn' of a childless quad, right after it: same mesh, binding and place; no clip, an absolute
        layer, no hidden flag"""
        o = self.one(name)
        kids = o.get('children')
        assert not (kids is not None and kids.items), f'{self.path}: {name} has children'
        nm = name + '_bn'
        assert nm not in self.names, f'{self.path}: {nm} exists'
        c = I.clone_node(o)
        c.set('name', Val('stri', nm))
        pa = c['params']
        pa.items = [it for it in pa.items if I._val(it.get('name')) not in ('isHidden', 'eAnimationGroup.AnimGroup')]
        H._param(c, 'guid', H._guid(self.path.split('/')[-1] + '/' + nm))
        H._param(c, 'eLayer.layer', int(layer), 'si32')
        H._param(c, 'eLayer.layerIsOffset', False, 'bool')
        if c.get('anims') is not None:
            c.set('anims', Arr([], c['anims'].tag))
        sib = self.parent[id(o)]['children'].items
        sib.insert(next(i for i, x in enumerate(sib) if x is o) + 1, c)
        self.parent[id(c)] = self.parent[id(o)]
        self.names.append(nm)
        self.new.append(nm)
        return c

    def done(self):
        T._ids_and_check(self.idf, self.entry, self.stock_ids, self.new)
        return self.idf.to_bytes()


def _cap(style):
    return T.CAP_EM * T.style_n(style) / 100.0


def label_clip(frags):
    """The RACE CONTROL label's clip (RC_TEXT_CLIP, 2 fragments: the packet tree, then the key data) with its
    DiffuseColour keys set to RC_LABEL_RGB. The stock layout is asserted: one DiffuseColour channel, two keys (t = 0
    and the clip's end), and per key and component 5 floats (value, in value, in time, out value, out time) holding
    the stock colour RC_STOCK_RGB, alpha 1. Only the R, G and B values change; every time and the Alpha channel stay.
    -> [fragments]"""
    import struct
    assert len(frags) == 2, len(frags)
    p = Pkg(frags[0])
    chans = [(pk, ch) for pk in p.root['packets'].items for ch in pk['channels'].items]
    assert sorted(ch['name'].value for _, ch in chans) == ['Alpha', 'DiffuseColour'], 'label clip channels'
    pk, ch = next((pk, ch) for pk, ch in chans if ch['name'].value == 'DiffuseColour')
    kp, tp, end = ch['keyptr'].value, ch['timesptr'].value, pk['maxtime'].value
    b = bytearray(frags[1])
    assert kp - tp == 8 and kp % 4 == 0 and len(b) >= kp + 160, (tp, kp, len(b))
    times = struct.unpack_from('<2f', b, tp)
    assert abs(times[0]) < 1e-6 and abs(times[1] - end) < 1e-5, times
    want = [c / 255.0 for c in RC_STOCK_RGB] + [1.0]
    for key in range(2):
        for comp in range(4):
            at = kp + 4 * 5 * (key * 4 + comp)
            g = struct.unpack_from('<5f', b, at)
            for j in (0, 1, 3):
                assert abs(g[j] - want[comp]) < 1e-3, (key, comp, g)
            if comp < 3:
                for j in (0, 1, 3):
                    struct.pack_into('<f', b, at + 4 * j, RC_LABEL_RGB[comp])
    assert bytes(b[:kp]) == frags[1][:kp] and len(b) == len(frags[1])
    return [frags[0], bytes(b)]


def build_banner(stock, meshes, emb_path, banner):
    """stock: {scene eaid: bytes}; meshes: {mesh resource: [fragments]}; emb_path: the binding that maps SLOTS to
    the bn_m material; banner: tower.js G.banner (sprites.json). -> ({scene eaid: bytes}, info for the docs/sim)"""
    base_frac = banner['base'] / banner['hPx']          # F1 TV baseline, from the bar's top
    gap = banner['gapPhrase'] / banner['hPx'] * STOCK_H  # F1 TV gap between title and message (pre-scale)
    out, info = {}, {'S': S, 'banner_hud': BANNER_HUD, 'stock_h': STOCK_H, 'kt': T.KT, 'cap_em': T.CAP_EM,
                     'title_style': TITLE_STYLE, 'line2_style': LINE2_STYLE, 'gap': gap, 'base_frac': base_frac,
                     'scenes': {}}
    sc = {p: _Scene(p, stock[p]) for p in SCENES}

    # -- the main toast's top (message_system coordinates, at rest) and the boxes' heights
    ms, cm = sc[MS], sc[CM]
    cm_top = (ms.chain_y('centre', 'stacker', 'right_null', 'stacker_right', 'central_message')
              + cm.chain_y('anim_null', 'stacker', 'scaler', 'bg_holder', 'pill') + cm.half_h('pill'))
    left_x = ms.chain_y('centre', 'stacker', 'left_null', 'stacker_left')
    for el, path in (('flags', FLAGS), ('fia', FIA)):
        o = sc[path]
        top = left_x + ms.y(el) + o.chain_y(o.names[1], 'bg_holder', 'bg') + o.half_h('bg')
        assert abs(top - cm_top) < 1e-4, (el, top, cm_top)
    for path, fill in ((CM, 'pill'), (FLAGS, 'bg'), (FIA, 'bg')):
        assert abs(2 * sc[path].half_h(fill) - STOCK_H) < 1e-4, (path, fill)

    # 1. size: each part scaled by S about its own top edge
    parts = {'centre': cm_top}
    for part, path in (('safety_car', SC), ('red_flag', RF), ('safety_rating', SR)):
        o = sc[path]
        assert I.get_param(ms.one(part), 'fileRef') == path, part
        assert o.y('anim_movement') == -1.5, (path, 'anim_movement rests at its authored -1.5')
        parts[part] = (ms.y(part) + o.chain_y('anim_movement', 'anim_fade', 'centre_width', 'scaler_bg_width',
                                              'stacker_bg_height', 'scaler_bg_height', 'content_bg')
                       + o.half_h('content_bg'))
    assert [I._val(c.get('name')) for c in ms.root['children'].items] == list(parts), 'message_system parts'
    for part, top in parts.items():
        y0 = ms.y(part)
        ms.set(part, y=top + (y0 - top) * S, scale=(S, S, 1.0))
    info['parts'] = {k: {'top': v, 'top_hud': (0.54 - v) / T.KT} for k, v in parts.items()}

    # 2. + 3. fills and decorations
    for path, (fills, hide) in RESTYLE.items():
        o = sc[path]
        rec = {'fills': {}, 'hidden': hide}
        for el, slot in fills.items():
            e = o.one(el)
            g = e['geoms'].items
            assert len(g) == 1 and g[0]['resourceid'].value == f'{path}/{el}?context=render', (path, el)
            frags = meshes[mesh_resource(path, el)]
            assert any(slot.encode() + b'\0' in f for f in frags), f'{path}/{el}: mesh slot is not {slot}'
            g[0].set('materialid', Val(g[0]['materialid'].type, emb_path))
            lo, hi = I.get_param(e, 'minExtents'), I.get_param(e, 'maxExtents')
            rec['fills'][el] = {'slot': slot, 'w': hi[0] - lo[0], 'h': hi[2] - lo[2]}
        for el in hide:
            e = o.one(el)
            kids = e.get('children')
            assert not (kids is not None and kids.items), f'{path}: {el} has children'
            H._param(e, 'isHidden', True, 'bool')
        info['scenes'][path.split('/')[-1]] = rec

    # 4a. central_message: one line, title bold + second line regular, at the F1 TV baseline
    cap1, cap2 = _cap(TITLE_STYLE), _cap(LINE2_STYLE)
    assert I.get_param(cm.one('stacker_content'), 'stackerType') == 't'
    assert I.get_param(cm.one('stacker_name_platform'), 'stackerType') == 'l'
    pill_top = cm.chain_y('bg_holder', 'pill') + cm.half_h('pill')          # scaler coordinates
    base = pill_top - base_frac * STOCK_H                                    # scaler coordinates
    sc_y = cm.y('centre') + cm.y('stacker_content')
    x0 = cm.one('text_line_1')['position'].value[0]                          # the stock text start (-2.49)
    assert abs(x0 - cm.one('stacker_name_platform')['position'].value[0]) < 1e-6
    cm.set('stacker_content', stackerType='l', fp32={'gap': gap}, x=x0)     # an 'l' stacker puts its first child
    cm.set('text_line_1', style=TITLE_STYLE, x=0.0, y=base - sc_y)          # at its own origin
    cm.set('stacker_name_platform', y=base - sc_y)
    cm.set('text_line_2', style=LINE2_STYLE)
    cm.set('platform_identity', y=cap2 / 2)                                  # the platform icon on the cap centre
    info['central_message'] = {'base_scaler': base, 'pill_top_scaler': pill_top, 'cap1': cap1, 'cap2': cap2,
                               'margins': [I.get_param(cm.one('scaler'), 'leftMargin'),
                                           I.get_param(cm.one('scaler'), 'rightMargin')]}

    # 4b. the RACE CONTROL label box: fill to the bar's height and top, label in the title style
    rc = sc[RCI]
    rc_scaler = left_x + ms.y('race_control_icon') + rc.chain_y('icon_null', 'centre', 'scaler')   # in message_system
    want_top = cm_top - rc_scaler                                                                   # scaler coords
    icon = rc.one('icon')
    hh = rc.half_h('icon')
    k = (STOCK_H / 2) / hh
    rc.set('icon', y=want_top - rc.y('bg_holder') - STOCK_H / 2,
           scale=(icon['scale'].value[0], icon['scale'].value[1], icon['scale'].value[2] * k))
    rc.set('text', style=TITLE_STYLE, fp32={'boxWidth': 3.2}, y=want_top - base_frac * STOCK_H)
    info['race_control'] = {'fill_z_scale': k, 'cap': cap1, 'box': 3.2,
                            'margins': [I.get_param(rc.one('scaler'), 'leftMargin'),
                                        I.get_param(rc.one('scaler'), 'rightMargin')]}
    fia_bg, fia_img = I.get_param(sc[FIA].one('bg'), 'maxExtents'), I.get_param(sc[FIA].one('image'), 'maxExtents')
    info['fia'] = {'w': 2 * fia_bg[0], 'logo': [2 * fia_img[0], 2 * fia_img[2]]}

    # 5. (round 2) clip-free twins of the fills the toast animates at an offset layer (after 4b: the RACE CONTROL
    # fill is copied stretched). The rule is checked both ways: a fill is offset exactly when it is in TWIN.
    for path, (fills, _) in RESTYLE.items():
        for el in fills:
            offset = bool(I.get_param(sc[path].one(el), 'eLayer.layerIsOffset'))
            assert offset == (TWIN.get(path) == el), f'{path}: {el} layerIsOffset {offset}, twin {TWIN.get(path)}'
    for path, el in TWIN.items():
        assert sc[path].one(el)['anims'].items, f'{path}: {el} has no clip'
        sc[path].twin(el, TWIN_LAYER)
        info['scenes'][path.split('/')[-1]]['twin'] = el + '_bn'

    for p, o in sc.items():
        out[p] = o.done()
    return out, info


def _group_scene(ms, p_root, path):
    """the scene a toast template group shows: the fileRef of the message_system xref its layout (or its nearest
    ancestor's layout) names"""
    parts = path.split('.')
    for k in range(len(parts), 0, -1):
        lay = H._node_at(p_root, '.'.join(parts[:k])).items[N.LAYOUT]
        if lay.items and lay.items[0].items:
            return I.get_param(ms.one(lay.items[0].items[-1]['debugName'].value), 'fileRef')
    return None


def toast_hides(ui_bytes, ms_bytes):
    """hud_dynamic_templates.ui + static nodes (visible = false) hiding each restyled scene's decorations, in the
    template group that shows the scene, in both toast instances. Checks: the group shows that scene, and no node in
    it already shows or hides one of those parts. -> (bytes, node count)"""
    p = Pkg(ui_bytes)
    ms = _Scene(MS, ms_bytes)
    n = 0
    for scene, (_, hide) in RESTYLE.items():
        for toast in TOASTS:
            gp = f'{toast}.osd_visibility_option.{toast}.{GROUP[scene]}'
            g = H._node_at(p.root, gp)
            assert g is not None, gp
            got = _group_scene(ms, p.root, gp)
            assert got == scene, (gp, got, scene)
            fights = []

            def walk(x):
                for lp in x.items[N.LAYOUT].items:
                    last = lp.items[-1]['debugName'].value if lp.items else ''
                    if last in hide and x.items[N.PROPS].get('visible') is not None:
                        fights.append((N.name(x), last))
                for c in N.children(x):
                    walk(c)
            walk(g)
            assert not fights, (gp, 'nodes already show or hide', fights)
            have = {N.name(c) for c in N.children(g)}
            for el in hide:
                nm = HIDE_NODE + el
                assert nm not in have, (gp, nm)
                k = U.hidden(nm, el)
                N.fix_ids(k, gp)
                g.items[N.CHILDREN].items.append(k)
                n += 1
    return p.to_bytes(), n
