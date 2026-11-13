"""Broadcast cards (0.2.2): the game's pit lane timer, pit window and lap time elements in the timing tower's look.

Each card is built into the stock element's own scene. Every stock template node, binding, state matrix and clip
stays: stock texts and colour quads are moved and restyled (static scene values only), stock panel quads show the
cards' flat fills through new material bindings on their own meshes (the Race Control banner's route), and stock art
the cards do not use is scaled to nothing (as the stock scenes' own closed states). New elements: the header parts
(position, team logo, surname, tyre letter), the team line and the sector progress steps.

Coordinates in this file: scene units (1 = screen width / 19.2), x right, y DOWN from the parent's origin.
P = the tower's row pitch in scene units.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tower_native'))
import tower_native as T  # noqa: E402
import banner_native as BN  # noqa: E402
import tower_resources as TR  # noqa: E402

I, H, Val, N, U, Arr, Pkg = T.I, T.H, T.Val, T.N, T.U, T.Arr, T.Pkg

OSD = 'eaid://ui_package/art/osd/components/'
PIT = OSD + 'pit_stop/pit_lane_time.idf'
WIN = OSD + 'pit_stop/pit_lane_open.idf'
SEC = OSD + 'timing/timing_sectors.idf'
POS = [OSD + f'timing/timing_position{s}.idf' for s in ('', '_practice', '_quali', '_time_trial')]
PILLS = OSD + 'timing/timing_pill_stack.idf'
BEST, PREV = OSD + 'timing/timing_pill_best.idf', OSD + 'timing/timing_pill_previous.idf'
DELTA = OSD + 'timing/timing_pill_delta.idf'
STACKS = [OSD + f'timing/timing_pill_stack_{s}.idf' for s in ('default', 'practice', 'qualifying', 'time_trial')]
# the pit approach banner's limit block (BN.PIT). Its scene is built from the Race Control banner's version
# (tower_scene.erp), not from stock: build_cards.py passes those bytes
BANNER = BN.PIT
BANNER_GROUP = BN.GROUP[BN.PIT]          # the block's template group under each toast
BANNER_LABEL = 'PIT LIMIT'               # static, English (as the tower's TIME TRIAL label)
# the state field, scene units before the banner's own scale: its left edge and width in the unit's frame
# (the unit's origin is the limit block's centre; the block is about 1.6 wide, the message about 6.3 in English:
# the field ends past the message's fill, so the fill never shows beside it)
# in game the 9.4 field ended 12 px before the message's fill with 'CURRENT SPEED - 79KPH Distance - 12m'
# (9.52 would have met it). The fill grows with the text, so the field covers the longest English form (a
# three-digit speed and distance, about 0.5 more) and is the panel's right end for every shorter one
BANNER_H, BANNER_UP = 0.86, 0.03         # the message fill's height and how far above the block's centre it sits
CM = BN.CM                                # the message scene: text, and the fill the game stretches to it
STATE_TWINS = (('green', 'cd_st_g', 'pgreen', 61), ('red', 'cd_st_r', 'pred', 62))
# the state colour under the limit: the stock clip's green (0, 0.776, 0) gives white text a contrast of 2.3 : 1;
# this darker green gives 5.5 : 1 (the red, kept as the game's, 5.8 : 1). Same keys, same times, same flag
BANNER_STOCK_GREEN, BANNER_GREEN = (0.0, 0.7765, 0.0), (11 / 255, 122 / 255, 50 / 255)
# the pit window (WIN) is not built: its texts take their colours from clips made for the stock light panel
# (title black, OPEN near black, the lap range red), so the cards' dark fills would need those clips rewritten
SCENES = [PIT, SEC] + POS + [PILLS, BEST, PREV, DELTA] + STACKS
# where the stock game keeps each scene (probe.txt): the overlays follow it
ERPS4 = [PIT]
ERPS2 = [POS[2], POS[3]]

VM = '#view_model_data.hud_cd_'
ZERO = 0.0001                 # a hidden part's scale, as the stock scenes' own closed states (0.0001 ... 0.001)
NSTEP = 16                    # sector progress steps per sector (leaves s1p00 ... s3p15)
BAR_OVER = 8.0                # a colour quad's width in bar widths (its gradient's last eighth shows)
ROW_H, ROW_BASE, ROW_PAD = 0.36, 0.25, 0.07   # best / previous rows: pitch, baseline, padding under the last
LAP_GREEN, LAP_PURPLE = '#58d654ff', '#a64bf4ff'   # the tower's lap time flash colours (tower_native.FLASH)
TYRES = 'SMHIW'
# flat fills, sRGB (r, g, b, a): the 2026 pit card's sampled colours [ref]
FILLS = {'head': (0x1C, 0x1E, 0x25, 255), 'cell': (0x0C, 0x0E, 0x16, 255), 'body': (0x15, 0x16, 0x1D, 255),
         'foot': (0x10, 0x11, 0x17, 255), 'white': (255, 255, 255, 255), 'track': (0x3A, 0x3C, 0x4A, 255),
         'grey': (0x9E, 0xA2, 0xB3, 255), 'red': (0xC4, 0x16, 0x1C, 255),
         # the pit speed states on the message's panel: the unit clip's red (0.792, 0.098, 0.086) and the darker
         # green its green keys were given (white text on it: 5.5 : 1)
         'pgreen': (11, 122, 50, 255), 'pred': (202, 25, 22, 255)}
TEX = 'eaid://ui_package/art/osd/textures/cards/cd_{}.tif'
MAT = 'eaid://ui_package/art/osd/materials/cards/cd_{}.material'
EMB = 'eaid://ui_package/art/osd/components/cards/cd_{}.emb?context=default'
LABEL_GREY = '#dadce6ff'
TEXT_WHITE = '#f9faffff'   # the new texts are copies without their source's colour clip: a static colour
QUAD_ROT = [-0.70710678, -0.0, 0.0, -0.70710678]
# from the first in-game capture of the pit card [game]: a two-digit position is 0.81 p wide (the digits'
# pitch is 0.48 p), so the cell is CELL wide; a surname is about 5 % wider than the tower's model; the non-OSD
# styles ('19_regular', '17_regular') draw about 20 % larger than the OSD ones of the same number; and a text
# with wrapping 'clampwidth' that is wider than its box breaks at a space (STOP / TIME on two lines). So every
# text that can hold more than one word has wrapping 'none' and a box with room.
CELL = 1.25                   # position cell width, p
NAME_X = CELL + 0.92          # surname start, p (logo 0.62 p with 0.15 p on each side)
# the STOP TIME row's colours (the texts' own DiffuseColour clips, rewritten): label grey, value light grey
CLIP_RGB = {'text_pit_time': (0xDA / 255, 0xDC / 255, 0xE6 / 255)}
STOP_LABEL = 'STOP TIME'      # the card's own label (static, English): the game's string has a line break
LABEL_GREY2 = '#9ea2b3ff'


def leaf(k):
    return VM + k


def mat_of(fill):
    """material path of a fill name, or of a tower sprite ('tt:ty_S')"""
    return TR.MAT.format(fill[3:]) if fill.startswith('tt:') else MAT.format(fill)


class CS(BN._Scene):
    """A stock scene edited in place."""

    def __init__(self, path, data, meshes, slots, embs):
        super().__init__(path, data)
        self.stock = data
        self.key = path.split('/')[-1][:-4]
        self.meshes, self.slots, self.embs = meshes, slots, embs
        self.texts = [e.obj for e, _ in self.idf.scenes[0].root.walk() if e.type == 'eText']
        # the model of a new null: a stock eNull, a drawing-free one first (null() drops clips and geometry)
        self.nulls = sorted((e.obj for e, _ in self.idf.scenes[0].root.walk() if e.type == 'eNull'),
                            key=lambda o: (bool(o['geoms'].items), bool(o['anims'].items)))
        self.hidden_default = []     # new elements hidden until a leaf shows them
        self.drawn = {}              # name -> info for the simulator / checks

    # -- helpers
    def kids(self, name):
        return self.one(name)['children'].items

    def slot(self, el):
        """the material slot of a stock quad's mesh: the scene binding's slot name found in the mesh resource"""
        g = self.one(el)['geoms'].items
        assert len(g) == 1 and g[0]['resourceid'].value == f'{self.path}/{el}?context=render', (self.path, el)
        blob = b''.join(self.meshes[BN.mesh_resource(self.path, el)])
        blob = blob.replace(f'{self.path}/{el}?context=render'.encode(), b'')
        hit = [s for s in self.slots if s.encode() + b'\0' in blob]
        assert len(hit) == 1, (self.path, el, hit, self.slots)
        return hit[0]

    def emb(self, el, fill):
        """a material binding that maps the mesh slot of stock quad `el` to a fill's material"""
        slot = self.slot(el)
        path = EMB.format(f'{self.key}_{slot}_{fill.replace(":", "_")}')
        self.embs[path] = [(slot, mat_of(fill))]
        return path

    def ext(self, o):
        lo, hi = I.get_param(o, 'minExtents'), I.get_param(o, 'maxExtents')
        assert abs(lo[1]) < 1e-3 and abs(hi[1]) < 1e-3 and hi[0] > lo[0] and hi[2] > lo[2], (self.path, lo, hi)
        return lo, hi

    def _rect(self, o, x0, y0, x1, y1):
        """lay quad o (the stock quads' quarter turn: mesh x -> x, mesh z -> -y) over the rect"""
        lo, hi = self.ext(o)
        sx, sz = (x1 - x0) / (hi[0] - lo[0]), (y1 - y0) / (hi[2] - lo[2])
        o.set('scale', Val(o['scale'].type, [sx, 1.0, sz, 0.0]))
        p = list(o['position'].value)
        p[0], p[1] = x0 - sx * lo[0], -y0 + sz * lo[2]
        o.set('position', Val(o['position'].type, p))
        o.set('rotation', Val('quat', list(QUAD_ROT)))

    def rect(self, el, x0, y0, x1, y1, fill=None, layer=None):
        """a stock quad moved over a rect; fill: its material rebound to a card fill"""
        o = self.one(el)
        self._rect(o, x0, y0, x1, y1)
        if fill:
            o['geoms'].items[0].set('materialid', Val(o['geoms'].items[0]['materialid'].type, self.emb(el, fill)))
        if layer is not None:
            H._param(o, 'eLayer.layer', int(layer), 'si32')
        self.drawn[el] = {'kind': 'quad', 'fill': fill or 'stock'}
        return o

    def _new(self, model, name, parent):
        assert name not in self.names, (self.path, name)
        o = I.clone_node(model)
        o.set('name', Val('stri', name))
        H._param(o, 'guid', H._guid(self.key + '/' + name))
        for key in ('children', 'anims'):
            if o.get(key) is not None:
                o.set(key, Arr([], o[key].tag))
        pa = o['params']
        pa.items = [it for it in pa.items if I._val(it.get('name')) not in ('isHidden', 'eAnimationGroup.AnimGroup')]
        par = self.one(parent) if isinstance(parent, str) else parent
        par['children'].items.append(o)
        self.parent[id(o)] = par
        self.names.append(name)
        self.new.append(name)
        return o

    def quad(self, name, parent, model, fill, x0, y0, x1, y1, layer, hidden=False):
        """a new quad: a copy of stock quad `model` (its mesh) showing a fill"""
        o = self._new(self.one(model), name, parent)
        o['geoms'].items[0].set('materialid', Val(o['geoms'].items[0]['materialid'].type, self.emb(model, fill)))
        self._rect(o, x0, y0, x1, y1)
        H._param(o, 'eLayer.layer', int(layer), 'si32')
        H._param(o, 'eLayer.layerIsOffset', False, 'bool')
        if hidden:
            I.set_param(o, 'isHidden', True, 'bool')
            self.hidden_default.append(name)
        self.drawn[name] = {'kind': 'quad', 'fill': fill}
        return o

    def null(self, name, parent, x=0.0, y=0.0, scale=1.0):
        o = self._new(self.nulls[0], name, parent)
        o.set('position', H._vec((x, -y, 0.0)))
        o.set('scale', H._vec((scale, scale, 1.0)))
        o.set('rotation', Val('quat', [-0.0, -0.0, 0.0, -1.0]))
        if o.get('geoms') is not None:
            o.set('geoms', Arr([], o['geoms'].tag))
        return o

    def style(self, o, x, y, style=None, halign=None, box=None, wrapping='clampwidth', textcase=None, layer=None):
        """static text values: the anchor (x, baseline y), style, alignment, box"""
        p = list(o['position'].value)
        p[0], p[1] = x, -y
        o.set('position', Val(o['position'].type, p))
        o.set('rotation', Val('quat', [-0.0, -0.0, 0.0, -1.0]))
        for k, v in (('style', style), ('halign', halign), ('wrapping', wrapping), ('textcase', textcase)):
            if v is not None:
                H._param(o, k, v)
        if box is not None:
            H._param(o, 'boxWidth', float(box), 'fp32')
        if layer is not None:
            H._param(o, 'eLayer.layer', int(layer), 'si32')
        return o

    def text(self, name, parent, x, y, style, halign, box, textcase='upper', layer=None, hidden=False):
        """a new text: a copy of one of the scene's own texts"""
        o = self._new(self.texts[0], name, parent)
        self.style(o, x, y, style, halign, box, 'clampwidth', textcase, layer)
        if hidden:
            I.set_param(o, 'isHidden', True, 'bool')
            self.hidden_default.append(name)
        return o

    def zero(self, el):
        """a stock part the card does not use: scaled to nothing. A part with a clip or children of its own goes
        into a new null with that scale instead (its own values untouched)."""
        o = self.one(el)
        plain = bool(o['geoms'].items) and not o['anims'].items and not o['children'].items
        if plain:
            s = o['scale'].value
            o.set('scale', Val(o['scale'].type, [s[0] * ZERO, s[1], s[2] * ZERO, 0.0]))
            return
        par = self.parent[id(o)]
        w = self.null('cd_z_' + el, par, scale=ZERO)
        sib = par['children'].items
        sib.remove(w)
        at = next(i for i, x in enumerate(sib) if x is o)
        sib[at] = w
        w['children'].items.append(o)
        self.parent[id(o)] = w

    def logo(self, name, parent, cx, cy, side, model, geom):
        """the stock team logo unit (a copy of the stock pill row's reference), its square `side` wide, centred"""
        (lcx, lcy), lside = geom
        s = side / lside
        o = self._new(model, name, parent)
        o.set('position', H._vec((cx - s * lcx, -cy - s * lcy, 0.0)))
        o.set('scale', H._vec((s, s, 1.0)))
        return o

    def point(self, el, x, y):
        o = self.one(el)
        p = list(o['position'].value)
        p[0], p[1] = x, -y
        o.set('position', Val(o['position'].type, p))

    def done(self):
        """ids: every stock element outside a zero wrapper keeps its id; names stay unique"""
        idf, entry = self.idf, self.entry
        ids = []
        for kid in entry['scene']['children'].items:
            I.recompute_ids(kid, I._val(kid.get('name')), ids)
        I.relookup(entry)
        out = idf.to_bytes()
        back = I.Idf(out).scenes[0]
        names = [e.name for e, _ in back.root.walk()]
        assert len(set(names)) == len(names) or not (set(self.new) & {n for n in names if names.count(n) > 1})
        stock_names = [I._val(e.obj.get('name')) for e, _ in I.Idf(self.stock).scenes[0].root.walk()]
        assert sorted(names) == sorted(stock_names + self.new), (self.path, 'element names')
        assert len(set(ids)) == len(ids), (self.path, 'elementId collision')
        return out


