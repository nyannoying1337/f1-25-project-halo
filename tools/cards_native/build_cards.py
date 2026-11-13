"""Build the broadcast cards' archives (0.2.2). Run after build_tower.py (it reads erp/tower_template.erp).

usage: python -I build_cards.py <stock folder> <tower sprites dir> <addon dir> <work dir> [--leaves <leaves.txt>]

Writes
  erp/cards_pit.erp       flow_race, flow_options, persistent, screens/hud_spectator_2: the pit lane timer scene, the cards' fills (textures, materials) and material bindings
  erp/cards_timing.erp    flow_race, flow_options, persistent: the lap time scenes, fills and bindings
  erp/cards_timing2.erp   flow_race, flow_options: the qualifying and Time Trial position scenes (stock keeps them
                          in these two archives only)
  erp/cards_template.erp  flow_race, flow_options: hud_dynamic_templates.ui = the tower's + the cards' nodes
  erp/halo.json           the cards' ops with "when": {"cards": true}; the tower's template op gets
                          "when": {"cards": false} (the option "Broadcast cards": off = none of the cards' files)
  <work>/cards_info.json, cards_scene.json (for the simulator and the checks)
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cards_native as C  # noqa: E402
T, TR, BN, I = C.T, C.TR, C.BN, C.I
import erpbuild as E  # noqa: E402
import emb  # noqa: E402
import resources as R  # noqa: E402
from build_native import read, index, MAT, MODS  # noqa: E402

UI = '2025_asset_groups/ui_package/'
A_RACE, A_OPT, A_PERS, A_SPEC = (UI + 'flow_race.erp', UI + 'flow_options.erp', UI + 'persistent.erp',
                                 UI + 'screens/hud_spectator_2.erp')
TEMPLATE = 'eaid://ui_package/templates/hud_dynamic_templates.ui'
OPTION = 'cards'
FILES = {'erp/cards_pit.erp': [A_RACE, A_OPT, A_PERS, A_SPEC], 'erp/cards_timing.erp': [A_RACE, A_OPT, A_PERS],
         'erp/cards_timing2.erp': [A_RACE, A_OPT], 'erp/cards_template.erp': [A_RACE, A_OPT]}


def where(scene):
    if scene in C.ERPS4:
        return 'erp/cards_pit.erp'
    return 'erp/cards_timing2.erp' if scene in C.ERPS2 else 'erp/cards_timing.erp'


def dump(idf_bytes, embs_rev):
    """the built scene as a tree for the simulator: every element with its local transform and what it draws"""
    def node(e):
        o = e.obj
        d = {'name': e.name, 'type': e.type, 'pos': list(o['position'].value[:3]), 'scale': list(o['scale'].value[:3]),
             'hidden': bool(I.get_param(o, 'isHidden')), 'kids': [node(c) for c in e.children]}
        if e.geoms:
            lo, hi = I.get_param(o, 'minExtents'), I.get_param(o, 'maxExtents')
            d.update(quad=[lo[0], lo[2], hi[0], hi[2]], mat=embs_rev.get(e.geoms[0]['materialid'], 'stock'),
                     layer=I.get_param(o, 'eLayer.layer'))
        if e.type == 'eText':
            d.update(style=I.get_param(o, 'style'), halign=I.get_param(o, 'halign'), box=I.get_param(o, 'boxWidth'),
                     wrapping=I.get_param(o, 'wrapping'), textcase=I.get_param(o, 'textcase'),
                     layer=I.get_param(o, 'eLayer.layer'))
        if e.type == 'eXRef':
            d['ref'] = I.get_param(o, 'fileRef')
        if e.type == 'eWindow':
            d['win'] = [I.get_param(o, 'width'), I.get_param(o, 'length')]
        if e.type == 'eStacker':
            d.update(stackerType=I.get_param(o, 'stackerType'), gap=I.get_param(o, 'gap'))
        return d
    return node(I.Idf(idf_bytes).scenes[0].root)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stock')
    ap.add_argument('sprites')
    ap.add_argument('addon')
    ap.add_argument('work')
    ap.add_argument('--leaves')
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    race = os.path.join(a.stock, A_RACE)
    meta = json.load(open(os.path.join(a.sprites, 'sprites.json')))
    p = T.KT * meta['G']['p']
    names_idx = {r[0] for r in index(race)[1]}
    # stock scenes, their material bindings and the meshes the cards copy; each the same in every archive that has it
    stock, slots, meshes = {}, {}, {}
    for sc in C.SCENES:
        base = sc[:-4]
        want = [sc] + sorted(n for n in names_idx if n.startswith(base + '.emb')) + \
            sorted(n for n in names_idx if n.startswith(sc + '/') and n.endswith('&mesh'))
        got = read(race, want)
        stock[sc] = got[sc][0]
        slots[sc] = [s for n in want if '.emb' in n for s, _ in emb.parse(got[n][0])]
        meshes.update({n: got[n] for n in want if n.endswith('&mesh')})
        for arch in FILES[where(sc)][1:]:
            other = read(os.path.join(a.stock, arch), want)
            assert all(other[n] == got[n] for n in want), f'{arch} carries a different {sc}'
    # the STOP TIME row's two colour clips (the pit scene's own), the same in every archive that has them
    clip_names = {el: f'{C.PIT}/{el}?context=animation' for el in C.CLIP_RGB}
    clip_stock = read(race, list(clip_names.values()))
    for arch in FILES['erp/cards_pit.erp'][1:]:
        assert read(os.path.join(a.stock, arch), list(clip_names.values())) == clip_stock, f'{arch}: other clips'
    clips = {clip_names[el]: C.recolour_clip(clip_stock[clip_names[el]], rgb) for el, rgb in C.CLIP_RGB.items()}
    # the banner's state clip with its green keys darker (the red key and every time stay)
    bclip = f'{C.BANNER}/black_bg?context=animation'
    bclip_stock = read(race, [bclip])[bclip]
    for arch in FILES['erp/cards_timing.erp'][1:]:
        assert read(os.path.join(a.stock, arch), [bclip])[bclip] == bclip_stock, f'{arch}: another banner clip'
    bclip_new = C.recolour_clip(bclip_stock, C.BANNER_GREEN, only=C.BANNER_STOCK_GREEN)
    # the pit banner's limit block, from the Race Control banner build's scene (tower_scene.erp, built
    # before); its stock binding and mesh for the slot. The scene is the same in the three archives it lives in
    tscene = E.read_all(os.path.join(a.addon, 'erp', 'tower_scene.erp'))
    assert tscene[C.BANNER][0] == 'UILayout', 'build the tower first'
    bbase = C.BANNER[:-4]
    bwant = sorted(n for n in names_idx if n.startswith(bbase + '.emb')) + \
        sorted(n for n in names_idx if n.startswith(C.BANNER + '/') and n.endswith('&mesh'))
    bgot = read(race, bwant + [C.BANNER])
    for arch in FILES['erp/cards_timing.erp'][1:]:
        other = read(os.path.join(a.stock, arch), bwant + [C.BANNER])
        assert all(other[n] == bgot[n] for n in bwant + [C.BANNER]), f'{arch} carries a different {C.BANNER}'
    stock[C.BANNER] = tscene[C.BANNER][1][0]
    # the message scene too (the Race Control banner build's, with the navy twin of its fill)
    assert tscene[C.CM][0] == 'UILayout'
    cbase = C.CM[:-4]
    cwant = sorted(n for n in names_idx if n.startswith(cbase + '.emb')) + \
        sorted(n for n in names_idx if n.startswith(C.CM + '/') and n.endswith('&mesh'))
    cgot = read(race, cwant + [C.CM])
    for arch in FILES['erp/cards_timing.erp'][1:]:
        other = read(os.path.join(a.stock, arch), cwant + [C.CM])
        assert all(other[n] == cgot[n] for n in cwant + [C.CM]), f'{arch} carries a different {C.CM}'
    stock[C.CM] = tscene[C.CM][1][0]
    slots[C.CM] = [s for n in cwant if '.emb' in n for s, _ in emb.parse(cgot[n][0])]
    meshes.update({n: cgot[n] for n in cwant if n.endswith('&mesh')})
    slots[C.BANNER] = [s for n in bwant if '.emb' in n for s, _ in emb.parse(bgot[n][0])]
    meshes.update({n: bgot[n] for n in bwant if n.endswith('&mesh')})
    unit = read(race, [T.ROW, T.LOGO, MAT, TEMPLATE])
    row_idf = I.Idf(unit[T.ROW][0])
    xr = [e.obj for e, _ in row_idf.scenes[0].root.walk() if e.name == T.LOGO_XREF]
    assert len(xr) == 1 and I.get_param(xr[0], 'fileRef') == T.LOGO
    lcx, lcy, lside, _layer = T.logo_geometry(unit[T.LOGO][0])
    logo_geom = ((lcx, lcy), lside)
    badge_tag = T.stock_badge_tag(unit[TEMPLATE][0])

    # the plain clip window the sector bars' colour quads sit in (dial_mods' window, the halo's and the
    # tower's model)
    mods = I.Idf(read(race, [MODS])[MODS][0])
    win_model = T.H._find(mods.scenes[0].entry['scene'], 'mod_1_icon_fill_mask')
    assert win_model is not None and I._val(win_model.get('typeName')) == 'eWindow' and not win_model['geoms'].items
    embs, built, names, info, hidden = {}, {}, {}, {}, {}
    jobs = [(C.PIT, lambda s: C.build_pit(s, p, xr[0], logo_geom)),
            (C.SEC, lambda s: C.build_sectors(s, p, win_model)), (C.PILLS, lambda s: C.build_pills(s, p)),
            (C.BEST, lambda s: C.build_row(s, p)), (C.PREV, lambda s: C.build_row(s, p)),
            (C.DELTA, lambda s: C.build_delta(s, p))]
    jobs += [(x, lambda s: C.build_position(s, p, xr[0], logo_geom, meta['sprites'])) for x in C.POS]
    jobs += [(x, lambda s: C.build_stack(s, p)) for x in C.STACKS]
    bl = [e.obj for e, _ in I.Idf(stock[C.PIT]).scenes[0].root.walk() if e.type == 'eBoundless']
    assert len(bl) == 1, 'the pit lane timer scene: one eBoundless to copy'
    jobs += [(C.BANNER, lambda s: C.build_banner_block(s, p)), (C.CM, lambda s: C.build_message_state(s, p))]
    for sc, fn in jobs:
        s = C.CS(sc, stock[sc], meshes, slots[sc], embs)
        names[sc], inf = fn(s)
        built[sc] = s.done()
        hidden[sc] = s.hidden_default
        inf.update(new=len(s.new), bytes=[len(stock[sc]), len(built[sc])])
        info[sc.split('/')[-1]] = inf
    for x in C.POS[1:]:
        assert names[x] == names[C.POS[0]]

    # the template: the tower's (built before) + the cards' nodes
    tower_tmpl = E.read_all(os.path.join(a.addon, 'erp', 'tower_template.erp'))[TEMPLATE][1][0]
    tmpl, nnodes, binds = C.template(tower_tmpl, names, badge_tag)
    ours = {db: tag for db, tag in binds}
    nv, _groups = T.check_vm_hashes(ours, [tmpl, unit[TEMPLATE][0]])
    if a.leaves:
        dll = T.dll_leaves(a.leaves)
        bad = [f'{db} {t}: the DLL writes {dll.get(db, "nothing")}' for db, t in binds if dll.get(db) != t]
        if bad:
            raise SystemExit('cards bindings vs the DLL leaf list:\n  ' + '\n  '.join(bad[:8]))
        extra = sorted(k for k in dll if k.startswith(C.VM) and k not in ours)
        if extra:
            raise SystemExit(f'DLL card leaves no node binds: {extra[:8]}')

    # resources: one texture + material per fill; a binding per (scene mesh slot, fill)
    cache = os.path.join(a.work, 'bc7_cache')
    os.makedirs(cache, exist_ok=True)
    fills = []
    for name, c in C.FILLS.items():
        tex, mat = C.TEX.format(name), C.MAT.format(name)
        img = np.tile(np.array(c, np.uint8), (16, 16, 1))
        fills += [(tex + '.image', 'GfxSurfaceRes', list(R.surface(img, cache))), (tex, 'GfxSRVResource', [R.srv(tex)]),
                  (mat, 'GfxMaterialRes', [R.material(unit[MAT][0], tex)])]
    arch = {f: E.Archive(race) for f in FILES}
    for f in ('erp/cards_pit.erp', 'erp/cards_timing.erp'):
        for n, t, fr in fills:
            # the two pit speed fills belong to the message scene's archive only
            if f == 'erp/cards_pit.erp' and ('/cd_pgreen.' in n or '/cd_pred.' in n):
                continue
            arch[f].add(n, t, fr)
    for sc in C.SCENES + [C.BANNER, C.CM]:
        arch[where(sc)].add(sc, 'UILayout', [built[sc]])
    by_key = sorted(C.SCENES + [C.BANNER, C.CM], key=len, reverse=True)
    for path, pairs in sorted(embs.items()):
        key = path.split('/cd_')[1]
        sc = next(s for s in by_key if key.startswith(s.split('/')[-1][:-4] + '_'))
        arch[where(sc)].add(path, 'GfxMatBindRes', [emb.write(pairs)])
    for n, fr in sorted(clips.items()):
        arch['erp/cards_pit.erp'].add(n, 'AnimClip', fr)
    arch['erp/cards_timing.erp'].add(bclip, 'AnimClip', bclip_new)
    arch['erp/cards_template.erp'].add(TEMPLATE, 'UIDF', [tmpl])
    sizes = {f: arch[f].write(os.path.join(a.addon, f)) for f in FILES}
    for f in FILES:
        back = E.read_all(os.path.join(a.addon, f))
        assert len(back) == len(arch[f].res), f
    back = E.read_all(os.path.join(a.addon, 'erp/cards_pit.erp'))
    assert all(list(back[n][1]) == list(fr) for n, fr in clips.items())
    assert E.read_all(os.path.join(a.addon, 'erp/cards_template.erp'))[TEMPLATE][1][0] == tmpl

    # ops: the cards behind the option, the tower's template op only without them
    ops_path = os.path.join(a.addon, 'erp', 'halo.json')
    ops = json.load(open(ops_path))
    keep = [o for o in ops['ops'] if not o['source'].startswith('erp/cards_')]
    for o in keep:
        if o['source'] == 'erp/tower_template.erp':
            o['when'] = {OPTION: False}
    assert sum(1 for o in keep if o['source'] == 'erp/tower_template.erp') == 1, 'build the tower first'
    new = [{'op': 'overlay', 'when': {OPTION: True}, 'erps': FILES[f], 'source': f} for f in FILES]
    json.dump({'schema_version': ops['schema_version'], 'ops': keep + new}, open(ops_path, 'w'), indent=2)

    rev = {k: k.split('/cd_')[1].split('.emb')[0] for k in embs}
    json.dump({'p': p, 'kt': T.KT, 'cap_em': T.CAP_EM, 'fills': C.FILLS, 'lap': [C.LAP_W, C.LAP_HP, C.LAP_HS],
               'nstep': C.NSTEP, 'cell': C.CELL, 'clip_rgb': C.CLIP_RGB, 'scenes': {sc: dump(built[sc], rev) for sc in C.SCENES + [C.BANNER]},
               'hidden': hidden, 'embs': embs},
              open(os.path.join(a.work, 'cards_scene.json'), 'w'))
    json.dump({'info': info, 'nodes': nnodes, 'bindings': [list(b) for b in binds], 'sizes': sizes,
               'template': [len(tower_tmpl), len(tmpl)], 'vm_names_checked': nv},
              open(os.path.join(a.work, 'cards_info.json'), 'w'), indent=1)
    for sc in C.SCENES + [C.BANNER]:
        open(os.path.join(a.work, sc.split('/')[-1]), 'wb').write(built[sc])
    open(os.path.join(a.work, 'hud_dynamic_templates.ui'), 'wb').write(tmpl)
    print(f'cards: {len(C.SCENES)} scenes, {sum(len(s) for s in hidden.values())} elements hidden by default, '
          f'{len(embs)} material bindings, {len(C.FILLS)} fills; template {len(tower_tmpl)} -> {len(tmpl)} bytes, '
          f'{nnodes} nodes, {len(binds)} DLL leaves bound; {nv} view-model names, no shared djb2 hash')
    for f, sz in sizes.items():
        print(f'  {f}: {len(arch[f].res)} resources, {sz} bytes -> {len(FILES[f])} archives')


if __name__ == '__main__':
    main()
