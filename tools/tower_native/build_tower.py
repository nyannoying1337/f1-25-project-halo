"""Build the game-native timing tower archives for the addon (Phase 2).

usage: python -I build_tower.py <stock folder> <tower sprites dir> <addon dir> <work dir>
                                [--replay-stock <folder> | --no-replay]
                                [--tower-leaves <tower_leaves.txt>] [--debug-dropzone]

<stock folder>       a folder of STOCK archive copies (2025_asset_groups/ui_package/…), never a game folder Swofty built
<tower sprites dir>  export_sprites.py's output (sprites.npz, sprites.json)
<addon dir>          the addon: reads erp/halo_template.erp, erp/halo.json, docs/timing-tower/leaves.md
--replay-stock       the folder of the replay screen's STOCK archive copies (flow_replay.erp,
                     screens/replays_and_highlights.erp, flow_frontend.erp); default: <stock folder>. Each must hold
                     the screen's resources with this game build's stock index hashes (REPLAY_MD5)
--no-replay          build the HUD tower only (no tower_replay*.erp, no replay ops; removes old replay archives)
--tower-leaves       the DLL's tower leaf list (sh native/tests/run_tests.sh <out> -> <out>/tower_leaves.txt): every
                     bound hud_tt_ leaf must be in it with the same type
--debug-dropzone     also bind the game's #session.dropzone (int32, si32) in the validation-log view. Off by default:
                     a binding exists even while hidden, and a wrong type crashes the game when the HUD is created

Writes
  erp/tower_scene.erp     flow_race, flow_options, persistent: the stacked table (+ tt_host), the bottom cap (+ the
                          tower, whose rows reference the game's own team logo unit and whose header references the
                          game's own lap counter logo unit: nothing of either is copied), the
                          table's .uipre (HUD editor preview), the tower's textures, materials, bindings,
                          and the Race Control banner: the top-centre toast's 12 scenes restyled (banner_native.py)
                          plus static nodes in the toast template that hide the banner's decorations
  erp/tower_template.erp  flow_race, flow_options: hud_dynamic_templates.ui = the halo's template (as in
                          erp/halo_template.erp) + the tower's nodes. Its op comes after the halo's and wins, so
                          RERUN THIS AFTER EVERY HALO BUILD (build_native.py rewrites halo.json with the halo ops only)
  erp/tower_replay.erp    flow_replay, screens/replays_and_highlights: the replay screen (round 5,
                          docs/timing-tower/replay-hud.md 6): replays_and_highlights.ui + the tower's nodes, and
                          replay_highlights.idf + tt_host (a third bottom cap instance at the board's top-left)
  erp/tower_replay_scene.erp  flow_frontend: the same replay_highlights.idf (that archive has no copy of the .ui)
  erp/tower_spectator.erp flow_race, screens/hud_spectator_2: the spectator screen (docs/spectator-ui.md 10.3):
                          hud_spectator_2.ui = the halo's (as in erp/halo_spectator.erp) + the tower's nodes, and
                          spec_driver_position_table.idf + tt_host (a fourth bottom cap instance at the board's
                          top-left). spectator_mode_2.idf stays stock (kizi.spectator-hud replaces it)
  erp/halo.json           the halo's three ops, then these five (three without the replay)
  <work>/                 tower_info.json (bindings of all three templates; tools/tower_re/check_tower_leaves.py reads it),
                          preview.json, tower_scene.json (for the simulator), banner_info.json and the built files
"""
import argparse
import hashlib
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tower_native as T  # noqa: E402  (sets up the native/ and SWOFTY_TOOLS paths)
import tower_resources as TR  # noqa: E402
import banner_native as BN  # noqa: E402
import erpbuild as E  # noqa: E402
from build_native import read, index, MAT  # noqa: E402

I = T.I

UI = '2025_asset_groups/ui_package/'
SCENE_ERPS = [UI + 'flow_race.erp', UI + 'flow_options.erp', UI + 'persistent.erp']
TEMPLATE_ERPS = [UI + 'flow_race.erp', UI + 'flow_options.erp']
TEMPLATE = 'eaid://ui_package/templates/hud_dynamic_templates.ui'
HALO_SOURCES = ['erp/halo_scene.erp', 'erp/halo_template.erp', 'erp/halo_spectator.erp']
TOWER_OPS = [{'op': 'overlay', 'erps': SCENE_ERPS, 'source': 'erp/tower_scene.erp'},
             {'op': 'overlay', 'erps': TEMPLATE_ERPS, 'source': 'erp/tower_template.erp'}]
