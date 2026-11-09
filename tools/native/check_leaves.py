"""Check the template against the DLL: every view_model_data.hud_halo_* leaf the template binds must be one the DLL
writes, or the halo part bound to it never changes in game.

usage: python -I check_leaves.py <leaves.txt from tests/run_tests.sh> <info.json from build_native.py's work dir>
"""
import json
import sys

PREFIX = '#view_model_data.'


def main():
    written = {line.strip().lstrip('#')[len(PREFIX) - 1:] for line in open(sys.argv[1], encoding='utf-8') if line.strip()}
    info = json.load(open(sys.argv[2], encoding='utf-8'))
    bound = set()
    for _nm, _el, db, *_ in info['vis']:
        bound.add(db)
    for _nm, _el, text_db, vis_db, *_ in info['texts']:
        bound.update(x for x in (text_db, vis_db) if x)
    for _nm, _el, db in info['xas']:
        bound.add(db)
    halo = {b[len(PREFIX):] for b in bound if b.startswith(PREFIX + 'hud_halo_')}
    native = sorted(b for b in bound if not b.startswith(PREFIX + 'hud_halo_'))
    missing = sorted(halo - written)
    unused = sorted(written - halo)
    print(f'template binds {len(halo)} DLL leaves and {len(native)} game values; the DLL writes {len(written)} leaves')
    cars = [x for x in native if x.startswith('#session.cars.')]
    print('game values:', ', '.join(x for x in native if x not in cars),
          f'and {sum(1 for x in cars if x.endswith(".position"))} cars as #session.cars.car<vid>.(position, driver.second_name)')
    if unused:
        print('written but not bound (diagnostic only):', ', '.join(unused))
    if missing:
        print('BOUND BUT NEVER WRITTEN:', ', '.join(missing))
        sys.exit(1)
    print('ok: every bound leaf is written')


if __name__ == '__main__':
    main()
