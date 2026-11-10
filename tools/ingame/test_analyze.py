"""test_analyze.py <out-dir> [tower_sample.csv]: runs analyze_diag.py on the synthetic drive and on each broken variant of it
(make_synthetic_log.py --variant). The good drive must pass every check (Overtake has no data: it is a race); each
variant must fail the checks it breaks and leave every other verdict as the good drive has it. Every log comes with
the timing tower's companion log (<stem>.tower.csv); the tower_* variants break that one. Logs and reports are
written to <out-dir>. With tower_sample.csv (written by the C++ log writer in `sh native/tests/run_tests.sh <out>`),
the analyzer also reads that real-format tower log alone: its rows must match its reads ("Tower: shown values"). Exit
status 1 on any mismatch."""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, 'make_synthetic_log.py')
ANALYZE = os.path.join(HERE, 'analyze_diag.py')
NO_DATA_OK = {'Overtake (Overtake Mode active, +0x1a62)'}  # the synthetic drive is a race
TOWER = ('Tower: systems found', 'Tower: classification (results R)', 'Tower: gaps and intervals', 'Tower: tyres',
         'Tower: safety car', 'Tower: penalties', 'Tower: warnings', 'Tower: shown values', 'Tower: cost',
         'Tower: yellow flag', 'Tower: red flag', 'Tower: team badges')
FLAGS = ('Tower: yellow flag', 'Tower: red flag')
BADGES = 'Tower: team badges'
GMETER = ('G meter: value', 'G meter: segments', 'G meter: direction', 'G meter: red bar and flash')
# variant: (verdicts it must change, other checks it may also fail and why)
CASES = {
    # a pre-2026-11-09 log: the speed check falls back to the distance counter column alone; no meter columns
    'legacy': ({f: 'NO DATA' for f in GMETER}, {}),
    'speed_scale': ({'Speed': 'FAIL'}, {}),
    'speed_ref_frame': ({'Speed': 'FAIL'}, {}),
    'glong_sign': ({'Longitudinal g (G-meter)': 'FAIL'}, {}),
    'glat_axis': ({'Lateral g (G-meter)': 'FAIL'}, {
        'Turn position': 'the driven bends come from lateral g, as the halo learns them',
        'Turn arrow (direction)': 'the driven bends come from lateral g, as the halo learns them'}),
    'harvest_half': ({'Recharge (harvest power)': 'FAIL'}, {
        'Deploy (deploy power)': 'the balance no longer closes, whichever field is wrong'}),
    'deploy_zero': ({'Deploy (deploy power)': 'FAIL'}, {
        'Recharge (harvest power)': 'the balance no longer closes, whichever field is wrong'}),
    'boost_hud': ({'Boost (ERS mode 2)': 'FAIL', 'HUD = state': 'FAIL'}, {}),
    'arrow_inverted': ({'Turn arrow (direction)': 'FAIL'}, {
        'Turn position': 'apexes are found by the arrow\'s direction: with every arrow wrong, none is'}),
    'arrow_one_wrong': ({'Turn arrow (direction)': 'FAIL'}, {}),
    'turn_offset': ({'Turn position': 'FAIL'}, {}),
    'turn_learned': ({}, {}),  # judged on the list the halo moved to the corners after lap 0
    'two_tracks': ({}, {}),    # a 2025 car's stint at another track first: per-stint checks keep it apart
    'car_lost': ({'Player car (ControllerSystem)': 'FAIL'}, {}),
    'slot_reject': ({'Car table (identity)': 'FAIL', 'Player car (ControllerSystem)': 'FAIL'}, {}),
    # the G-force meter (an option, off by default)
    'gm_off': ({f: 'NO DATA' for f in GMETER}, {}),
    'gm_scale': ({'G meter: value': 'FAIL'}, {}),
    'gm_mirror': ({'G meter: direction': 'FAIL'}, {}),
    'gm_gap': ({'G meter: segments': 'FAIL'}, {}),
    'gm_red': ({'G meter: red bar and flash': 'FAIL'}, {}),
    'gm_flash': ({'G meter: red bar and flash': 'FAIL'}, {}),
    'gm_unavail': ({'G meter: value': 'FAIL'}, {}),
    # the timing tower's companion log
    'tower_absent': ({f: 'NO DATA' for f in TOWER}, {}),
    'tower_tyre_visual': ({'Tower: tyres': 'FAIL'}, {}),
    'tower_tyre_offpit': ({'Tower: tyres': 'FAIL'}, {}),
    'tower_gap_swap': ({'Tower: gaps and intervals': 'FAIL'}, {
        'Tower: classification (results R)': 'its independent check orders cars by the leader gaps, now the intervals'}),
    'tower_sorted': ({'Tower: classification (results R)': 'FAIL'}, {}),
    'tower_sc_flap': ({'Tower: safety car': 'FAIL'}, {}),
    'tower_pen_dt': ({'Tower: penalties': 'FAIL'}, {}),
    'tower_warn_drop': ({'Tower: warnings': 'FAIL'}, {}),
    'tower_shown_round': ({'Tower: shown values': 'FAIL'}, {}),
    'tower_cost': ({'Tower: cost': 'FAIL'}, {}),
    'tower_flag_pit': ({'Tower: gaps and intervals': 'FAIL'}, {}),
    'tower_restart': ({}, {}),   # a restart clears the game's penalty log: the counts start again, nothing fails
    'tower_pen_glitch': ({'Tower: penalties': 'FAIL', 'Tower: warnings': 'FAIL'}, {}),
    'tower_full': ({}, {}),      # the layout test-drive.md asks for
    # flags (leaves v3): the header must follow the zones and the red flag byte, 3 > 1 > 2 > 5, without flicker
    'tower_yellow_flicker': ({'Tower: yellow flag': 'FAIL'}, {}),
    'tower_red_as_sc': ({'Tower: red flag': 'FAIL'}, {}),   # the in-game bug of 2026-11-09 16:39
    'tower_noflags': ({f: 'NO DATA' for f in FLAGS}, {}),
    'tower_oldlog': ({f: 'NO DATA' for f in FLAGS + (BADGES,)}, {}),    # a log from before leaves v3
    # team badges (leaves v4): every running car has one, a car keeps its own, two cars at most per badge, rows
    # carry their own car's badge
    'tower_nobadges': ({BADGES: 'NO DATA'}, {}),            # a log from before leaves v4
    'tower_badge_missing': ({BADGES: 'FAIL'}, {}),
    'tower_badge_change': ({BADGES: 'FAIL'}, {}),
    'tower_badge_three': ({BADGES: 'FAIL'}, {}),
    'tower_badge_row': ({BADGES: 'FAIL'}, {}),
    # a save resumed mid-race (the 2026-11-09 15:32 log): the settle window keeps the replay out of the rate checks
    # and the tyre changes, so nothing fails
    'resume': ({}, {}),
}


