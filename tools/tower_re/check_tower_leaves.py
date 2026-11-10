"""Check a timing-tower template against the DLL's tower leaves (docs/timing-tower/leaves.md section 6).

A template binding whose type differs from the leaf's type crashes the game, so every bound view_model_data.hud_tt_*
leaf must exist in the DLL's list and carry the same type tag:
  visibility binding -> bool, text binding -> the binding's own tag (stri by default), fraction binding (fp32) -> none
  (the DLL writes no float leaf).

usage: python -I check_tower_leaves.py <tower_leaves.txt> <info.json>
       python -I check_tower_leaves.py --self-test

tower_leaves.txt: written by `sh native/tests/run_tests.sh <out>`, one `path tag` per line.
info.json: the halo builder's format ('vis', 'texts', 'xas' lists, tools/native/halo_native.py) or
{"bindings": [[dbentry, tag], ...]} for any other builder.
"""
import json
import os
import sys
import tempfile

TOWER = 'view_model_data.hud_tt_'


def load_leaves(path):
    leaves = {}
    for line in open(path, encoding='utf-8'):
        parts = line.split()
        if len(parts) == 2:
            leaves[parts[0].lstrip('#')] = parts[1]
    return leaves


def bindings(info):
    """(dbentry, tag, where) for every binding in the builder's info."""
    out = []
    for row in info.get('vis', []):
        nm, _el, db = row[0], row[1], row[2]
        out.append((db, 'bool', f'{nm}.visible'))
    for row in info.get('texts', []):
        nm, _el, text_db, vis_db = row[0], row[1], row[2], row[3]
        vtype = row[6] if len(row) > 6 and row[6] else 'stri'
        if text_db:
            out.append((text_db, vtype, f'{nm}.text'))
        if vis_db:
            out.append((vis_db, 'bool', f'{nm}.visible'))
    for row in info.get('xas', []):
        nm, _el, db = row[0], row[1], row[2]
        out.append((db, 'fp32', f'{nm}.fraction'))
    for i, row in enumerate(info.get('bindings', [])):
        out.append((row[0], row[1], f'bindings[{i}]'))
    return out


def check(leaves, info, quiet=False):
    errors, bound = [], set()
    for db, tag, where in bindings(info):
        path = (db or '').lstrip('#')
        if not path.startswith(TOWER):
            continue
        bound.add(path)
        if path not in leaves:
            errors.append(f'{where}: {db} is not a DLL leaf (never written)')
        elif leaves[path] != tag:
            errors.append(f'{where}: {db} is bound as {tag} but the DLL writes {leaves[path]} (crashes the game)')
    if not quiet:
        print(f'template binds {len(bound)} tower leaves; the DLL writes {len(leaves)}')
        for e in errors:
            print('ERROR', e)
        if not errors:
            print('ok: every bound tower leaf exists with the same type')
    return errors


def self_test():
    leaves_txt = ('view_model_data.hud_tt_on bool\nview_model_data.hud_tt_r00_gap stri\n'
                  'view_model_data.hud_tt_rows si32\n')
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'tower_leaves.txt')
        open(p, 'w', encoding='utf-8').write(leaves_txt)
        leaves = load_leaves(p)
    good = {'vis': [['v_on', 'el', '#view_model_data.hud_tt_on', False, False]],
            'texts': [['t_gap', 'el', '#view_model_data.hud_tt_r00_gap', '#view_model_data.hud_tt_on', False, False],
                      ['t_laps', 'el', '#session.number_of_laps', None, False, False, 'ui32']],
            'bindings': [['#view_model_data.hud_tt_rows', 'si32']]}
    bad = {'texts': [['t_rows', 'el', '#view_model_data.hud_tt_rows', None, False, False]],   # stri on an int32
           'vis': [['v_x', 'el', '#view_model_data.hud_tt_sessna', False, False]],            # not written
           'xas': [['x_a', 'el', '#view_model_data.hud_tt_on']]}                               # fp32 on a bool
    assert check(leaves, good, quiet=True) == []
    errs = check(leaves, bad, quiet=True)
    assert len(errs) == 3, errs
    assert any('crashes' in e and 'hud_tt_rows' in e for e in errs)
    assert any('never written' in e for e in errs)
    print('self-test: 2 cases ok')


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test()
        return
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    errors = check(load_leaves(sys.argv[1]), json.load(open(sys.argv[2], encoding='utf-8')))
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