# the replay screen (round 5): the .ui and the scene in two archives, the scene alone in a third (index)
REPLAY_ERPS = [UI + 'flow_replay.erp', UI + 'screens/replays_and_highlights.erp']
REPLAY_SCENE_ERPS = [UI + 'flow_frontend.erp']
REPLAY_MD5 = {T.REPLAY_UI: 'e56a359e0263fcaa2afd89f9330779b0',      # index hash (md5 of the resource) of the stock
              T.REPLAY_SCENE: '2b4294dede0ef120f1808f7d454fbc4c'}   # copies, the same in every target archive
REPLAY_TYPES = {T.REPLAY_UI: 'UIDF', T.REPLAY_SCENE: 'UILayout'}
REPLAY_OPS = [{'op': 'overlay', 'erps': REPLAY_ERPS, 'source': 'erp/tower_replay.erp'},
              {'op': 'overlay', 'erps': REPLAY_SCENE_ERPS, 'source': 'erp/tower_replay_scene.erp'}]
REPLAY_FILES = ('tower_replay.erp', 'tower_replay_scene.erp')
# the spectator screen (docs/spectator-ui.md 10.3): its .ui and the board's table scene, both in these two archives
# (the bottom cap is not: the game takes it from flow_race/persistent, which tower_scene.erp overlays, as on the replay
# screen). The screen scene is read for the board's position only. Index hashes of this game build's stock copies
SPECT_ERPS = [UI + 'flow_race.erp', UI + 'screens/hud_spectator_2.erp']
SPECT_MD5 = {T.SPECT_UI: '727c52c7bf56d5cec3b20bbbdc1ea398', T.SPECT_TABLE: '8eb42afc944280d9e0f579014294157f',
             T.SPECT_SCREEN: 'fa9a482122a77b261805d457a9cde3e8'}
SPECT_TYPES = {T.SPECT_UI: 'UIDF', T.SPECT_TABLE: 'UILayout', T.SPECT_SCREEN: 'UILayout'}
SPECT_OPS = [{'op': 'overlay', 'erps': SPECT_ERPS, 'source': 'erp/tower_spectator.erp'}]
# the series logos the game picks from (round 6): the texture array behind "#overrides.osd.timing_tower.
# timing_tower_logos.<key>" (overrides.uidb: lc_f1_logo, lc_f2_logo, lc_f2_26_logo), in flow_race. Only its surface
# header is read (size and slice count), as for the F1 logo and the FIA badge
SERIES_ARRAY = 'eaid://ui_package/art/texture_arrays/overrides.uidb/overrides.osd.timing_tower.timing_tower_logos.texarray'


def surface_size(frags):
    h = struct.unpack_from('<10I', frags[0], 0)
    return h[3], h[4]


def replay_stock(folder):
    """the replay screen's .ui, scene and lap sting scene from the stock copies. In every target archive each resource
    the overlays replace must carry this game build's stock index hash (REPLAY_MD5), its type and one stored layout,
    so one overlay fits every target. -> ({name: fragments}, {archive: {name: index hash}})"""
    got, hashes, layouts = {}, {}, {}
    targets = [(arch, [T.REPLAY_UI, T.REPLAY_SCENE]) for arch in REPLAY_ERPS]
    targets += [(arch, [T.REPLAY_SCENE]) for arch in REPLAY_SCENE_ERPS]
    for arch, names in targets:
        path = os.path.join(folder, arch)
        if not os.path.isfile(path):
            raise SystemExit(f'{path}: no stock copy (pass --replay-stock <folder>, or --no-replay)')
        rows = {r[0]: r for r in index(path)[1] if r[0] in names}
        data = read(path, names)
        hashes[arch] = {}
        for n in names:
            name, typ, unk, frags, h = rows[n]
            if h.hex() != REPLAY_MD5[n]:
                raise SystemExit(f'{arch}: {n} has index hash {h.hex()}, the stock copy {REPLAY_MD5[n]}: not a stock '
                                 'archive (a modded copy, or another game build)')
            if hashlib.md5(b''.join(data[n])).hexdigest() != REPLAY_MD5[n]:
                raise SystemExit(f'{arch}: {n} does not match its own index hash')
            assert typ.rstrip(b'\0').decode() == REPLAY_TYPES[n], (arch, n, typ)
            lay = (unk, [(fr[0], fr[3], fr[4]) for fr in frags])
            assert layouts.setdefault(n, lay) == lay, (arch, n, 'stored differently')
            assert got.setdefault(n, data[n]) == data[n]
            hashes[arch][n] = h.hex()
    sting = read(os.path.join(folder, REPLAY_ERPS[0]), [T.REPLAY_STING_SCENE])
    got.update(sting)
    return got, hashes