def verdicts(path):
    out = {}
    for line in open(path, encoding='utf-8'):
        m = re.match(r'\| (.+?) \| \*\*(PASS|FAIL|NO DATA)\*\* \|', line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def run(out_dir, variant):
    csv_path = os.path.join(out_dir, f'synthetic_{variant}.csv')
    md_path = os.path.join(out_dir, f'synthetic_{variant}.md')
    subprocess.run([sys.executable, '-I', GEN, csv_path, '--variant', variant], check=True)
    subprocess.run([sys.executable, '-I', ANALYZE, csv_path, md_path], check=True, stdout=subprocess.DEVNULL)
    return verdicts(md_path)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    out_dir = sys.argv[1]
    os.makedirs(out_dir, exist_ok=True)
    bad = []
    good = run(out_dir, 'good')
    for field, v in good.items():
        if v != 'PASS' and not (v == 'NO DATA' and field in NO_DATA_OK):
            bad.append(f'good: {field} is {v}')
    print(f'good: {sum(v == "PASS" for v in good.values())} PASS, '
          f'{", ".join(f"{f} {v}" for f, v in good.items() if v != "PASS") or "nothing else"}')
    for variant, (must, may) in CASES.items():
        got = run(out_dir, variant)
        wrong = [f'{f} is {got.get(f)}, want {v}' for f, v in must.items() if got.get(f) != v]
        changed = [f'{f} {good.get(f)} -> {v}' for f, v in got.items()
                   if f not in must and f not in may and v != good.get(f)]
        changed += [f'{f} missing' for f in good if f not in got]
        status = 'ok' if not wrong and not changed else 'MISMATCH'
        extra = [f'{f} {got.get(f)}' for f in may if got.get(f) != good.get(f)]
        print(f'{variant}: {status}; ' + ', '.join(f'{f} {got.get(f)}' for f in must) +
              (f' (also {", ".join(extra)})' if extra else ''))
        bad += [f'{variant}: {x}' for x in wrong + changed]
    if bad:
        print('\n'.join(['FAILED:'] + bad))
        sys.exit(1)
    if len(sys.argv) > 2:   # the real writer's format (native/src/diag_log.cpp) on the fake game of the host tests
        md = os.path.join(out_dir, 'tower_sample.md')
        subprocess.run([sys.executable, '-I', ANALYZE, sys.argv[2], md], check=True, stdout=subprocess.DEVNULL)
        got = verdicts(md)
        want = {'Tower: systems found': 'PASS', 'Tower: shown values': 'PASS', 'Tower: tyres': 'PASS',
                'Tower: classification (results R)': 'PASS', 'Tower: cost': 'PASS', 'Tower: yellow flag': 'PASS',
                'Tower: red flag': 'PASS', BADGES: 'PASS'}
        wrong = [f'{f} is {got.get(f)}' for f, v in want.items() if got.get(f) != v]
        print(f'tower_sample (C++ writer): {"ok" if not wrong else "MISMATCH"}; ' +
              ', '.join(f'{f} {got.get(f)}' for f in want))
        if wrong:
            print('\n'.join(['FAILED:'] + [f'tower_sample: {x}' for x in wrong]))
            sys.exit(1)
    print(f'all {len(CASES) + 1 + (len(sys.argv) > 2)} cases as expected')


if __name__ == '__main__':
    main()