def card_header(s, parent, x0, w, p, model_quad, logo_model, logo_geom, base_dy=0.0, y0=0.0, tyre=False,
                pos_text=None):
    """position cell, team logo, surname (and tyre letters): the texts under `parent`, whose origin is at
    (0, y0 - base_dy) of the card. Returns the names for the template nodes."""
    base = y0 + 0.707 * p - base_dy          # baseline of a 0.414 p cap centred in the 1 p header
    mid = y0 + 0.5 * p - base_dy
    out = {}
    if pos_text is None:
        s.text('cd_pos', parent, x0 + CELL / 2 * p, base, 'OSD_24_regular', 'centre', (CELL - 0.1) * p, layer=40)
        out['pos'] = 'cd_pos'
    s.logo('cd_logo', parent, x0 + (CELL + 0.46) * p, mid, 0.62 * p, logo_model, logo_geom)
    out['logo'] = 'cd_logo'
    right = 1.1 * p if tyre else 0.25 * p
    s.text('cd_name', parent, x0 + NAME_X * p, base, 'OSD_24_bold', 'start', w - NAME_X * p - right, layer=40)
    out['name'] = 'cd_name'
    return out


def build_pit(s, p, logo_model, logo_geom):
    """pit lane timer. Open state of the stock clips (frame 100): anim_label at y 0.24, pit_null at 0.34 with the
    three detail nulls at y 0 in it, every background null at scale 1 (the stock scene)."""
    W, H_ = 6.9 * p, 2.85 * p
    x0, x1 = -W / 2, W / 2
    for el, pos in (('anim_label', (0.0, -0.14)), ('pit_null', (0.0, -0.34)), ('anim_primary_bg', (0.0, 0.0)),
                    ('anim_secondary_bg', (0.0, -0.09998))):
        got = s.one(el)['position'].value
        assert abs(got[0] - pos[0]) < 1e-3 and abs(got[1] - pos[1]) < 1e-3, (el, got)
    LBL, PITN, SEC2 = 0.24, 0.34, 0.34 + 0.09998
    # panels
    s.rect('primary_bg', x0, 0.0, x1, H_, 'body', 25)
    s.quad('cd_head', 'anim_primary_bg', 'primary_bg', 'head', x0, 0.0, x1, p, 26)
    s.quad('cd_cell', 'anim_primary_bg', 'primary_bg', 'cell', x0, 0.0, x0 + CELL * p, p, 27)
    s.quad('cd_line', 'anim_primary_bg', 'primary_bg', 'white', x0, p, x1, 1.15 * p, 27)
    s.zero('secondary_bg')
    s.zero('divider_1')
    s.zero('title_text')
    # header
    names = card_header(s, 'anim_label', x0, W, p, 'primary_bg', logo_model, logo_geom, base_dy=LBL)
    # body: IN PIT + the lane time (stock text; its 3-decimal twin for the final time)
    ox = s.one('anim_details_pit')['position'].value[0]
    s.zero('text_pit')
    lab = s.text('cd_inpit', 'anim_details_pit', x0 + 0.4 * p - ox, 1.95 * p - PITN, '19_regular', 'left', 2.6 * p,
                 layer=32)
    H._param(lab, 'wrapping', 'none')
    run = s.null('cd_run', 'anim_details_pit')
    t = s.one('text_pit_lane_time')
    s.kids('anim_details_pit').remove(t)
    run['children'].items.append(t)
    s.parent[id(t)] = run
    s.style(t, x1 - 0.4 * p - ox, 2.15 * p - PITN, 'OSD_34_bold', 'right', 4.3 * p)
    s.text('cd_fin', 'anim_details_pit', x1 - 0.4 * p - ox, 2.15 * p - PITN, 'OSD_34_bold', 'right', 4.3 * p,
           layer=32, hidden=True)
    # under IN PIT: STOP TIME (or the penalty flag) + the stop time, small
    mx = s.one('anim_details_middle')['position'].value[0]
    # the game's string for this label holds a line break in 8 of its 11 languages (English: 'Stop \r\nTime',
    # read from the game's language file; twice seen on two lines in game whatever its box), so the stock text is
    # not shown and the card has a one-line label of its own (STOP_LABEL, the form of IN PIT and PIT LIMIT, which
    # stay on one line in game). Its node repeats the stock label's rule: hidden while the penalty flag shows
    s.zero('text_pit_lane')
    lab = s.text('cd_stop', 'anim_details_middle', x0 + 0.4 * p - mx, 2.62 * p - PITN, 'OSD_17_regular', 'left',
                 3.6 * p, layer=32)
    H._param(lab, 'wrapping', 'none')
    s.rect('penalty_flag', x0 + 0.4 * p - mx, 2.3 * p - PITN, x0 + 0.4 * p + 0.36 * p * 64 / 44 - mx, 2.66 * p - PITN)
    tx = s.one('anim_details_time')['position'].value[0]
    # right aligned under the time, so a longer label (another language) has room before it
    s.style(s.one('text_pit_time'), x1 - 0.4 * p - tx, 2.62 * p - PITN, 'OSD_17_bold', 'right', 1.6 * p)
    s.point('point_tl', x0, 0.0)
    s.point('point_br', x1, H_)
    names.update(line='cd_line', inpit='cd_inpit', run='cd_run', fin='cd_fin', stop='cd_stop')
    return names, {'w': W, 'h': H_}