def spect_stock(folder):
    """the spectator screen's .ui, table scene and screen scene from the stock copies: in both target archives each
    with this game build's stock index hash (SPECT_MD5), its type and one stored layout, so one overlay fits both.
    -> ({name: fragments}, {archive: {name: index hash}})"""
    got, hashes, layouts = {}, {}, {}
    names = list(SPECT_MD5)
    for arch in SPECT_ERPS:
        path = os.path.join(folder, arch)
        if not os.path.isfile(path):
            raise SystemExit(f'{path}: no stock copy (the spectator screen needs it)')
        rows = {r[0]: r for r in index(path)[1] if r[0] in names}
        data = read(path, names)
        hashes[arch] = {}
        for n in names:
            name, typ, unk, frags, h = rows[n]
            if h.hex() != SPECT_MD5[n]:
                raise SystemExit(f'{arch}: {n} has index hash {h.hex()}, the stock copy {SPECT_MD5[n]}: not a stock '
                                 'archive (a modded copy, or another game build)')
            if hashlib.md5(b''.join(data[n])).hexdigest() != SPECT_MD5[n]:
                raise SystemExit(f'{arch}: {n} does not match its own index hash')
            assert typ.rstrip(b'\0').decode() == SPECT_TYPES[n], (arch, n, typ)
            lay = (unk, [(fr[0], fr[3], fr[4]) for fr in frags])
            assert layouts.setdefault(n, lay) == lay, (arch, n, 'stored differently')
            assert got.setdefault(n, data[n]) == data[n]
            hashes[arch][n] = h.hex()
    return got, hashes


def logo_unit(arch, unit=T.LOGO):
    """{resource name: fragments} of every resource of a stock unit scene in an archive: the team logo unit (the
    tower's rows reference it) or the lap counter logo unit (the header's, round 6). Each must be in every archive the
    cap scene goes to, unchanged"""
    base = unit[:-len('.idf')]
    names = [r[0] for r in index(arch)[1] if r[0].startswith(base + '.')]
    must = [unit, I.material_binding(unit)]
    assert all(m in names for m in must), (arch, 'no stock unit', unit)
    return read(arch, names)