def build_window(s, p):
    """NOT BUILT (see SCENES): kept for a later pass that also rewrites the texts' colour clips.
    pit window: the stock blocks keep their places and clips (title 1.08, info 1.56, aws 0.5 high); the fills
    become the cards' and a header strip with the grey line goes in"""
    x0, x1 = -1.3, 1.3
    s.zero('title_bg')
    s.rect('title_pattern', x0, 0.0, x1, 1.08, 'body', 16)
    s.quad('cd_head', 'title', 'title_pattern', 'head', x0, 0.0, x1, p, 17)
    s.quad('cd_line', 'title', 'title_pattern', 'grey', x0, p, x1, 1.12 * p, 17)
    s.style(s.one('title_text'), x0 + 0.4 * p, 0.707 * p, 'OSD_24_bold', 'left', 2.6 - 0.8 * p, textcase='upper')
    # OPEN: its holder is scaled 1.5 by the stock clip; one style smaller, its top clears the header strip
    assert I.get_param(s.one('open_text'), 'style') == '44_bold'
    H._param(s.one('open_text'), 'style', '34_bold')
    o = s.one('info_bg')
    o['geoms'].items[0].set('materialid', Val(o['geoms'].items[0]['materialid'].type, s.emb('info_bg', 'body')))
    o = s.one('lap_lockup_scaled')
    o['geoms'].items[0].set('materialid', Val(o['geoms'].items[0]['materialid'].type,
                                              s.emb('lap_lockup_scaled', 'head')))
    o = s.one('aws_bg')
    o['geoms'].items[0].set('materialid', Val(o['geoms'].items[0]['materialid'].type, s.emb('aws_bg', 'foot')))
    return {}, {'w': 2.6, 'h': 1.08 + 1.56 + 0.5}


LAP_W, LAP_HP, LAP_HS = 8.8, 2.85, 1.0      # in p: card width, header + line + body, sector strip


def build_position(s, p, logo_model, logo_geom, tyre_sprites):
    """the lap card's top: header, team line, running time (timing_position and its three session variants)"""
    W, Hh = LAP_W * p, LAP_HP * p
    x0 = -W
    s.rect('pill_bg', x0, 0.0, 0.0, Hh, 'body', 20)
    s.rect('edge_base', x0, 0.0, 0.0, p, 'head', 21)
    s.rect('edge_border', x0, 0.0, x0 + CELL * p, p, 'cell', 22)
    s.zero('lockup')
    s.rect('team_colour', x0, p, 0.0, 1.15 * p, 'white', 27)
    # position: the stock number alone, centred in the cell (the stock "/ total" is not shown)
    # out of its stacker (which would place a centred text by its left edge), into the stacker's parent
    lab = s.one('label_position_current')
    s.kids('stacker_position').remove(lab)
    tf = s.one('transitions_fade')
    tf['children'].items.append(lab)
    s.parent[id(lab)] = tf
    s.style(lab, x0 + CELL / 2 * p, 0.707 * p, 'OSD_24_regular', 'centre', (CELL - 0.1) * p)
    s.zero('stacker_position')
    # the running time in a null of its own (shown while no result colour is on) and two coloured copies
    # of it for a personal best and the session's best (the same game text; shown by DLL leaves)
    lt = s.one('label_time')
    wn = s.null('cd_lt_w', 'boundless')
    s.kids('boundless').remove(lt)
    wn['children'].items.append(lt)
    s.parent[id(lt)] = wn
    s.style(lt, x0 + 0.4 * p, 2.293 * p, 'OSD_34_bold', 'start', 4.75 * p)
    for nm in ('cd_lt_g', 'cd_lt_p'):
        s.text(nm, 'boundless', x0 + 0.4 * p, 2.293 * p, 'OSD_34_bold', 'start', 4.75 * p, textcase='mixed',
               layer=30, hidden=True)
    names = card_header(s, 'boundless', x0, W, p, 'pill_bg', logo_model, logo_geom, tyre=True, pos_text=False)
    # tyre letter: the tower's own letter sprites, one per compound, each shown by its leaf
    ts = tyre_sprites['ty_S']
    cx, cy, hh = -0.55 * p, 0.5 * p, (ts['y1'] - ts['y0']) * T.KT
    for c in TYRES:
        sp = tyre_sprites['ty_' + c]
        ww = hh * sp['w'] / sp['h']
        s.quad('cd_t' + c, 'boundless', 'pill_bg', 'tt:ty_' + c, cx - ww / 2, cy - hh / 2, cx + ww / 2, cy + hh / 2,
               30, hidden=True)
    s.point('tl', x0, 0.0)
    s.point('br', 0.0, Hh)
    names.update({'t' + c: 'cd_t' + c for c in TYRES})
    names.update(ltw='cd_lt_w', ltg='cd_lt_g', ltp='cd_lt_p')
    return names, {'w': W, 'h': Hh}