def scene_json(T_, cap_bytes, root_name=T.ROOT):
    """a tower subtree of the built cap scene (tt_root, or the editor's copy tp_root), for the simulator
    (tools/tower_native/tower_sim.js)"""
    I = T.I
    idf = I.Idf(cap_bytes)
    root = None
    for e, _ in idf.scenes[0].root.walk():
        if e.name == root_name:
            root = e
            break
    embs = {v: k for k, v in T_.B.embs.items()}

    def node(e):
        o = e.obj
        d = {'name': e.name, 'type': e.type, 'pos': list(o['position'].value[:3]), 'scale': list(o['scale'].value[:3]),
             'hidden': bool(I.get_param(o, 'isHidden')), 'kids': [node(c) for c in e.children]}
        if e.type == 'eNull' and e.geoms:
            d['type'] = 'quad'
            d['sprite'] = embs[e.geoms[0]['materialid']]
            d['w'], d['h'] = T_.B.mesh_w * d['scale'][0], T_.B.mesh_h * d['scale'][2]
            d['layer'] = I.get_param(o, 'eLayer.layer')
        elif e.type == 'eText':
            d.update(style=I.get_param(o, 'style'), halign=I.get_param(o, 'halign'), box=I.get_param(o, 'boxWidth'),
                     wrapping=I.get_param(o, 'wrapping'), textcase=I.get_param(o, 'textcase'))
        elif e.type == 'eXRef' and e.name in (T.SERIES_EL, T.TRIAL_SERIES_EL):
            # the series logo (round 6; also the Time Trial board's): the lap counter logo unit's quad as drawn
            # (centre and size in this frame), a placeholder in the simulator (never the game's logo)
            s = d['scale'][0]
            left, top, qw, qh = T_.B.series_q
            d.update(type='quad', sprite='series_logo', scale=[1.0, 1.0, 1.0], layer=T_.B.series_layer,
                     pos=[d['pos'][0] + s * (left + qw / 2), d['pos'][1] + s * (top - qh / 2), 0.0], w=s * qw, h=s * qh)
        elif e.type == 'eXRef':
            # a team logo (or, on the Time Trial board, a tyre icon: the same stock unit): the unit's square quad as
            # drawn (centre and side in this frame), a placeholder in the simulator (never the game's texture)
            s = d['scale'][0]
            cx, cy = T_.B.logo_c
            sprite = 'tyre_icon' if e.name.startswith('tt_q') and e.name.endswith('_tc') else 'team_logo'
            d.update(type='quad', sprite=sprite, scale=[1.0, 1.0, 1.0], layer=T_.B.logo_layer,
                     pos=[d['pos'][0] + s * cx, d['pos'][1] + s * cy, 0.0], w=s * T_.B.logo_side, h=s * T_.B.logo_side)
        elif e.type == 'eStacker':
            d.update(stackerType=I.get_param(o, 'stackerType'), gap=I.get_param(o, 'gap'))
        return d

    return node(root)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('stock')
    ap.add_argument('sprites')
    ap.add_argument('addon')
    ap.add_argument('work')
    ap.add_argument('--replay-stock')
    ap.add_argument('--no-replay', action='store_true')
    ap.add_argument('--tower-leaves')
    ap.add_argument('--debug-dropzone', action='store_true')
    a = ap.parse_args()
    if a.no_replay and a.replay_stock:
        raise SystemExit('--replay-stock and --no-replay: pick one')
    os.makedirs(a.work, exist_ok=True)
    # the replay screen's stock copies first: a wrong copy stops the build before anything is written
    if not a.no_replay:
        rstock, rhashes = replay_stock(a.replay_stock or a.stock)
    sstock, shashes = spect_stock(a.stock)

    # the halo must be built first: its ops in halo.json, its template in halo_template.erp
    ops_path = os.path.join(a.addon, 'erp', 'halo.json')
    ops = json.load(open(ops_path))
    halo_ops = [o for o in ops['ops'] if not o['source'].startswith('erp/tower_')]
    if [o['source'] for o in halo_ops] != HALO_SOURCES:
        raise SystemExit(f'{ops_path}: expected the halo ops {HALO_SOURCES}, found {[o["source"] for o in halo_ops]}')
    halo_tmpl = E.read_all(os.path.join(a.addon, 'erp', 'halo_template.erp'))[TEMPLATE][1][0]
    halo_spect = E.read_all(os.path.join(a.addon, 'erp', 'halo_spectator.erp'))[T.SPECT_UI][1][0]

    contract = T.contract_types(os.path.join(a.addon, 'docs', 'timing-tower', 'leaves.md'))
    meta = json.load(open(os.path.join(a.sprites, 'sprites.json')))
    if 'bar' not in meta['G'] or 'barBadgeX' not in meta['G']:
        raise SystemExit(f'{a.sprites}: sprites.json has no G.bar / G.barBadgeX (the team-colour bar, round 4): '
                         're-export the sprites from the current tools/tower/tower.js (export_sprites.py)')
    z = np.load(os.path.join(a.sprites, 'sprites.npz'))
    sprites = {n: {'img': z[n]} for n in z.files}
    sprites.update(TR.solid_images(meta['P']))

    race = os.path.join(a.stock, SCENE_ERPS[0])
    scenes = [T.STACKED, T.STACKED_UIPRE, T.CAP]
    gtex = list(TR.GAME_TEX.values())
    stock = read(race, scenes + [T.DIAL, T.LAPC, T.ROW, TEMPLATE, MAT] + [t + '.image' for t in gtex])
    # the team logo unit the tower's rows reference (round 3): every one of its resources (scene, clips, mesh,
    # material binding) in every archive that carries the cap scene, the same bytes as in flow_race
    unit = logo_unit(race)
    # the lap counter logo unit the header references (round 6): the same check
    cat = logo_unit(race, T.CAT_LOGO)
    for arch in SCENE_ERPS[1:]:
        other = read(os.path.join(a.stock, arch), scenes + [t + '.image' for t in gtex] + gtex + [MAT])
        for n in scenes:
            assert other[n] == stock[n], f'{arch} carries a different {n}'
        assert logo_unit(os.path.join(a.stock, arch)) == unit, f'{arch} carries a different team logo unit'
        assert logo_unit(os.path.join(a.stock, arch), T.CAT_LOGO) == cat, f'{arch} carries a different lap counter logo unit'
    assert read(os.path.join(a.stock, TEMPLATE_ERPS[1]), [TEMPLATE])[TEMPLATE] == stock[TEMPLATE]
    for key, tex in TR.GAME_TEX.items():
        T.GAME_SIZE[key] = surface_size(stock[tex + '.image'])
    T.BADGE_TAG = T.stock_badge_tag(stock[TEMPLATE][0])
    # the series logo (round 6): the leaf's view model path (the stock HUD layouts), the stock lap counter's tag, and
    # the logos the game picks from: one shape, the F1 logo's (so the F2 logo fills the F1 logo's box)
    layouts = T.check_hud_layouts(read(os.path.join(a.stock, SCENE_ERPS[2]), [T.HUD_LAYOUTS])[T.HUD_LAYOUTS][0])
    T.SERIES_TAG = T.stock_series_tag(stock[TEMPLATE][0])
    arr = read(race, [SERIES_ARRAY + '.image', SERIES_ARRAY])
    arr_hdr = struct.unpack_from('<10I', arr[SERIES_ARRAY + '.image'][0], 0)
    arr_size, arr_n = surface_size(arr[SERIES_ARRAY + '.image']), arr_hdr[7]
    if arr_size != T.GAME_SIZE['g_f1'] or arr_n != 3:
        raise SystemExit(f'{SERIES_ARRAY}: {arr_size} x {arr_n}, expected 3 logos of the F1 logo\'s size '
                         f'{T.GAME_SIZE["g_f1"]}')
    for nm in ('badge', 'bdg'):
        if T.leaf(f'r00_{nm}') not in contract:
            raise SystemExit(f'leaves.md has no rNN_{nm}: the team logos need the DLL contract v{T.CONTRACT_VERSION}')

    # the Race Control banner: the toast's scenes and its fill meshes, the same in all three archives
    fills = BN.fill_meshes()
    bn_names = BN.SCENES + [m for _, _, m, _ in fills] + [BN.RC_TEXT_CLIP]
    bn_stock = read(race, bn_names)
    for arch in SCENE_ERPS[1:]:
        other = read(os.path.join(a.stock, arch), bn_names)
        for n in bn_names:
            assert other[n] == bn_stock[n], f'{arch} carries a different {n}'
    assert 'bn_m' in sprites, 'the banner needs the bn_m sprite (export_sprites.py)'
    banner, bn_info = BN.build_banner({n: bn_stock[n][0] for n in BN.SCENES}, bn_stock, TR.BANNER_EMB,
                                      meta['G']['banner'])
    rc_clip = BN.label_clip(bn_stock[BN.RC_TEXT_CLIP])     # the RACE CONTROL label in white (banner_native.py)
    bn_info['race_control']['label_rgb'] = list(BN.RC_LABEL_RGB)

    res, embs = TR.tower_resources(sprites, stock[MAT][0], os.path.join(a.work, 'bc7_cache'))
    cap, tw, tpv = T.build_cap(stock[T.CAP][0], stock[T.DIAL][0], stock[T.LAPC][0], stock[T.STACKED][0], embs, meta,
                               stock[T.ROW][0], unit[T.LOGO][0], cat[T.CAT_LOGO][0], a.debug_dropzone)
    stacked = T.build_stacked(stock[T.STACKED][0])
    pv_texts = tpv.pv_texts
    uipre, nset = T.build_uipre(stock[T.STACKED_UIPRE][0], pv_texts)
    nlapc = T.check_lap_counter(stock[T.LAPC][0], stock[TEMPLATE][0])
    template, nnodes, bindings = T.build_template(halo_tmpl, stock[TEMPLATE][0], tw, contract)
    hud_growth = len(template) - len(halo_tmpl)
    # the banner's decorations: static hide nodes in the toast template (round 2: isHidden alone did not hold)
    template, nhide = BN.toast_hides(template, bn_stock[BN.MS][0])
    bn_info['toast_hide_nodes'] = nhide

    # the replay screen (round 5): the same tower nodes in the replay template, tt_host in the replay scene
    rbindings, rinfo = [], None
    if not a.no_replay:
        rscene, rsinfo = T.build_replay_scene(rstock[T.REPLAY_SCENE][0])
        sting = T.sting_layers(rstock[T.REPLAY_STING_SCENE][0])
        rui, rinfo, rbindings = T.build_replay_template(rstock[T.REPLAY_UI][0], stock[TEMPLATE][0], tw, contract)
        replay_growth = len(rui) - len(rstock[T.REPLAY_UI][0])
        # the brief's stop rule: the replay's tower may not come out more than twice the HUD's
        if rinfo['nodes'] > 2 * nnodes or replay_growth > 2 * hud_growth:
            raise SystemExit(f'replay template: {rinfo["nodes"]} nodes, +{replay_growth} bytes; the HUD tower: '
                             f'{nnodes} nodes, +{hud_growth} bytes. More than twice: stopped')
        rinfo.update(scene=rsinfo, sting_layers=sting, stock_hashes=rhashes, growth=replay_growth,
                     hud_nodes=nnodes, hud_growth=hud_growth)

    # the spectator screen (docs/spectator-ui.md 10.3): the same tower nodes in the halo's spectator template, tt_host
    # in the board's table scene
    sscene, ssinfo = T.build_spectator_scene(sstock[T.SPECT_TABLE][0], sstock[T.SPECT_SCREEN][0])
    sui, sinfo, sbindings = T.build_spectator_template(halo_spect, sstock[T.SPECT_UI][0], stock[TEMPLATE][0], tw,
                                                       contract)
    spect_growth = len(sui) - len(halo_spect)
    # the replay's stop rule, here too: not more than twice the HUD's tower
    if sinfo['nodes'] > 2 * nnodes or spect_growth > 2 * hud_growth:
        raise SystemExit(f'spectator template: {sinfo["nodes"]} nodes, +{spect_growth} bytes; the HUD tower: '
                         f'{nnodes} nodes, +{hud_growth} bytes. More than twice: stopped')
    sinfo.update(scene=ssinfo, stock_hashes=shashes, growth=spect_growth, hud_nodes=nnodes, hud_growth=hud_growth)

    # cross-check against the DLL's own leaf list
    if a.tower_leaves:
        dll = T.dll_leaves(a.tower_leaves)
        bad = [f'{db} {t}: the DLL writes {dll.get(db, "nothing")}' for db, t in bindings + rbindings + sbindings
               if db.startswith(T.VM) and dll.get(db) != t]
        if bad:
            raise SystemExit('bindings vs tower_leaves.txt:\n  ' + '\n  '.join(bad))
        diff = sorted(k for k in set(dll) ^ set(contract))
        if diff:
            raise SystemExit(f'leaves.md and tower_leaves.txt differ: {diff[:8]}')
        print(f'DLL leaf list: {len(dll)} leaves, every bound tower leaf in it with the same type')

    erp_dir = os.path.join(a.addon, 'erp')
    sa = E.Archive(race)
    sa.add(T.STACKED, 'UILayout', [stacked])
    sa.add(T.CAP, 'UILayout', [cap])
    sa.add(T.STACKED_UIPRE, 'UIPR', [uipre])
    for n in BN.SCENES:
        sa.add(n, 'UILayout', [banner[n]])
    sa.add(BN.RC_TEXT_CLIP, 'AnimClip', rc_clip)
    for n, t, fr in res + TR.banner_resources(BN.SLOTS):
        sa.add(n, t, fr)
    scene_erp = os.path.join(erp_dir, 'tower_scene.erp')
    size1 = sa.write(scene_erp)
    ta = E.Archive(race)
    ta.add(TEMPLATE, 'UIDF', [template])
    tmpl_erp = os.path.join(erp_dir, 'tower_template.erp')
    size2 = ta.write(tmpl_erp)
    replay_erps = [os.path.join(erp_dir, f) for f in REPLAY_FILES]
    if a.no_replay:
        for f in replay_erps:
            if os.path.exists(f):
                os.remove(f)
                print(f'removed {f} (--no-replay)')
    else:
        # each overlay copies the stored layout of the archive it replaces (the same in all targets: replay_stock)
        rs = a.replay_stock or a.stock
        ra = E.Archive(os.path.join(rs, REPLAY_ERPS[0]))
        ra.add(T.REPLAY_UI, 'UIDF', [rui])
        ra.add(T.REPLAY_SCENE, 'UILayout', [rscene])
        size3 = ra.write(replay_erps[0])
        rf = E.Archive(os.path.join(rs, REPLAY_SCENE_ERPS[0]))
        rf.add(T.REPLAY_SCENE, 'UILayout', [rscene])
        size4 = rf.write(replay_erps[1])
    # the spectator screen: one archive for both targets (spect_stock: the same stored layouts)
    sp = E.Archive(os.path.join(a.stock, SPECT_ERPS[0]))
    sp.add(T.SPECT_UI, 'UIDF', [sui])
    sp.add(T.SPECT_TABLE, 'UILayout', [sscene])
    spect_erp = os.path.join(erp_dir, 'tower_spectator.erp')
    size5 = sp.write(spect_erp)
    new_ops = TOWER_OPS + ([] if a.no_replay else REPLAY_OPS) + SPECT_OPS
    json.dump({'schema_version': ops['schema_version'], 'ops': halo_ops + new_ops}, open(ops_path, 'w'), indent=2)

    # read everything back
    back = E.read_all(scene_erp)
    assert back[T.STACKED][1][0] == stacked and back[T.CAP][1][0] == cap and back[T.STACKED_UIPRE][1][0] == uipre
    assert all(back[n][1][0] == banner[n] for n in BN.SCENES)
    assert list(back[BN.RC_TEXT_CLIP][1]) == rc_clip
    assert len(back) == len(sa.res)
    assert E.read_all(tmpl_erp)[TEMPLATE][1][0] == template
    assert E.read_all(os.path.join(erp_dir, 'halo_template.erp'))[TEMPLATE][1][0] == halo_tmpl
    if not a.no_replay:
        rb = E.read_all(replay_erps[0])
        assert set(rb) == {T.REPLAY_UI, T.REPLAY_SCENE} and rb[T.REPLAY_UI][1] == [rui] and rb[T.REPLAY_SCENE][1] == [rscene]
        rb = E.read_all(replay_erps[1])
        assert set(rb) == {T.REPLAY_SCENE} and rb[T.REPLAY_SCENE][1] == [rscene]
    sb = E.read_all(spect_erp)
    assert set(sb) == {T.SPECT_UI, T.SPECT_TABLE} and sb[T.SPECT_UI][1] == [sui] and sb[T.SPECT_TABLE][1] == [sscene]
    assert E.read_all(os.path.join(erp_dir, 'halo_spectator.erp'))[T.SPECT_UI][1][0] == halo_spect
    assert [o['source'] for o in json.load(open(ops_path))['ops']] == HALO_SOURCES + [o['source'] for o in new_ops]

    for name, data in (('driver_position_table_stacked.idf', stacked), ('driver_position_bottom_cap.idf', cap),
                       ('driver_position_table_stacked.uipre', uipre), ('hud_dynamic_templates.ui', template)):
        open(os.path.join(a.work, name), 'wb').write(data)
    if not a.no_replay:
        os.makedirs(os.path.join(a.work, 'replay'), exist_ok=True)
        for name, data in (('replays_and_highlights.ui', rui), ('replay_highlights.idf', rscene)):
            open(os.path.join(a.work, 'replay', name), 'wb').write(data)
        json.dump(rinfo, open(os.path.join(a.work, 'replay', 'replay_info.json'), 'w'), indent=1)
    os.makedirs(os.path.join(a.work, 'spectator'), exist_ok=True)
    for name, data in (('hud_spectator_2.ui', sui), ('spec_driver_position_table.idf', sscene)):
        open(os.path.join(a.work, 'spectator', name), 'wb').write(data)
    json.dump(sinfo, open(os.path.join(a.work, 'spectator', 'spectator_info.json'), 'w'), indent=1)
    os.makedirs(os.path.join(a.work, 'banner'), exist_ok=True)
    for n in BN.SCENES:
        open(os.path.join(a.work, 'banner', n.split('/')[-1]), 'wb').write(banner[n])
    json.dump(bn_info, open(os.path.join(a.work, 'banner_info.json'), 'w'), indent=1)
    json.dump({'contract': T.CONTRACT_VERSION, 'bindings': [list(b) for b in bindings + rbindings + sbindings],
               'hud_bindings': len(bindings), 'replay_bindings': len(rbindings),
               'spectator_bindings': len(sbindings), 'recs': tw.recs,
               'trial_recs': tw.trecs, 'trial': tw.trial_info,
               'debug_dropzone': a.debug_dropzone}, open(os.path.join(a.work, 'tower_info.json'), 'w'), indent=1)
    json.dump({'on': tw.pv_on, 'texts': tw.pv_text, 'uipre_texts': pv_texts},
              open(os.path.join(a.work, 'preview.json'), 'w'), indent=1)
    json.dump({'root': scene_json(tw, cap), 'preview_root': scene_json(tpv, cap, T.PV_ROOT),
               'preview_texts': pv_texts, 'G': meta['G'], 'P': meta['P'], 'game_size': T.GAME_SIZE,
               'recs': tw.recs, 'trial_recs': tw.trecs, 'kt': T.KT, 'cap_em': T.CAP_EM, 'bar_default': T.BAR_DEFAULT},
              open(os.path.join(a.work, 'tower_scene.json'), 'w'))
    nleaf = len({db for db, _ in bindings if db.startswith(T.VM)})
    npv = sum(1 for nm in tw.B.names if nm.startswith('tp_'))
    print(f'bottom cap {len(stock[T.CAP][0])} -> {len(cap)} bytes, {len(tw.B.names)} new elements '
          f'({len(tw.B.names) - npv} live tower, {npv} HUD editor copy)')
    print(f'stacked table {len(stock[T.STACKED][0])} -> {len(stacked)} bytes (+ {T.HOST}); '
          f'uipre {len(stock[T.STACKED_UIPRE][0])} -> {len(uipre)} bytes, {nset} new preview elements')
    print(f'template {len(halo_tmpl)} -> {len(template)} bytes, {nnodes} tower nodes, {len(bindings)} bindings '
          f'({nleaf} DLL leaves), every type checked; lap counter: {nlapc} parts hidden while hud_tt_show')
    nlogo = sum(1 for r in tw.recs if r.get('tex') and r['tex'][0] != T.SERIES)
    print(f'team logos: {nlogo} references of the stock logo unit, {meta["G"]["badgeH"]:.2f} HUD units square '
          f'(stock pill: {tw.B.logo_side / T.KT:.2f}), textureOverride bound as {T.BADGE_TAG} (the stock pill\'s tag), '
          f'centred at {meta["G"]["barBadgeX"]:.2f}')
    ser = [r for r in tw.recs if r.get('tex') and r['tex'][0] == T.SERIES]
    sq = tw.B.series_q
    sx = [x for x, _ in I.Idf(cap).scenes[0].root.walk() if x.name == T.SERIES_EL][0]
    print(f'series logo: {len(ser)} reference of the stock lap counter logo unit ({sq[2]:.2f} x {sq[3]:.2f} at scale '
          f'{sx.scale[0]:.4f}: {sq[2] * sx.scale[0] / T.KT:.2f} x {sq[3] * sx.scale[0] / T.KT:.2f} HUD units, layer '
          f'{tw.B.series_layer}); textureOverride bound as {T.SERIES_TAG} (the stock lap counter\'s tag) to '
          f'{T.HUD_SERIES} on the HUD (hud_lap_counter is nameId "{layouts["hud_lap_counter"]}") and '
          f'{T.REPLAY_SERIES} on the replay screen; default {T.SERIES_DEFAULT}; the game\'s logos: {arr_n} of '
          f'{arr_size[0]} x {arr_size[1]} px')
    bars = [r for r in tw.recs if r.get('col')]
    bar = meta['G']['bar']
    print(f'team-colour bars: {len(bars)} quads ({bar["w"]:.2f} x {bar["h"]:.2f} HUD units at {bar["x"]:.2f}), each in '
          f'its code\'s rNN_cVV null; colourOverride bound as {sorted({r["col"][1] for r in bars})}')
    ti = tw.trial_info
    tb = [db for db, _ in bindings if db.startswith(T.LAPTIMES_VM) or db.startswith(T.LAPC_VM) or db.startswith('#ui_menu')]
    tcount = sum(1 for x, _ in I.Idf(cap).scenes[0].root.walk() if x.path.startswith(f'{T.ROOT}.{T.TRIAL_ROOT}'))
    print(f'Time Trial board: tt_trial ({tcount} elements), {ti["nodes"]} template nodes, {len(tw.trecs)} recs, {ti["decisions"]} decision nodes '
          f'({ti["signals"]} signals) on {", ".join(ti["values"][:2])}, ...; {len(tb)} bindings to the game\'s board, lap '
          f'counter and HUD menu values, each with the stock tag; host, mask and lap counter on hud_tt_show')
    print(f'banner: {len(BN.SCENES)} toast scenes restyled (scale {BN.S:.4f}, {len(BN.SLOTS)} fill slots -> bn_m, '
          f'{len(BN.TWIN)} clip-free fill twins, {nhide} toast template hide nodes in {len(BN.TOASTS)} instances)')
    if not a.no_replay:
        rs_ = rinfo['scene']
        print(f'replay scene {len(rstock[T.REPLAY_SCENE][0])} -> {len(rscene)} bytes: + {T.HOST} (bottom cap reference) '
              f'at {rs_["position"][:2]}, scale {rs_["scale"][0]:.2f}; {rs_["elements"]} elements, '
              f'{rs_["lookup"]} lookup ids')
        print(f'replay template {len(rstock[T.REPLAY_UI][0])} -> {len(rui)} bytes (+{replay_growth}; the HUD tower '
              f'+{hud_growth}): {rinfo["nodes"]} nodes ({rinfo["tower_nodes"]} under tt_host_n), {len(rbindings)} '
              f'bindings ({rinfo["dll_leaves"]} DLL leaves; screen view model: {", ".join(rinfo["replay_vm"])}), '
              f'every type checked; no stock visible on the hidden or shown parts ({rinfo["stock_visible_nodes"]} '
              f'stock visible nodes)')
        print(f'lap sting layers {sting}: between the tower\'s logos ({T.LAYER["bar"]}) and texts ({T.LAYER["text"]}), '
              f'so {T.REPLAY_STING_NODE} hides the tower while it plays')
        for arch, hs in rhashes.items():
            print(f'  stock {arch}: ' + ', '.join(f'{n.split("/")[-1]} {h[:16]}' for n, h in hs.items()))
        print(f'{replay_erps[0]}: {size3} bytes')
        print(f'{replay_erps[1]}: {size4} bytes')
    ss_ = sinfo['scene']
    print(f'spectator table scene {len(sstock[T.SPECT_TABLE][0])} -> {len(sscene)} bytes: + {T.HOST} (bottom cap '
          f'reference) at {ss_["local"][:2]} in the table, {ss_["world"]} on screen, scale {ss_["scale"][0]:.2f}; '
          f'{ss_["elements"]} elements, {ss_["lookup"]} lookup ids; spectator_mode_2.idf not written')
    print(f'spectator template {len(halo_spect)} -> {len(sui)} bytes (+{spect_growth}): {sinfo["nodes"]} nodes '
          f'({sinfo["tower_nodes"]} under tt_host_n), {len(sbindings)} bindings ({sinfo["dll_leaves"]} DLL leaves; '
          f'screen view model: {", ".join(sinfo["screen_vm"])}), every type checked; no stock visible on the hidden '
          f'or shown parts ({sinfo["stock_visible_nodes"]} stock visible nodes)')
    for arch, hs in shashes.items():
        print(f'  stock {arch}: ' + ', '.join(f'{n.split("/")[-1]} {h[:16]}' for n, h in hs.items()))
    print(f'{spect_erp}: {size5} bytes')
    print(f'{scene_erp}: {len(sa.res)} resources, {size1} bytes')
    print(f'{tmpl_erp}: {size2} bytes')
    print(f'{ops_path}: {len(halo_ops)} halo ops + {len(new_ops)} tower ops')


if __name__ == '__main__':
    main()