def sector_bars(p):
    """[(x0, x1)] of the three bars, and their (y0, y1), in the strip's frame (origin top right)"""
    W = LAP_W * p
    m, g = 0.4 * p, 0.12 * p
    wb = (W - 2 * m - 2 * g) / 3
    return [(-W + m + k * (wb + g), -W + m + k * (wb + g) + wb) for k in range(3)], (0.70 * p, 0.82 * p)


def build_sectors(s, p, win_model):
    W, Hs = LAP_W * p, LAP_HS * p
    bars, (y0, y1) = sector_bars(p)
    s.one('sector_null').set('position', H._vec((0.0, 0.0, 0.0)))
    s.rect('bg', -W, 0.0, 0.0, Hs, 'body', 28)
    s.zero('edge_border')
    s.zero('edge_base')
    for k, (a, b) in enumerate(bars, 1):
        s.style(s.one(f'label_s{k}'), a, 0.52 * p, 'OSD_17_bold', 'start', b - a)
        s.rect(f'bg_s{k}_unfilled', a, y0, b, y1, 'track', 29)
        step = (b - a) / NSTEP
        for j in range(NSTEP):
            # step j covers the bar from its start to (j + 1) / NSTEP: lit steps overlap, so no seam can show
            s.quad(f'cd_s{k}p{j:02d}', 'sector_null', 'bg_s1_unfilled', 'white', a, y0,
                   a + (j + 1) * step, y1, 32, hidden=True)   # above the game's colour quad (31)
    # the game's colour quads draw a texture with a gradient (darker at the left) [game], and sector 3's sat
    # in a stock window whose mask cut its bottom right corner [game]. Each colour quad now sits in a plain clip
    # window of the bar's rect (a copy of dial_mods' window: the halo's and the tower's, clipping in game) and is
    # BAR_OVER times the bar's width, its right end on the bar's: only the gradient's bright last part shows
    mask = s.one('bg_s3_mask')
    q3 = s.one('bg_s3')
    s.kids('bg_s3_mask').remove(q3)
    s.kids('sector_null').append(q3)
    s.parent[id(q3)] = s.one('sector_null')
    s.zero('bg_s3_mask')
    w, l = bars[0][1] - bars[0][0], y1 - y0
    for k in (1, 2, 3):
        a, b = bars[k - 1]
        win = s._new(win_model, f'cd_sw{k}', 'sector_null')
        win.set('position', H._vec(((a + b) / 2, -(y0 + y1) / 2, -0.03)))
        win.set('scale', H._vec((1.0, 1.0, 1.0)))
        win.set('rotation', Val('quat', [-0.0, -0.0, 0.0, -1.0]))
        H._param(win, 'width', float(w), 'fp32')
        H._param(win, 'length', float(l), 'fp32')
        H._param(win, 'minExtents', [-w / 2, -l / 2, -0.0, 0.0], 'vec3')
        H._param(win, 'maxExtents', [w / 2, l / 2, -0.0, 0.0], 'vec3')
        q = s.one(f'bg_s{k}')
        s.kids('sector_null').remove(q)
        win['children'].items.append(q)
        s.parent[id(q)] = win
        s.rect(f'bg_s{k}', w / 2 - BAR_OVER * w, -l / 2, w / 2, l / 2)
        qp = list(q['position'].value)
        qp[2] = 0.03                                     # back to the strip's depth, as the stock window's quad
        q.set('position', Val(q['position'].type, qp))
    s.point('tl', -W, 0.0)
    s.point('br', 0.0, Hs)
    return {f's{k}p{j:02d}': f'cd_s{k}p{j:02d}' for k in (1, 2, 3) for j in range(NSTEP)}, {'w': W, 'h': Hs}


def build_pills(s, p):
    """best / previous rows: the stretched background at the card's width and fill; the delta first in its stacker
    (so it hangs from the strip's bottom edge whatever the rows below do)"""
    W = LAP_W * p
    o = s.one('pill_bg')
    lo, hi = s.ext(o)
    sx = W / (hi[0] - lo[0])
    sc = o['scale'].value
    o.set('scale', Val(o['scale'].type, [sx, sc[1], sc[2], 0.0]))
    pp = list(o['position'].value)
    pp[0] = -sx * hi[0]
    o.set('position', Val(o['position'].type, pp))
    o['geoms'].items[0].set('materialid', Val(o['geoms'].items[0]['materialid'].type, s.emb('pill_bg', 'body')))
    # the rows' background ended at the last text [game]. The scaler that stretches it has margins (stock 0;
    # the stock scenes use the left / right ones): ROW_PAD under the rows. The fill is the card's body, so the
    # margin reads as the card's bottom padding with or without a row
    sb = s.one('scaler_bg')
    assert I.get_param(sb, 'bottomMargin') == 0 and I.get_param(sb, 'scaleY') is True
    H._param(sb, 'bottomMargin', float(ROW_PAD), 'fp32')
    for el in ('lockup', 'edge_border', 'edge_base'):
        s.zero(el)
    # the delta pill out of the rows' stacker and the background's scaler (they measure what they hold, and the
    # delta's content is drawn above its origin): beside them, at the scene's origin = the strip's bottom edge.
    # The stock node finds it by name (its layout 'timing_pill_delta > anim_pill' sits under a group whose own
    # target, pill_stacker, never held it)
    kids = s.kids('delta_stacker')
    assert [I._val(k.get('name')) for k in kids] == ['pill_stacker', 'timing_pill_delta'], 'delta stacker'
    d = kids.pop(1)
    tf = s.one('transition_fade')
    tf['children'].items.append(d)
    s.parent[id(d)] = tf
    d.set('position', H._vec((0.0, 0.0, 0.0)))
    s.point('tr', 0.0, 0.0)
    return {}, {'w': W}


def build_row(s, p):
    W = LAP_W * p
    # small upper-case label (the game's own text and grey), an even row pitch
    s.style(s.one('label_title'), -W + 0.4 * p, ROW_BASE, 'OSD_17_regular', 'start', 4.2 * p, wrapping='none',
            textcase='upper')
    s.style(s.one('label_time'), -0.4 * p, ROW_BASE, 'OSD_19_regular', 'end', 4.0 * p)
    s.point('tl', -W, 0.0)
    s.point('br', 0.0, ROW_H)
    return {}, {'w': W, 'h': ROW_H}


def build_delta(s, p):
    """the gap to the own best: the stock delta pill's own texts and colour quad, placed in the card's body (the
    pill hangs LAP_HS below the body: its content is drawn above its own origin); the pill's art is not shown"""
    up = (LAP_HP + LAP_HS) * p                     # the card's top above the pill's origin
    y = lambda card_y: card_y * p - up             # noqa: E731
    b = s.one('boundless')
    b.set('rotation', Val('quat', [-0.0, -0.0, 0.0, -1.0]))
    b.set('position', H._vec((0.0, 0.0, 0.0)))
    for el in ('pill_bg', 'edge_base', 'edge_border', 'lockup', 'pill_base', 'delta_icon'):
        s.zero(el)
    col = s.one('pill_colour')
    s.kids('pill_pattern_mask').remove(col)
    b['children'].items.append(col)
    s.parent[id(col)] = b
    s.zero('pill_pattern_mask')
    xr = -0.4 * p
    s.rect('pill_colour', xr - 3.1 * p, y(2.46), xr, y(2.56))
    s.style(s.one('label_title'), xr, y(1.62), 'OSD_11_regular', 'right', 4.0 * p, wrapping='none', textcase='upper')
    s.style(s.one('label_time'), xr, y(2.293), 'OSD_24_bold', 'right', 3.1 * p)
    s.point('tl', -LAP_W * p, 0.0)
    s.point('br', 0.0, 0.0)
    return {}, {}


def build_banner_block(s, p, boundless=None):
    """the pit speed unit: the state colour stays in the game's own construction. Stock
    (the stock scene): black_bg, a 0.8 x 0.8 quad, is a child of bg_holder (eScalee), which the
    unit's eScaler speed_limit_bg_scaler stretches in x to the extents of the limit text (margins 0.2 / 0.18); its
    clip holds green up to frame 20 and red at frame 30, played by the template from the message's own is_speeding
    [code]; red and green were seen in game. An earlier build took the quad out of the holder and gave it a fixed
    width: in the pit lane, where the message has no texts, the bar ran far past the panel (seen in game). Now nothing
    here has a width of its own: the quad's x extent is the stock 0.8 the game stretches. Only its height changes: the
    message fill's 0.86, 0.03 higher (central_message's fill as the Race Control banner builds it), so the block and
    the message's panel are one band. PIT LIMIT (static English) sits above the limit; both are inside the scaler,
    so the game sizes the block to the wider of the two."""
    o = s.one('black_bg')
    holder, scaler = s.one('bg_holder'), s.one('speed_limit_bg_scaler')
    assert s.parent[id(o)] is holder and s.parent[id(holder)] is scaler, 'the stock block: black_bg in bg_holder in the scaler'
    assert I._val(scaler.get('typeName')) == 'eScaler' and I.get_param(scaler, 'scaleX') is True
    assert I.get_param(holder, 'eScalee.enabled') is True, 'bg_holder is what the scaler stretches'
    lo, hi = s.ext(o)
    sc = list(o['scale'].value)
    assert abs(sc[0] - 1) < 1e-6 and abs(sc[2] - 1) < 1e-6 and abs(hi[0] - lo[0] - 0.8) < 1e-3 and abs(hi[2] - lo[2] - 0.8) < 1e-3
    x_before = (tuple(lo), tuple(hi), sc[0], o['position'].value[0])
    sc[2] = BANNER_H / 0.8
    o.set('scale', Val(o['scale'].type, sc))
    pos = list(o['position'].value)
    pos[1] += BANNER_UP
    o.set('position', Val(o['position'].type, pos))
    lo2, hi2 = s.ext(o)
    assert (tuple(lo2), tuple(hi2), o['scale'].value[0], o['position'].value[0]) == x_before, 'the block keeps its stock x'
    t = s.one('speed_value_text')
    assert s.parent[id(t)] is s.one('speed_centre') and s.parent[id(s.one('speed_centre'))] is scaler
    tp = list(t['position'].value)
    tp[1] += 0.093 + 0.086      # onto the message's baseline (measured in game)
    t.set('position', Val(t['position'].type, tp))
    lab = s.text('cd_limlab', 'speed_centre', 0.0, tp[1] * -1 - 0.244 - 0.07, 'OSD_17_regular', 'centre', 2.0, layer=70)   # right above the limit's caps
    H._param(lab, 'wrapping', 'none')
    # nothing of ours in this scene but the label: no quad, no container
    assert s.new == ['cd_limlab'], s.new
    return {'label': 'cd_limlab'}, {'block': {'height': BANNER_H, 'up': BANNER_UP, 'x': 'stock (stretched by speed_limit_bg_scaler)'}}


def box_of(o):
    """what places and sizes a quad under its parent: position, rotation, scale, extents, mesh"""
    g = o['geoms'].items[0]
    return (tuple(o['position'].value), tuple(o['rotation'].value), tuple(o['scale'].value),
            tuple(I.get_param(o, 'minExtents')), tuple(I.get_param(o, 'maxExtents')), I._val(g.get('modelid')) if g.get('modelid') is not None else None)


def build_message_state(s, p):
    """the pit speed colour on the message's panel: two copies of pill_bn, the navy twin of the message fill
    (banner_native: same mesh and place as the stock fill `pill`, absolute layer 60, drawn right in game for every
    message). They hang under the same parent, the bg_holder the message's own eScaler stretches to its
    texts, with the same transform and mesh: whatever box the game gives the panel, they have it. Hidden unless the
    template's two nodes show them. -> (names, info)"""
    base = s.one('pill_bn')
    par = s.parent[id(base)]
    scaler = s.parent[id(par)]
    assert I._val(par.get('name')) == 'bg_holder' and I.get_param(par, 'eScalee.enabled') is True
    assert I._val(scaler.get('typeName')) == 'eScaler' and I.get_param(scaler, 'scaleX') is True
    assert s.parent[id(s.one('pill'))] is par and box_of(s.one('pill'))[:5] == box_of(base)[:5], 'pill_bn is the fill\'s twin'
    names = {}
    for key, nm, fill, layer in STATE_TWINS:
        o = s._new(base, nm, par)
        o['geoms'].items[0].set('materialid', Val(o['geoms'].items[0]['materialid'].type, s.emb('pill', fill)))
        H._param(o, 'eLayer.layer', int(layer), 'si32')
        H._param(o, 'eLayer.layerIsOffset', False, 'bool')
        I.set_param(o, 'isHidden', True, 'bool')
        s.hidden_default.append(nm)
        # the test: the colour's box is the panel's box, in every state, because every value
        # that places or sizes it equals the panel twin's and both hang under the element the game stretches
        assert s.parent[id(o)] is par and box_of(o) == box_of(base), (nm, 'differs from the panel fill')
        assert not (o.get('anims') is not None and o['anims'].items), (nm, 'has a clip of its own')
        names[key] = nm
    assert s.new == [nm for _k, nm, _f, _l in STATE_TWINS], s.new
    return names, {'twins': [nm for _k, nm, _f, _l in STATE_TWINS], 'of': 'pill_bn', 'parent': 'bg_holder (eScalee of scaler)',
                   'box': [list(x) if isinstance(x, tuple) else x for x in box_of(base)[:5]]}


def build_stack(s, p):
    """the element's stacker: the card's top first, then the sector strip, then the rows"""
    kids = s.kids('practice_stacker')
    names = [I._val(k.get('name')) for k in kids]
    assert names[:2] == ['timing_sectors', 'timing_position'], names
    kids[0], kids[1] = kids[1], kids[0]
    y = 0.0
    for k, h in zip(kids[:3], (LAP_HP * p, LAP_HS * p, 0.0)):
        pos = list(k['position'].value)
        pos[1] = -y
        k.set('position', Val(k['position'].type, pos))
        y += h
    return {}, {}


def recolour_clip(frags, rgb, only=None):
    """A text's colour clip (2 fragments: the packet tree, then the key data) with every DiffuseColour key set to
    rgb. The stock layout is asserted (the Race Control label's, banner_native.label_clip): per key and component
    5 floats (value, in value, in time, out value, out time), the keys right after the key times. Only the R, G
    and B values change: every time, the alpha and any other channel stay. only: change just the keys that hold
    this stock colour (the banner's green keys; its red key stays). -> [fragments]"""
    import struct
    assert len(frags) == 2, len(frags)
    p = Pkg(frags[0])
    chans = [(pk, ch) for pk in p.root['packets'].items for ch in pk['channels'].items
             if ch['name'].value == 'DiffuseColour']
    assert len(chans) == 1, 'one DiffuseColour channel'
    pk, ch = chans[0]
    kp, tp = ch['keyptr'].value, ch['timesptr'].value
    b = bytearray(frags[1])
    nk = (kp - tp) // 4
    assert nk in (2, 3, 4) and kp % 4 == 0 and len(b) >= kp + nk * 80, (tp, kp, len(b))
    times = struct.unpack_from(f'<{nk}f', b, tp)
    assert abs(times[0]) < 1e-6 and all(x < y for x, y in zip(times, times[1:])), times
    hit = 0
    for key in range(nk):
        cur = [struct.unpack_from('<f', b, kp + 20 * (key * 4 + c))[0] for c in range(3)]
        if only is not None and any(abs(x - y) > 2e-3 for x, y in zip(cur, only)):
            continue
        hit += 1
        for comp in range(4):
            at = kp + 20 * (key * 4 + comp)
            g = struct.unpack_from('<5f', b, at)
            assert abs(g[0] - g[1]) < 1e-3 and abs(g[0] - g[3]) < 1e-3 and 0.0 <= g[0] <= 1.001, (key, comp, g)
            if comp == 3:
                assert abs(g[0] - 1.0) < 1e-3, ('alpha', g)
            else:
                for j in (0, 1, 3):
                    struct.pack_into('<f', b, at + 4 * j, float(rgb[comp]))
    assert hit and (only is None or hit < nk), ('keys changed', hit, nk)
    assert bytes(b[:kp]) == frags[1][:kp] and len(b) == len(frags[1])
    return [frags[0], bytes(b)]


# ---------------------------------------------------------------- template
def _add(root, parent_path, nodes):
    par = H._node_at(root, parent_path)
    assert par is not None, parent_path
    have = {N.name(c) for c in N.children(par)}
    for n in nodes:
        assert N.name(n) not in have, (parent_path, N.name(n))
        N.fix_ids(n, parent_path)
        par.items[N.CHILDREN].items.append(n)
    return len(nodes)


def _vis(name, el, key, neg=False):
    return U.node(name, 'UIGP', [('visible', H._bool_prop(neg, leaf(key), neg))], layout=[el],
                  behav=U.GROUP_BEHAVIOURS)


def header_nodes(names, badge_tag, ctx, dll_badge=True):
    """ctx: '' for bindings relative to the group's data context (the pit timer's car), or an absolute car path"""
    out = []
    if 'pos' in names:
        out.append(U.node('cd_t_pos', 'UILB', [('text', U.prop('ui32', 1, ctx + 'position')),
                                            ('colourOverride', U.prop('rgba', TEXT_WHITE))], layout=[names['pos']],
                          behav=U.LABEL_BEHAVIOURS))
    out.append(U.node('cd_t_name', 'UILB', [('text', U.prop('stri', '', ctx + 'driver.second_name')),
                                         ('colourOverride', U.prop('rgba', TEXT_WHITE))],
                      layout=[names['name']], behav=U.LABEL_BEHAVIOURS))
    if dll_badge:
        out.append(_vis('cd_v_logo', names['logo'], 'bdg'))
        out.append(U.node('cd_x_logo', 'UIGP', [(T.STOCK_BADGE[1], U.prop(badge_tag, T._default(badge_tag),
                                                                         leaf('badge')))],
                          layout=[names['logo'], T.LOGO_QUAD], behav=U.GROUP_BEHAVIOURS))
    else:
        out.append(U.hidden('cd_v_logo', names['logo']))
    return out


def template(ui_bytes, names, badge_tag):
    """the cards' nodes in hud_dynamic_templates.ui. No stock node is changed or removed.
    -> (bytes, node count, [(leaf, tag)] the DLL leaves bound)"""
    p = Pkg(ui_bytes)
    n = 0
    binds = []
    # pit lane timer (and its split-screen twin: the guest car has no DLL leaves, so no logo and no final time)
    for root, dll in (('hud_pit_lane_timer', True), ('hud_pit_lane_timer_p2', False)):
        base = f'{root}.osd_visibility_option.pit_timer'
        nm = names[PIT]
        nodes = header_nodes(nm, badge_tag, '', dll)
        nodes.append(U.node('cd_c_line', 'UIGP', [('colourOverride', U.prop('rgba', '#00000000', 'nub_colour'))],
                            layout=[nm['line']], behav=U.GROUP_BEHAVIOURS))
        nodes.append(U.node('cd_t_inpit', 'UILB', [('localise', U.prop('bool', True)),
                                                   ('text', U.prop('stri', 'lng_in_pit_lowercase')),
                                                   ('colourOverride', U.prop('rgba', LABEL_GREY))],
                            layout=[nm['inpit']], behav=U.LABEL_BEHAVIOURS))
        # the card's own STOP TIME label, shown as the stock one is (not while the penalty flag shows)
        nodes.append(U.node('cd_t_stop', 'UILB', [('visible', H._bool_prop(False, 'pit_penalty', True)),
                                                  ('localise', U.prop('bool', False)),
                                                  ('text', U.prop('stri', STOP_LABEL)),
                                                  ('colourOverride', U.prop('rgba', LABEL_GREY2))],
                            layout=[nm['stop']], behav=U.LABEL_BEHAVIOURS))
        if dll:
            nodes.append(_vis('cd_v_run', nm['run'], 'pfin', neg=True))
            nodes.append(U.node('cd_t_fin', 'UILB', [('visible', H._bool_prop(False, leaf('pfin'))),
                                                     ('text', U.prop('stri', '', leaf('pit3'))),
                                                     ('colourOverride', U.prop('rgba', TEXT_WHITE))],
                                layout=[nm['fin']], behav=U.LABEL_BEHAVIOURS))
            nodes.append(U.node('cd_fmt3', 'UIVF', [('value_to_format', U.prop('fp32', 0.0, 'pit_lane_timer')),
                                                    ('database_output', U.prop('stri', '', leaf('pit3'))),
                                                    ('decimal_places', U.prop('ui08', 3))]))
            binds += [(leaf('bdg'), 'bool'), (leaf('badge'), 'stri'), (leaf('pfin'), 'bool'), (leaf('pit3'), 'stri')]
        else:
            nodes.append(U.hidden('cd_v_fin', nm['fin']))
        n += _add(p.root, base, nodes)
    # lap times: the same nodes under each session's timing_position and timing_sectors groups
    for st in ('default', 'practice', 'qualifying', 'time_trial'):
        root = f'hud_timing_pill_stack_{st}.osd_visibility_option'
        nm = names[POS[0]]
        nodes = header_nodes(nm, badge_tag, '#session.current_car.')
        nodes += [_vis('cd_v_t' + c, nm['t' + c], 't' + c) for c in TYRES]
        # the lap time's result colour. The stock node label_time binds formatted_time_string (stri) in
        # this group's own view model: the copies bind the same
        nodes.append(_vis('cd_v_ltw', nm['ltw'], 'lcol', neg=True))
        for key, el, col in (('lpb', nm['ltg'], LAP_GREEN), ('lob', nm['ltp'], LAP_PURPLE)):
            nodes.append(U.node('cd_t_' + key, 'UILB', [('visible', H._bool_prop(False, leaf(key))),
                                                        ('text', U.prop('stri', '', 'formatted_time_string')),
                                                        ('colourOverride', U.prop('rgba', col))],
                                layout=[el], behav=U.LABEL_BEHAVIOURS))
        n += _add(p.root, root + '.timing_position', nodes)
        sn = names[SEC]
        n += _add(p.root, root + '.timing_sectors', [_vis('cd_v_' + k, el, k) for k, el in sn.items()])
    # the PIT LIMIT label in both toasts' pit speed group (a static text; no binding)
    if BANNER in names:
        for toast in BN.TOASTS:
            n += _add(p.root, f'{toast}.osd_visibility_option.{toast}.{BANNER_GROUP}',
                      [U.node('cd_t_limlab', 'UILB', [('localise', U.prop('bool', False)),
                                                      ('text', U.prop('stri', BANNER_LABEL)),
                                                      ('colourOverride', U.prop('rgba', TEXT_WHITE))],
                              layout=[names[BANNER]['label']], behav=U.LABEL_BEHAVIOURS)])
    if CM in names:
        for toast in BN.TOASTS:
            grp = f'{toast}.osd_visibility_option.{toast}.{BN.GROUP[CM]}'
            n += _add(p.root, grp,
                      [U.node('cd_v_stg', 'UIGP', [('visible', U.prop('bool', False, 'user_attributes.pit_speed_icon.Value'))],
                              layout=[names[CM]['green']], behav=U.GROUP_BEHAVIOURS),
                       U.node('cd_v_str', 'UIGP', [('visible', U.prop('bool', False, 'user_attributes.is_speeding.Value'))],
                              layout=[names[CM]['red']], behav=U.GROUP_BEHAVIOURS)])
    binds += [(leaf('t' + c), 'bool') for c in TYRES] + [(leaf(k), 'bool') for k in names[SEC]]
    binds += [(leaf(k), 'bool') for k in ('lcol', 'lpb', 'lob')]
    return p.to_bytes(), n, sorted(set(binds))
