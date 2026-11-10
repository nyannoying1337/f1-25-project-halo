"""analyze_diag.py <halo_*.csv | tower_*.csv> [report.md]

Turns an in-game validation log (written by the addon's "Validation log" option) into a per-field verification
report: every check below compares a value the provider read against another, independent in-game observation
(the game's own distance counter, the battery's rate of change, the car's motion, the steering in a corner, the
game's own record of who drives which car), so a wrong offset shows up as a failed check instead of a
plausible-looking number. Verdicts: PASS, FAIL, or NO DATA (the drive did not exercise that state; the report says
what to do). Logs written by older builds lack some columns: those checks are skipped.

The timing tower's companion log (tower_<same stamp>.csv, next to the halo's) is read automatically and adds the
"Tower: ..." rows (docs/timing-tower/field-traces.md §1-7 and §10, what the tower showed, its cost). Given a
tower_*.csv alone, only those rows are written.

The G-force meter (option, off by default) adds the "G meter: ..." rows: its value against the read g, and its
segment, direction, red bar and flash rules (docs/gmeter/design.md). They say NO DATA while the meter is off.
"""
import csv
import math
import os
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import unquote

import numpy as np

KMH = 3.6
RECORD_S = 1 / 30      # the log's record period (halo_hud.cpp kDiagPeriod)
STRIPES = 10           # throttle / brake slats (leaves.hpp kStripes)
LOST_MAX_S = 2.0       # longest tolerated loss: table churn while cars are created or destroyed lasts a few frames
SLOT_REJECT = 'uti?'   # vehicle-table slot statuses that are not a car (game_state_f1_25.hpp SlotStatus)


def text(v):
    """A text column as strings (the loader turns a column whose every value is numeric into floats)."""
    return np.array([str(int(x)) if isinstance(x, float) and math.isfinite(x) and x == int(x) else str(x) for x in v],
                    dtype=object)


def runs(mask):
    """Inclusive (first, last) index pairs of the True runs of a boolean array."""
    d = np.diff(np.concatenate(([0], np.asarray(mask, dtype=np.int8), [0])))
    return list(zip(np.nonzero(d == 1)[0].tolist(), (np.nonzero(d == -1)[0] - 1).tolist()))


def longest(mask, t):
    """(seconds, first index) of the longest True run; (0.0, None) without one."""
    return max(((float(t[b] - t[a]) + RECORD_S, a) for a, b in runs(mask)), default=(0.0, None))


def turn_key(label):
    """'9' -> (9, ''), '14a' -> (14, 'a'): the order of official turn labels."""
    m = re.fullmatch(r'(\d+)([a-z]?)', label)
    return (int(m.group(1)), m.group(2)) if m else None


def pct(x):
    return 'n/a' if x is None or math.isnan(x) else f'{100 * x:.0f}%'


def load(path):
    rows = []
    with open(path, newline='', encoding='utf-8', errors='replace') as f:
        r = csv.DictReader(line for line in f if not line.startswith('#'))
        for row in r:
            rows.append(row)
    if not rows:
        sys.exit('empty log')
    cols = {}
    for k in rows[0]:
        vals = [row[k] for row in rows]
        try:
            cols[k] = np.array([float(v) for v in vals])
        except ValueError:
            cols[k] = np.array(vals, dtype=object)
    return cols, len(rows)


class Report:
    def __init__(self):
        self.lines, self.table = [], []

    def verdict(self, field, verdict, evidence, todo=''):
        self.table.append((field, verdict, evidence, todo))

    def text(self, s=''):
        self.lines.append(s)

    def render(self, path, n, dur, run_s=None):
        span = f'{dur:.0f} s with the player car live' + (
            f', {run_s:.0f} s of it with the simulation advancing' if run_s is not None else '')
        out = ['# In-game validation report', '',
               f'Log: `{path}` — {n} records, {span}.', '',
               '| Field | Verdict | Evidence | To complete |', '|---|---|---|---|']
        for f, v, e, t in self.table:
            out.append(f'| {f} | **{v}** | {e} | {t} |')
        out += [''] + self.lines
        return '\n'.join(out) + '\n'


def corr(a, b):
    if len(a) < 10 or np.std(a) == 0 or np.std(b) == 0:
        return float('nan')
    return float(np.corrcoef(a, b)[0, 1])


# --- rates from a log whose records do not line up with the game's simulation steps
# The game steps its physics at 60 Hz; the log records at 30 Hz, stamped with the rendered frame's time, so a record
# interval holds 2 or 3 steps and a rate between two neighbouring records is off by up to a step (33 %). While the game
# is paused the log keeps recording the frozen state (one test log: 12.5 of its 13 minutes). Every rate below is
# therefore taken between fresh records only, inside one run of consecutive fresh records, over a window of several
# steps.
FRESH_GAP_S = 0.2     # a longer gap between two records ends a run
G_WINDOW_S = 0.3      # pedal and g checks: speed change over >= 0.3 s (18 steps)
SPEED_WINDOW_S = 1.0  # speed check: distance counter over >= 1 s
E_WINDOW_S = 1.0      # energy balance windows
E_MARGIN_J = 0.05e6   # the store saturates at empty and full: windows touching either end are left out
ERS_2026_KW = 300     # 2026 cars (max deploy 350 kW); a 2025 car's deploy includes the MGU-H's direct path to the
                      # MGU-K, energy that never enters the store, so the balance below applies to 2026 cars only
DEPLOY_ON_KW = 20     # deploying
WINDOW_MIN_J = 50e3   # a window with this much energy moved counts as a harvest / deploy window
MODES = {0: 'None', 1: 'Medium', 2: 'Boost', 3: 'Hotlap'}  # +0x1a68 (static-validation.md G1)

# --- one log, several stints: a session restart, another session or another track gives the player a new car object
# (generation). Checks that depend on the car (gear ratios) or the track (laps, turns) are made per stint: pooled, run
# 6's 38 s Montreal stint in a 2025 car turned the Bahrain race's checks into FAILs (2026-11-09).
GEAR_MIN_S = 30.0     # in-gear driving a stint needs before its gear ratios are judged
LAUNCH_KMH, LAUNCH_S = 100.0, 8.0   # a launch from a standstill: until this speed or this long (clutch slip, wheelspin)
TURN_BEHIND = 15.0    # halo_track.cpp kBehind: with no turn within 220 m ahead, the one passed shows for 15 m more
BIN_M = 5.0           # halo_track.cpp kBin: lap-distance bins of the driven heading change
CURV_R = 350.0        # halo_track.cpp HALO_CURV_R: an apex bends tighter than this radius
TURN_REACH_M = 60.0   # halo_track.cpp apex_offset: a turn's apex is looked for this far either side of it
TURN_MIN_DEG = 5.0    # a turn's stretch must turn at least this much to judge its arrow
TURN_FREE_M = 50.0    # with no offset measured, an arrow is judged only if its direction holds for any offset this size
POS_TOL_M = 15.0      # the halo's turn positions must sit this close to the driven apexes
SESSIONS = [(1, 4, 'practice'), (5, 9, 'qualifying'), (10, 14, 'sprint shootout'), (15, 17, 'race'), (18, 18, 'time trial')]


def stints(c, mask):
    """Index arrays of the runs of records in mask with one generation and one track (name and length)."""
    idx = np.nonzero(mask)[0]
    if not len(idx):
        return []
    name = text(c['track_name'])[idx]
    gen, tl = c['generation'][idx], c['track_len_m'][idx]
    brk = np.nonzero((np.diff(gen) != 0) | (np.diff(tl) != 0) | (name[1:] != name[:-1]))[0] + 1
    return [idx[a:b] for a, b in zip(np.r_[0, brk], np.r_[brk, len(idx)])]


def stint_name(c, ix):
    st = int(np.median(c['session_type'][ix]))
    sess = next((nm for a, b, nm in SESSIONS if a <= st <= b), f'session {st}')
    return f'{text(c["track_name"][ix[:1]])[0]} {sess} (generation {int(c["generation"][ix[0]])})'


def gear_check(rep, c, live, fresh):
    """Gear: discrete, sequential, one rpm/speed ratio per gear in each stint (one car). Only fresh records with the
    clutch engaged count: a launch from a standstill (clutch slip, wheelspin: one logged start read 567 rpm per km/h in
    1st at 18 km/h) and a disengaged clutch (rpm near idle while rolling: anti-stall in slow traffic, a crash) are left
    out, and so are paused records (a frozen frame repeats one ratio hundreds of times)."""
    t, sp, g, rpm = c['t'], c['speed_kmh'], c['gear'], c['rpm']
    ok = live & (c['gear_ok'] == 1)
    seen = sorted(set(g[ok].astype(int).tolist()))
    steps = np.diff(g[ok].astype(int))
    jumps = int((np.abs(steps[steps != 0]) > 1).sum())
    idle_m = live & (sp < 1) & (c['throttle'] < 0.05) & (c['rpm_ok'] == 1)
    idle = float(np.median(rpm[idle_m])) if idle_m.sum() > 10 else 4000.0
    launch = np.zeros(len(t), dtype=bool)
    start = None
    for i in np.nonzero(live)[0]:
        if sp[i] < 5:
            start = t[i]
        elif start is not None:
            if sp[i] < LAUNCH_KMH and t[i] - start < LAUNCH_S:
                launch[i] = True
            else:
                start = None
    base = fresh & (sp > 30) & (c['gear_ok'] == 1) & (c['rpm_ok'] == 1) & (g >= 1)
    clutch = base & ~launch & (rpm < 1.15 * idle)
    kept = base & ~launch & ~clutch
    judged, skipped, all_ok = [], [], True
    for ix in stints(c, live):
        k = ix[kept[ix]]
        ratio_cv = []
        for gear in range(1, 9):
            mm = k[g[k] == gear]
            if len(mm) >= 20:
                r = rpm[mm] / sp[mm]
                ratio_cv.append((gear, float(np.median(r)), float(np.std(r) / np.mean(r))))
        secs = len(k) * RECORD_S
        if secs < GEAR_MIN_S or len(ratio_cv) < 3:
            if (base[ix]).any():
                skipped.append(f'{stint_name(c, ix)}: {secs:.0f} s in gear, not judged')
            continue
        mono = all(ratio_cv[i][1] > ratio_cv[i + 1][1] for i in range(len(ratio_cv) - 1))
        tight = all(cv < 0.08 for _, _, cv in ratio_cv)
        all_ok &= mono and tight
        judged.append(f'{stint_name(c, ix)}, {secs:.0f} s in gear: rpm per km/h ' +
                      ', '.join(f'{gg}: {r:.1f} (cv {cv:.2f})' for gg, r, cv in ratio_cv))
    ev = (f'gears seen {seen}; ' + '; '.join(judged + skipped) +
          f'; left out: {int((base & launch).sum())} launch records, {int(clutch.sum())} with the clutch out '
          f'(rpm under {1.15 * idle:.0f}); {jumps} multi-step jumps between samples')
    if not judged:
        rep.verdict('Gear', 'NO DATA', ev, f'drive {GEAR_MIN_S:.0f} s or more through at least 3 gears')
    else:
        rep.verdict('Gear', 'PASS' if all_ok else 'FAIL', ev, '' if -1 in seen else 'select reverse once to cover R')


def lap_check(rep, c, live):
    """Lap distance / lap: in each stint, every time the distance passes a multiple of the track length the lap counter
    goes up by one at the same moment. The counter counts completed laps from the first time the car crosses the line,
    so a crossing from behind it (the grid, the out-lap from the pit exit, a garage reset) adds no lap."""
    pg = live & (c['progress_ok'] == 1)
    rows, n_w, n_i, n_m, crossings, ok = [], 0, 0, 0, 0, True
    for ix in stints(c, pg):
        tl = float(np.median(c['track_len_m'][ix]))
        if tl <= 0:
            continue
        tot, lap, t = c['total_m'][ix], c['lap'][ix], c['t'][ix]
        w = np.nonzero((np.diff(np.floor(tot / tl)) == 1) & (tot[:-1] >= 0))[0]
        inc = np.nonzero(np.diff(lap) == 1)[0]
        crossings += int(((tot[:-1] < 0) & (tot[1:] >= 0)).sum())
        match = sum(1 for a in w if len(inc) and np.min(np.abs(t[inc + 1] - t[a + 1])) <= 1.0)
        n_w, n_i, n_m = n_w + len(w), n_i + len(inc), n_m + match
        ok &= abs(len(w) - len(inc)) <= 1 and match >= 0.9 * len(w)
        rows.append(f'{stint_name(c, ix)} ({tl:.0f} m): laps {int(lap.min())}–{int(lap.max())}, {len(w)} distance wraps, '
                    f'{len(inc)} lap increments, {match} at the same moment')
    ev = ('; '.join(rows) + f'; {crossings} crossings from behind the line (grid, pit exit, garage: no lap counted)' +
          (f'; entry → car link matched in {100 * c["progress_link"][pg].mean():.0f}% of records'
           if 'progress_link' in c and pg.any() else ''))
    rep.verdict('Lap distance / lap', 'NO DATA' if n_w == 0 else 'PASS' if ok else 'FAIL', ev,
                'cross the line at least once' if n_w == 0 else '')


def turn_passes(c, ix, shown, lab):
    """Runs of one turn label in a stint: (label, first record, last record, the record after it or -1 when the log
    goes on more than 0.2 s later)."""
    t = c['t']
    passes, k = [], 0
    while k < len(ix):
        if not shown[ix[k]]:
            k += 1
            continue
        j = k
        while j + 1 < len(ix) and shown[ix[j + 1]] and lab[ix[j + 1]] == lab[ix[k]] and t[ix[j + 1]] - t[ix[j]] < 0.5:
            j += 1
        nxt = ix[j + 1] if j + 1 < len(ix) and t[ix[j + 1]] - t[ix[j]] < 0.2 else -1
        passes.append((lab[ix[k]], ix[k], ix[j], nxt))
        k = j + 1
    return passes


def bend_profile(c, ix, fresh, tlen):
    """The heading change (rad, + left) at the end of each 5 m bin of lap distance, as halo_track.cpp learns it from
    the player's path: lateral g * 9.81 / speed^2, mean over the stint's fresh records driven by the player at
    36 km/h or more (spins tighter than a 5 m radius left out), gaps filled linearly, smoothed over 25 m. Also the
    records per bin. (None, None) below 100 records."""
    kk = ix[fresh[ix] & (c['speed_kmh'][ix] >= 36) & (c['accel_ok'][ix] == 1) & (c['progress_ok'][ix] == 1) &
            (c['ai_driving'][ix] == 0)]
    nb = int(np.ceil(tlen / BIN_M))
    if len(kk) < 100 or nb < 10:
        return None, None
    kappa = c['g_lat'][kk] * 9.81 / (c['speed_kmh'][kk] / KMH) ** 2
    ok = np.abs(kappa) <= 0.2
    b = np.clip((c['lap_m'][kk][ok] / BIN_M).astype(int), 0, nb - 1)
    cnt = np.bincount(b, minlength=nb)
    have = np.nonzero(cnt)[0]
    k = np.bincount(b, kappa[ok], nb)[have] / cnt[have]
    k = np.interp(np.arange(nb), have, k, period=nb)
    dth = 0.5 * (k + np.roll(k, -1)) * BIN_M
    return sum(np.roll(dth, j) for j in range(-2, 3)) / 5, cnt


def covered(cnt, lo, hi):
    """The bins from lo to hi m (wrapping at the line), and whether 80% of them have records."""
    ii = np.arange(int(np.floor(lo / BIN_M)), int(np.floor(hi / BIN_M)) + 1) % len(cnt)
    return ii, np.mean(cnt[ii] > 0) >= 0.8


def apex_offset(pos, right, dth, cnt):
    """halo_track.cpp Corners::apex_offset on the logged drive: for each turn, the distance from where the halo puts
    it to the strongest bend of its arrow's direction within 60 m (tighter than a 350 m radius); the median when 5
    or more turns find one. The halo moves its list by the same measure once it has learned a lap, so a list it
    moved measures about 0 here."""
    nb, reach = len(dth), int(TURN_REACH_M / BIN_M)
    js = np.arange(-reach, reach + 1)
    deltas = {}
    for la, p in pos.items():
        ii, cov = covered(cnt, p - TURN_REACH_M, p + TURN_REACH_M)
        if la in right and cov:
            v = (-1 if right[la] else 1) * dth[(int(p / BIN_M) - 1 + js) % nb]
            if v.max() > BIN_M / CURV_R:
                deltas[la] = float(js[np.argmax(v)] * BIN_M)
    d = sorted(deltas.values())
    return (d[len(d) // 2] if len(d) >= 5 else None), deltas


def turn_checks(rep, c, live, fresh):
    """Turn number, position and arrow, per stint.

    Order: labels follow each other in track order, wrapping at the line.
    Position: the halo shows the nearest turn ahead (within 220 m), so where a label hands over to the next one is
    where the halo puts that turn (a label followed by none ends 15 m after it). The driven apex of a turn is the
    strongest bend of its arrow's direction within 60 m, as halo_track.cpp finds it; the median distance over the
    turns is the offset. Where the halo puts a turn before its apex, it shows the next turn's arrow in the corner.
    Arrow: the direction the car turned over each turn's own stretch (halfway to the turn before to halfway to the
    one after, at most 100 m, moved by the offset), against the arrow shown. With no offset measured, only arrows
    whose stretch turns the same way for any offset up to 50 m are judged. Unlike the steering in the second half of
    each label's window (the check until 2026-11-09), it does not credit one corner's exit to the next arrow."""
    lab = text(c['hud_turn'])
    shown = (lab != '-') & (c['hud_live'] == 1)
    arrow_col = c['hud_turn_right'] if 'hud_turn_right' in c else None
    shift = c['turn_shift_m'] if 'turn_shift_m' in c else None
    n_pass, fwd, bad, wrong, flips = 0, 0, 0, Counter(), 0
    order_rows, pos_rows, arrow_rows = [], [], []
    offsets, judged, disagree = [], 0, []
    for ix in stints(c, live):
        passes = turn_passes(c, ix, shown, lab)
        if not passes:
            continue
        n_pass += len(passes)
        tlen = float(np.median(c['track_len_m'][ix]))
        name = stint_name(c, ix)
        seen = sorted({p[0] for p in passes}, key=lambda x: turn_key(x) or (999, x))
        succ = {la: seen[(i + 1) % len(seen)] for i, la in enumerate(seen)}
        f0, b0 = fwd, bad
        for (la, a0, a1, _), (lb, b1, _, _) in zip(passes, passes[1:]):
            if c['t'][b1] - c['t'][a1] > 40:  # a long gap: the pits, a restart, the menus
                continue
            if shift is not None and shift[b1] != shift[a1]:  # the list moved to the game's corners
                continue
            wrapped = c['lap_m'][b1] + 0.5 * tlen < c['lap_m'][a1]
            if lb == la and not wrapped:
                continue
            if lb == succ[la] and (not wrapped or (la == seen[-1] and lb == seen[0])):
                fwd += 1
            else:
                bad += 1
                wrong[f'{la}>{lb}' + (' across the line' if wrapped else '')] += 1
        order_rows.append(f'{name}: {len(passes)} passes of {len(seen)} labels, {fwd - f0} of {fwd - f0 + bad - b0} '
                          f'changes in track order')
        if arrow_col is None:
            continue
        # where the halo puts each turn in the stint's final list: the list moves as a whole once a lap is learned
        # (turn_shift_m), so a pass made before that counts at its position plus the move since
        final = shift[ix[-1]] if shift is not None else 0.0
        direct, gap, arrows = defaultdict(list), defaultdict(list), defaultdict(list)
        for la, a0, a1, nxt in passes:
            tr = arrow_col[a0:a1 + 1]
            if (tr != tr[0]).any() or tr[0] < 0:
                flips += 1
                continue
            arrows[la].append(int(tr[0]))
            sh = shift[a1] if shift is not None else 0.0
            if nxt < 0 or c['speed_kmh'][a1] < 30 or (shift is not None and (shift[a0] != sh or shift[nxt] != sh)):
                continue
            move = final - sh
            if shown[nxt] and lab[nxt] != la:
                if abs(c['lap_m'][nxt] - c['lap_m'][a1]) < 50:
                    direct[la].append((c['lap_m'][a1] + c['lap_m'][nxt]) / 2 + move)
            elif not shown[nxt]:
                gap[la].append(c['lap_m'][a1] - TURN_BEHIND + move)
        pos = {la: float(np.median(direct[la] or gap[la])) % tlen for la in seen if direct[la] or gap[la]}
        right = {la: float(np.mean(v)) >= 0.5 for la, v in arrows.items() if v}
        dth, cnt = bend_profile(c, ix, fresh, tlen)
        if dth is None:
            continue
        off, deltas = apex_offset(pos, right, dth, cnt)
        if off is not None:
            offsets.append((name, off))
        pos_rows.append(f'{name}: ' + (
            f'apexes {off:+.0f} m from the halo\'s turns (median of {len(deltas)}: ' +
            ', '.join(f'T{la} {d:+.0f}' for la, d in sorted(deltas.items(), key=lambda x: turn_key(x[0]) or (999,))) +
            ')' + (f', list moved {final:+.0f} m by the halo' if final else '')
            if off is not None else f'{len(deltas)} turns located, too few'))
        # each turn's own stretch, moved by the offset
        order = sorted((la for la in pos if la in right), key=lambda la: pos[la])
        rows = []
        for i, la in enumerate(order):
            p = pos[la]
            gap_b = (p - pos[order[i - 1]]) % tlen if len(order) > 1 else 2 * TURN_REACH_M
            gap_a = (pos[order[(i + 1) % len(order)]] - p) % tlen if len(order) > 1 else 2 * TURN_REACH_M
            lo, hi = p - min(gap_b / 2, 100.0), p + min(gap_a / 2, 100.0)
            tries = [off] if off is not None else np.arange(-TURN_FREE_M, TURN_FREE_M + 1, BIN_M)
            hs = []
            for o in tries:
                ii, cov = covered(cnt, lo + o, hi + o)
                hs.append(math.degrees(dth[ii].sum()) if cov else 0.0)
            if min(abs(h) for h in hs) < TURN_MIN_DEG or len({h > 0 for h in hs}) > 1:
                continue
            h = hs[len(hs) // 2]
            judged += 1
            ok = (h < 0) == right[la]
            rows.append(f'T{la} {"R" if right[la] else "L"}{"" if ok else " ✗"} {h:+.0f}°')
            if not ok:
                at = (off or 0.0)
                disagree.append(f'{name} T{la}: arrow {"right" if right[la] else "left"}, the car turned '
                                f'{"left" if h > 0 else "right"} ({h:+.0f}° over {(lo + at) % tlen:.0f}–'
                                f'{(hi + at) % tlen:.0f} m)')
        if rows:
            arrow_rows.append(f'{name}' + (f' (stretches moved {off:+.0f} m)' if off else '') + ': ' + ', '.join(rows))
    if n_pass == 0 or fwd + bad < 5:
        rep.verdict('Turn number (order)', 'NO DATA', f'{n_pass} turn passes; ' + '; '.join(order_rows),
                    'drive a full lap (turn numbers need the lap distance)')
    else:
        share = fwd / (fwd + bad)
        rep.verdict('Turn number (order)', 'PASS' if share >= 0.9 else 'FAIL',
                    '; '.join(order_rows) + f'; {fwd} of {fwd + bad} label changes in track order (wrapping at the line)' +
                    (f'; out of order: {dict(wrong.most_common(6))}' if wrong else ''),
                    'check that the number matches the corner on screen; a few out-of-order changes come from spins or '
                    'the pit lane')
    if arrow_col is None:
        return
    if not offsets:
        rep.verdict('Turn position', 'NO DATA', '; '.join(pos_rows) or 'no turn passes with the car moving',
                    'drive a full lap at speed')
    else:
        far = [f'{nm}: {o:+.0f} m' for nm, o in offsets if abs(o) > POS_TOL_M]
        rep.verdict('Turn position', 'FAIL' if far else 'PASS', '; '.join(pos_rows),
                    (f'the halo switches to the next turn {", ".join(far)} before the apex of the one it leaves: its '
                     'turn list must move to the game\'s corners (halo_track.cpp learns this offset from the first '
                     'lap; turn_shift_m logs it)') if far else '')
    ev = (f'{judged} turns judged by the direction the car turned over each turn\'s stretch; ' + '; '.join(arrow_rows) +
          f'; the arrow changed within a pass {flips} times')
    if judged < 4:
        rep.verdict('Turn arrow (direction)', 'NO DATA', ev, 'drive a full lap at speed')
    else:
        rep.verdict('Turn arrow (direction)', 'PASS' if not disagree and not flips else 'FAIL',
                    ev + ('; wrong: ' + '; '.join(disagree) if disagree else ''),
                    'a wrong arrow is a wrong direction in the turn table (tools/corners_hpp.py)' if disagree else '')


def fresh_records(c, live):
    """Live records in which the simulation advanced since the previous live record of the same generation: the world
    velocity or the distance counter changed.

    A moving car changes both at every step. A paused game repeats them bit for bit while the log goes on, and its g
    and ERS powers stand still with them, so a rate taken across such records reads zero or a stale value. (A car
    held at the pit limiter can repeat its velocity to the logged precision; its distance still moves.)"""
    m = np.zeros(len(live), dtype=bool)
    idx = np.nonzero(live)[0]
    if len(idx) > 1:
        V = np.stack([c['vel_x'], c['vel_y'], c['vel_z']], 1)[idx]
        dist = (np.diff(c['total_m'][idx]) != 0) & (c['progress_ok'][idx][1:] == 1) & (c['progress_ok'][idx][:-1] == 1)
        moved = (np.any(np.diff(V, axis=0) != 0, axis=1) | dist) & (np.diff(c['generation'][idx]) == 0)
        m[idx[1:][moved]] = True
    return m


SETTLE_RUN_S = 1.0     # after a generation change: the first stretch this long of fresh records ...
SETTLE_KMH = 20.0      # ... above this speed ...
SETTLE_DIST = 0.10     # ... whose distance counter never goes back and agrees with ∫speed dt within 10 % + 1 m ...
SETTLE_G_SHARE = 0.9   # ... and whose g changes between records in 90 % of them (g readable) ends the settle window
SETTLE_TOWER_S = 15.0  # a tower log read without its halo log: a fixed window after each generation change / restart
SETTLE_BACK_M = 500.0  # the distance counter going back more than this inside a generation is a restart


def settle_start(c, s):
    """The first record of run s (consecutive fresh moving records) that starts a settled SETTLE_RUN_S stretch, or
    None."""
    t, d = c['t'][s], c['total_m'][s]
    Cv = cumtrapz(c['speed_kmh'][s] / KMH, t)
    back = np.concatenate(([0], np.cumsum(np.diff(d) < 0)))
    rd = (c['accel_ok'][s] == 1) if 'accel_ok' in c else np.zeros(len(s), dtype=bool)
    pair = rd[1:] & rd[:-1]
    moved = (np.diff(c['g_long'][s]) != 0) | (np.diff(c['g_lat'][s]) != 0)
    pr = np.concatenate(([0], np.cumsum(pair)))
    pc = np.concatenate(([0], np.cumsum(pair & moved)))
    for i in range(len(s)):
        j = int(np.searchsorted(t, t[i] + SETTLE_RUN_S - 1e-9))
        if j >= len(s):
            return None
        if back[j] != back[i]:
            continue
        path, dd = Cv[j] - Cv[i], d[j] - d[i]
        if abs(dd - path) > SETTLE_DIST * path + 1.0:
            continue
        n = pr[j] - pr[i]
        if n >= 10 and (pc[j] - pc[i]) < SETTLE_G_SHARE * n:
            continue
        return int(s[i])
    return None


def settle_windows(c, live):
    """Records to leave out of the rate checks (speed, pedals, g, energy) and the tower's tyre-change check after a
    generation change (a load, a new car set) or a restart inside a generation. Resuming a save replays the car: in
    the 2026-11-09 15:32 log, after generation 10 began, the distance counter jumped, ran backwards for 0.6 s and
    jumped back, g stood frozen for 10 s while the car moved, and four tyre letters changed while the game rebuilt its
    caches. In the 16:39 log a race restart kept generation 9: the counter fell from 90194 m to 84 m and a tyre letter
    changed on the grid.

    Triggers: the first live record of each generation but the log's first, and each record where the distance
    counter goes back more than SETTLE_BACK_M inside a generation. Window: from the trigger to the start of the first
    SETTLE_RUN_S stretch of consecutive fresh records above SETTLE_KMH in which the distance counter never goes back
    and agrees with ∫speed dt within SETTLE_DIST + 1 m, and g changes between records in SETTLE_G_SHARE of them
    (where g is readable). With no such stretch the window runs to the generation's end.
    Returns (mask, [(generation, start t, settled t or inf, cause)])."""
    t, gen = c['t'], c['generation']
    mask = np.zeros(len(t), dtype=bool)
    out = []
    idx = np.nonzero(live)[0]
    if not len(idx) or not len(t):
        return mask, out
    fresh = fresh_records(c, live)
    gs, at = np.unique(gen[idx], return_index=True)
    trig = [(int(idx[k]), 'generation change') for g, k in zip(gs, at) if g != gen[0]]
    pr = idx[c['progress_ok'][idx] == 1]
    back = pr[1:][(np.diff(c['total_m'][pr]) < -SETTLE_BACK_M) & (np.diff(gen[pr]) == 0)]
    trig += [(int(k), 'restart') for k in back]
    base = fresh & (c['speed_ok'] == 1) & (c['progress_ok'] == 1) & (c['speed_kmh'] > SETTLE_KMH)
    for k, cause in sorted(trig):
        g, t0 = gen[k], t[k]
        end = math.inf
        for s in segments(t, gen, base & (gen == g) & (t >= t0), SETTLE_RUN_S):
            j = settle_start(c, s)
            if j is not None:
                end = float(t[j])
                break
        gi = idx[(gen[idx] == g) & (t[idx] >= t0)]
        mask[gi[t[gi] < end]] = True
        out.append((g, float(t0), end, cause))
    return mask, out


def settle_text(rep, info):
    if not info:
        return
    parts = [f'{cause} at {a:.1f} s (generation {int(g)}): to {b:.1f} s ({b - a:.1f} s)'
             for g, a, b, cause in info if math.isfinite(b)]
    never = [int(g) for g, a, b, cause in info if not math.isfinite(b)]
    if never:
        parts.append(f'{len(never)} with no such stretch before the generation ended, left out whole (generation'
                     f'{"s" if len(never) > 1 else ""} {", ".join(map(str, never[:12]))}{" …" if len(never) > 12 else ""})')
    rep.text('- Settle windows after generation changes and restarts (left out of the speed, pedal, g and energy checks '
             "and the tower's tyre changes): " + '; '.join(parts) + f'. Each ends where the first {SETTLE_RUN_S:.0f} s '
             f'of fresh records above {SETTLE_KMH:.0f} km/h has a distance counter that never goes back and agrees with '
             f'∫speed dt within {100 * SETTLE_DIST:.0f} % + 1 m, and g changing between records.')


def segments(t, gen, mask, min_s=0.0):
    """Runs of consecutive records in mask (none left out between them, one generation, no gap > FRESH_GAP_S, time
    increasing), as index arrays, each at least min_s long."""
    idx = np.nonzero(mask)[0]
    if not len(idx):
        return []
    dt = np.diff(t[idx])
    cut = np.nonzero((np.diff(idx) != 1) | (np.diff(gen[idx]) != 0) | (dt > FRESH_GAP_S) | (dt <= 0))[0]
    return [s for s in np.split(idx, cut + 1) if len(s) > 1 and t[s[-1]] - t[s[0]] >= min_s]


def windows(t, segs, width):
    """Non-overlapping (first, last) record index pairs, each spanning at least `width` seconds inside one run."""
    out = []
    for s in segs:
        tt = t[s]
        i = 0
        while True:
            j = int(np.searchsorted(tt, tt[i] + width - 1e-9))
            if j >= len(s):
                break
            out.append((s[i], s[j]))
            i = j
    return np.array(out, dtype=int).reshape(-1, 2)


def cumtrapz(x, t):
    """Running trapezoid integral of x over t. Differences are valid between two records of one run."""
    return np.concatenate(([0.0], np.cumsum(0.5 * (x[1:] + x[:-1]) * np.diff(t))))


def slope_r(x, y):
    """(slope through the origin, r) of y against x; nan without spread."""
    if len(x) < 10 or np.std(x) == 0 or np.std(y) == 0:
        return float('nan'), float('nan')
    return float(np.dot(x, y) / np.dot(x, x)), corr(x, y)


def frozen_text(rep, c, live, fresh):
    """How much of the log the game was paused for (the state frozen while the log goes on)."""
    t = c['t']
    idx = np.nonzero(live)[0]
    gaps = np.diff(t[idx]) if len(idx) > 1 else np.zeros(0)
    ok = gaps < FRESH_GAP_S
    run_s = float(gaps[ok & fresh[idx[1:]]].sum()) if len(gaps) else 0.0
    frozen_s = float(gaps[ok & ~fresh[idx[1:]]].sum()) if len(gaps) else 0.0
    mv = live & (c['speed_kmh'] > 20)
    frz = mv & ~fresh
    s, at = longest(frz, t)
    rep.text(f'- Simulation advancing in {run_s:.0f} s of the live log, state frozen in {frozen_s:.0f} s (game paused or '
             f'car parked: world velocity, distance counter, g and ERS powers repeat bit for bit). {int(frz.sum())} of '
             f'{int(mv.sum())} live records above 20 km/h are frozen (paused at speed)' +
             (f', the longest run {s:.0f} s from t = {t[at]:.1f} s' if at is not None else '') +
             '. Speed, pedal, g and energy checks use fresh records only and take rates only inside runs of them.')
    return run_s


def speed_check(rep, c, live, fresh):
    """Speed against the game's own distance counter (VehicleProgressSystem, an object independent of the car)."""
    t, gen = c['t'], c['generation']
    sp = c['speed_kmh'] / KMH
    base = fresh & (c['speed_ok'] == 1) & (c['progress_ok'] == 1)
    moving = base & (c['speed_kmh'] > 20)
    Cv = cumtrapz(sp, t)
    W = windows(t, segments(t, gen, base, SPEED_WINDOW_S), SPEED_WINDOW_S)
    a, b = W[:, 0], W[:, 1]
    dt = t[b] - t[a]
    path, dD = Cv[b] - Cv[a], c['total_m'][b] - c['total_m'][a]
    mv = path > dt * 20 / KMH
    ev, fails, checked = [], [], False
    if mv.sum() >= 30:
        checked = True
        ratio = dD[mv] / path[mv]
        r = corr(dD[mv] / dt[mv], path[mv] / dt[mv])
        med = float(np.median(ratio))
        if not (abs(med - 1) < 0.03 and r > 0.98):
            fails.append('distance counter')
        ev.append(f'distance counter (total_m): Δdistance / ∫speed dt = {med:.3f} median (p5 {np.percentile(ratio, 5):.3f}, '
                  f'p95 {np.percentile(ratio, 95):.3f}) over {int(mv.sum())} fresh 1 s windows above 20 km/h, '
                  f'r(Δdistance / Δt, mean speed) = {r:.3f}')
    if 'dist_win_s' in c:
        # the provider's reference: the counter's change over >= 0.5 s between two of its changes (one per 60 Hz step)
        w, sd = c['dist_win_s'], c['speed_dist_kmh'] / KMH
        ref, val, eligible = [], [], 0
        for s in segments(t, gen, base, 0.6):
            k = s[(t[s] - t[s[0]] >= 0.6) & moving[s]]  # far enough into the run for a whole window to lie in it
            eligible += len(k)
            k = k[(w[k] >= 0.5) & (t[k] - w[k] >= t[s[0]])]
            if len(k):
                ref.append((Cv[k] - np.interp(t[k] - w[k], t[s], Cv[s])) / w[k])
                val.append(sd[k])
        n2 = sum(len(x) for x in ref)
        cover = n2 / eligible if eligible else float('nan')
        if n2 >= 50:
            checked = True
            ref, val = np.concatenate(ref), np.concatenate(val)
            ratio = val / ref
            med, r = float(np.median(ratio)), corr(val, ref)
            if not (abs(med - 1) < 0.03 and r > 0.98 and cover > 0.8):
                fails.append('provider reference')
            ev.append(f'provider reference (speed_dist_kmh over its dist_win_s window): {med:.3f} × the mean speed over '
                      f'that window, median (p5 {np.percentile(ratio, 5):.3f}, p95 {np.percentile(ratio, 95):.3f}), '
                      f'r = {r:.3f}, present in {pct(cover)} of {eligible} fresh moving records')
        elif eligible >= 50:
            checked = True
            fails.append('provider reference')
            ev.append(f'provider reference present in only {pct(cover)} of {eligible} fresh moving records')
    elif moving.sum() > 50:
        # builds before 2026-11-09: speed_dist_kmh was the counter's change since the previous rendered frame; the
        # counter moves once per 60 Hz step, so that is 0 on frames without a step and ~3x the speed on the rest
        sd, spm = c['speed_dist_kmh'][moving], c['speed_kmh'][moving]
        nz = sd != 0
        ev.append(f"the log's own reference column (old build: change since the previous frame) is 0 in "
                  f'{pct(1 - nz.mean())} of {int(moving.sum())} fresh moving records and '
                  f'{np.median(sd[nz] / spm[nz]) if nz.any() else float("nan"):.2f}× the speed in the rest: not used')
    if not checked:
        rep.verdict('Speed', 'NO DATA', 'too few fresh moving records' + (f'; {"; ".join(ev)}' if ev else ''),
                    'drive a lap')
        return
    rep.verdict('Speed', 'FAIL' if fails else 'PASS', '; '.join(ev) + f'; max {c["speed_kmh"][live].max():.0f} km/h',
                f'disagrees with: {", ".join(fails)}; send the log' if fails else '')


def accel_checks(rep, c, live, fresh):
    """Pedals and the g fields against the car's own motion: the change of its speed and world velocity over
    >= G_WINDOW_S between fresh records (never the frozen g of a paused game, never a rate across a gap)."""
    t, gen = c['t'], c['generation']
    v = c['speed_kmh'] / KMH
    W = windows(t, segments(t, gen, fresh & (c['input_ok'] == 1), G_WINDOW_S), G_WINDOW_S)
    a, b = W[:, 0], W[:, 1]
    acc = (v[b] - v[a]) / (t[b] - t[a])
    slow = np.minimum(v[a], v[b]) * KMH
    thr, brk = c['throttle'], c['brake']
    lo_t = np.array([thr[i:j + 1].min() for i, j in W])
    hi_b = np.array([brk[i:j + 1].max() for i, j in W])
    lo_b = np.array([brk[i:j + 1].min() for i, j in W])
    full_thr = (slow > 30) & (lo_t > 0.95) & (hi_b < 0.05) if len(W) else np.zeros(0, dtype=bool)
    hard_brk = (slow > 30) & (lo_b > 0.6) if len(W) else np.zeros(0, dtype=bool)
    if full_thr.sum() >= 10:
        a_thr = float(np.median(acc[full_thr]))
        rep.verdict('Throttle', 'PASS' if a_thr > 0.3 else 'FAIL',
                    f'median accel {a_thr:.1f} m/s² over {int(full_thr.sum())} fresh 0.3 s windows at full throttle')
    else:
        rep.verdict('Throttle', 'NO DATA', f'{int(full_thr.sum())} fresh full-throttle windows',
                    'accelerate flat out down a straight')
    if hard_brk.sum() >= 5:
        a_brk = float(np.median(acc[hard_brk]))
        rep.verdict('Brake', 'PASS' if a_brk < -5 else 'FAIL',
                    f'median accel {a_brk:.1f} m/s² over {int(hard_brk.sum())} fresh 0.3 s windows with the brake > 60%')
    else:
        rep.verdict('Brake', 'NO DATA', f'{int(hard_brk.sum())} fresh heavy-braking windows', 'brake hard into a corner')

    # g: chassis +0x324 (longitudinal) and +0x320 (lateral), in g
    W = windows(t, segments(t, gen, fresh & (c['accel_ok'] == 1), G_WINDOW_S), G_WINDOW_S)
    a, b = W[:, 0], W[:, 1]
    dt = t[b] - t[a]
    keep = np.minimum(v[a], v[b]) * KMH > 30
    a, b, dt = a[keep], b[keep], dt[keep]
    if len(a) < 50:
        rep.verdict('Longitudinal g (G-meter)', 'NO DATA', f'{len(a)} fresh 0.3 s windows above 30 km/h', 'drive a lap')
        rep.verdict('Lateral g (G-meter)', 'NO DATA', f'{len(a)} fresh 0.3 s windows above 30 km/h', 'drive a lap')
        return
    gl = (cumtrapz(c['g_long'], t)[b] - cumtrapz(c['g_long'], t)[a]) / dt
    gt = (cumtrapz(c['g_lat'], t)[b] - cumtrapz(c['g_lat'], t)[a]) / dt
    along = (v[b] - v[a]) / dt / 9.81
    # signed lateral acceleration from the world velocity (Y up): (v × dv/dt)·up / |v|
    V = np.stack([c['vel_x'], c['vel_y'], c['vel_z']], 1)
    Vm = np.stack([(cumtrapz(V[:, i], t)[b] - cumtrapz(V[:, i], t)[a]) / dt for i in range(3)], 1)
    dV = (V[b] - V[a]) / dt[:, None]
    lat = np.cross(Vm, dV)[:, 1] / np.maximum(np.linalg.norm(Vm, axis=1), 1e-3) / 9.81
    st = (cumtrapz(c['steer'], t)[b] - cumtrapz(c['steer'], t)[a]) / dt
    st_ok = (c['steer_ok'][a] == 1) & (c['steer_ok'][b] == 1)
    k_l, r_l = slope_r(along, gl)
    k_t, r_t = slope_r(lat, gt)

    def med(x, m):
        return float(np.median(x[m])) if m.any() else float('nan')
    up, down = along > 0.2, along < -1.0
    right, left = st_ok & (st > 0.1), st_ok & (st < -0.1)
    ok_l = r_l > 0.9 and 0.9 < k_l < 1.1
    ok_t = r_t > 0.9 and 0.9 < k_t < 1.1
    rep.verdict('Longitudinal g (G-meter)', 'PASS' if ok_l else 'FAIL',
                f'g_long = {k_l:.3f} × Δspeed/Δt / 9.81, r = {r_l:.3f}, over {len(a)} fresh 0.3 s windows above 30 km/h; '
                f'median g_long {med(gl, up):+.2f} speeding up (> 0.2 g), {med(gl, down):+.2f} braking (< −1 g): '
                f'positive = speeding up', '' if ok_l else 'send the log')
    rep.verdict('Lateral g (G-meter)', 'PASS' if ok_t else 'FAIL',
                f'g_lat = {k_t:.3f} × the lateral acceleration from the world velocity, r = {r_t:.3f}, same windows; '
                f'median g_lat {med(gt, right):+.2f} steering right (steer > 0.1, {int(right.sum())} windows), '
                f'{med(gt, left):+.2f} steering left ({int(left.sum())}): positive = toward the car\'s left',
                '' if ok_t else 'send the log')


# --- the G-force meter (native/src/gmeter.cpp; option g_meter, off by default; columns hud_g_* since 2026-11-09)
GM_FIELDS = ('G meter: value', 'G meter: segments', 'G meter: direction', 'G meter: red bar and flash')
GM_WINDOW_S = 0.1     # the meter filters per frame (median of 3 fresh reads, then tau 0.05 s): compared with a 0.1 s median
GM_MIN_ROWS = 100


def gm_windowed(c, fresh, idx, width=GM_WINDOW_S):
    """Median g_lat and g_long over the fresh, readable records of the same generation in [t - width, t], for each
    record in idx (NaN where there is none)."""
    t, gen = c['t'], c['generation']
    fi = np.nonzero(fresh & (c['accel_ok'] == 1))[0]
    lo = np.searchsorted(t[fi], t[idx] - width - 1e-9, side='left')
    hi = np.searchsorted(t[fi], t[idx] + 1e-9, side='right')
    lat, lon = np.full(len(idx), np.nan), np.full(len(idx), np.nan)
    for j, (a, b) in enumerate(zip(lo, hi)):
        w = fi[a:b]
        w = w[gen[w] == gen[idx[j]]]
        if len(w):
            lat[j], lon[j] = np.median(c['g_lat'][w]), np.median(c['g_long'][w])
    return lat, lon


def gm_lit(segs):
    """Lit segments of the bitmask: bit k is the segment centred on k * 45 deg (0 right, 90 down, 180 left, 270 up)."""
    return [k for k in range(8) if (int(segs) >> k) & 1]


def gm_adjacent(ks):
    return len(ks) in (2, 3) and any(all((s + j) % 8 in ks for j in range(len(ks))) for s in ks)


def gm_middle(ks):
    """The direction (deg) in the middle of the lit segments: their circular mean."""
    x = sum(math.cos(math.radians(45 * k)) for k in ks)
    y = sum(math.sin(math.radians(45 * k)) for k in ks)
    return math.degrees(math.atan2(y, x)) % 360


def gm_angle(a, b):
    return abs((a - b + 180) % 360 - 180)


def gmeter_checks(rep, c, live, fresh):
    """The G-force meter against the logged g and against its own rules (the meter's spec, 2026-11-09). Only
    records with the meter on (hud_g_on = 1) count."""
    if 'hud_g_on' not in c:
        for f in GM_FIELDS:
            rep.verdict(f, 'NO DATA', 'log written by an older build (no meter columns)', 'update the addon')
        return
    on = c['hud_g_on'] == 1
    if not on.any():
        for f in GM_FIELDS:
            rep.verdict(f, 'NO DATA', 'the G-force meter was off', 'turn the G-force meter option on and drive a lap')
        return
    t = c['t']
    tenths, segs, axis = c['hud_g_tenths'], c['hud_g_segs'].astype(int), c['hud_g_axis']
    red, flash = c['hud_g_red_bar'], c['hud_g_red_digits']
    pop = np.array([len(gm_lit(s)) for s in segs])

    # 1 + 2: unavailable records blank; the value against the read g (fresh records, 0.1 s median)
    na = on & ((c['accel_ok'] != 1) | (c['hud_live'] != 1))
    na_bad = na & ~((tenths == -1) & (segs == 0) & (axis == -1) & (red == 0) & (flash == 0))
    shown = on & ~na & (tenths >= 0)
    blank = on & ~na & (tenths < 0)
    vi = np.nonzero(shown & fresh)[0]
    lat, lon = gm_windowed(c, fresh, vi)
    okw = np.isfinite(lat)
    err = np.abs(tenths[vi][okw] / 10 - np.hypot(lat[okw], lon[okw]))
    within = float((err <= 0.3).mean()) if len(err) else float('nan')
    blank_share = float(blank.sum() / max(1, (on & ~na).sum()))
    ev = (f'{int(on.sum())} records with the meter on; {int(na.sum())} unreadable, {int(na_bad.sum())} of them not blank; '
          f'{int(blank.sum())} blank while readable; value within 0.3 g of the 0.1 s median read in {pct(within)} of '
          f'{len(err)} fresh records' + (f' (median error {np.median(err):.2f} g)' if len(err) else ''))
    bad = na_bad.any() or (len(err) >= GM_MIN_ROWS and (within < 0.95 or blank_share > 0.05))
    if bad:
        rep.verdict(GM_FIELDS[0], 'FAIL', ev, 'the meter must show hypot(g_lat, g_long) and go blank when g is unreadable')
    elif len(err) < GM_MIN_ROWS:
        rep.verdict(GM_FIELDS[0], 'NO DATA', ev, 'drive a lap with the G-force meter on')
    else:
        rep.verdict(GM_FIELDS[0], 'PASS', ev, 'check the meter against the game\'s own g readout if it has one')

    # 3 + 4: indicator on/off with hysteresis, 2 or 3 adjacent segments, wide from 2.0 g and narrow below 1.0 g
    s = shown
    rules = {
        'segments lit at <= 0.2 g': s & (tenths <= 2) & (segs != 0),
        'no segment at >= 0.4 g': s & (tenths >= 4) & (segs == 0),
        'axis set without segments or missing with them': s & ((axis == -1) != (segs == 0)),
        'not 2 or 3 adjacent segments': s & (segs != 0) & ~np.array([gm_adjacent(gm_lit(x)) for x in segs]),
        '3 segments below 1.0 g': s & (pop == 3) & (tenths < 10),
        '2 segments at >= 2.1 g': s & (tenths >= 21) & (segs != 0) & (pop != 3),
    }
    broken = {k: int(m.sum()) for k, m in rules.items() if m.any()}
    ev = (f'{int(s.sum())} records with a value: {int((s & (segs != 0)).sum())} lit ({int((s & (pop == 3)).sum())} wide); '
          + ('; '.join(f'{k}: {n}' for k, n in broken.items()) if broken else 'every rule held'))
    if not s.any():
        rep.verdict(GM_FIELDS[1], 'NO DATA', ev, 'drive a lap with the G-force meter on')
    else:
        rep.verdict(GM_FIELDS[1], 'FAIL' if broken else 'PASS', ev,
                    'the indicator rules in native/src/gmeter.cpp' if broken else '')

    # 5: direction. The middle of the lit segments within 67.5 deg of the read g's direction; the axis the side the
    # middle points to (round(dir / 90), so within 67.5 deg of it as the middle is); the signs on clear cases
    di = np.nonzero(s & fresh & (tenths >= 5) & (segs != 0))[0]
    lat, lon = gm_windowed(c, fresh, di)
    okd = np.isfinite(lat)
    di, lat, lon = di[okd], lat[okd], lon[okd]
    gdir = np.degrees(np.arctan2(lon, lat)) % 360
    mid = np.array([gm_middle(gm_lit(segs[k])) for k in di])
    dir_ok = float((np.array([gm_angle(a, b) for a, b in zip(mid, gdir)]) <= 67.5).mean()) if len(di) else float('nan')
    li = np.nonzero(s & (segs != 0))[0]
    axis_bad = int(sum(gm_angle(gm_middle(gm_lit(segs[k])), 90 * axis[k]) > 67.5 for k in li))
    right = (lat > 1) & (np.abs(lon) < 0.5 * lat)
    brake = (lon < -1) & (np.abs(lat) < 0.5 * -lon)
    right_ok = float((axis[di][right] == 0).mean()) if right.any() else float('nan')
    brake_ok = float((axis[di][brake] == 3).mean()) if brake.any() else float('nan')
    ev = (f'lit segments point within 67.5 deg of the read g in {pct(dir_ok)} of {len(di)} fresh records at >= 0.5 g; '
          f'axis off its segments in {axis_bad} of {len(li)} records; g_lat > 1 g (mostly sideways): axis right in '
          f'{pct(right_ok)} of {int(right.sum())}; braking < -1 g (mostly straight): axis up in {pct(brake_ok)} of '
          f'{int(brake.sum())}')
    signs_bad = (right.sum() >= 20 and right_ok < 0.9) or (brake.sum() >= 20 and brake_ok < 0.9)
    if len(di) < GM_MIN_ROWS:
        rep.verdict(GM_FIELDS[2], 'FAIL' if axis_bad else 'NO DATA', ev, 'corner and brake hard with the meter on')
    elif dir_ok < 0.9 or axis_bad or signs_bad:
        rep.verdict(GM_FIELDS[2], 'FAIL', ev, 'the arc must sit on the side the force pushes the driver: right in a left '
                                              'turn (g_lat > 0), up under braking')
    else:
        rep.verdict(GM_FIELDS[2], 'PASS', ev, 'check on screen: braking lights the top, a left turn the right side')

    # 6 + 7: the red bar from 2.3-2.4 g; the digits flash for <= 1.5 s from >= 4.3 g, again only after < 4.0 g
    red_bad = int((s & (red == 1) & (tenths < 23)).sum()) + int((s & (tenths >= 24) & (red != 1)).sum())
    flash_bad = []
    prev_end = None
    flashes = runs(on & (flash == 1))             # inclusive (first, last) records
    for a, b in flashes:
        if t[b] - t[a] > 1.5 + 0.05:
            flash_bad.append(f'{t[a]:.1f} s lasted {t[b] - t[a]:.1f} s')
        if not (tenths[max(a - 1, 0):a + 2] >= 43).any():
            flash_bad.append(f'{t[a]:.1f} s started below 4.3 g')
        gap = tenths[prev_end:a] if prev_end is not None else None
        if gap is not None and not ((gap >= 0) & (gap < 40)).any():
            flash_bad.append(f'{t[a]:.1f} s without dropping below 4.0 g first')
        prev_end = b + 1
    n_flash = len(flashes)
    ev = (f'red bar on in {int((s & (red == 1)).sum())} records, {red_bad} against the 2.3 / 2.4 g rule; '
          f'{int((s & (tenths >= 24)).sum())} records at >= 2.4 g; {n_flash} flashes'
          + (f': {"; ".join(flash_bad[:5])}' if flash_bad else '')
          + ('' if (s & (tenths >= 43)).any() else '; never 4.3 g, so the flash was not exercised'))
    if red_bad or flash_bad:
        rep.verdict(GM_FIELDS[3], 'FAIL', ev, 'the red bar and flash rules in native/src/gmeter.cpp')
    elif not (s & (tenths >= 24)).any():
        rep.verdict(GM_FIELDS[3], 'NO DATA', ev, 'brake hard or corner fast (2.4 g or more) with the meter on')
    else:
        rep.verdict(GM_FIELDS[3], 'PASS', ev, '')


def energy_checks(rep, c, live, fresh):
    """The battery's own energy against the power fields: over fresh 1 s windows the store must change by
    ∫(harvest_k − deploy) dt, by ERS mode, away from empty and full."""
    t, gen = c['t'], c['generation']
    es = live & (c['store_ok'] == 1) & (c['power_ok'] == 1)
    if es.sum() <= 100:
        rep.verdict('Battery / Recharge / Deploy', 'NO DATA', 'energy channels not read', 'drive a lap')
        return
    E = c['store_mj'] * 1e6
    caps = c['capacity_mj'][es & (c['capacity_ok'] == 1)]
    cap = float(np.median(caps)) * 1e6 if len(caps) else 4e6
    rep.verdict('Battery energy', 'PASS' if (E[es].min() >= 0 and E[es].max() <= 4.2e6) else 'FAIL',
                f'{E[es].min() / 1e6:.2f}–{E[es].max() / 1e6:.2f} MJ (capacity {cap / 1e6:.2f} MJ)')
    rep.text(f'- Low-battery state reached: {"yes" if E[es].min() < 0.5e6 else "no"} (minimum {E[es].min() / 1e6:.2f} MJ).')
    hk, hh, dp = c['harvest_k_kw'] * 1e3, c['harvest_h_kw'] * 1e3, c['deploy_kw'] * 1e3
    mode = c['ers_mode']
    md_ok = es & (c['max_deploy_ok'] == 1) & (c['mode_ok'] == 1)
    car26 = md_ok & (c['max_deploy_kw'] >= ERS_2026_KW)
    n25 = int((md_ok & (c['max_deploy_kw'] < ERS_2026_KW)).sum())
    if n25:
        rep.text(f'- {n25} live records in a 2025 car (max deploy < {ERS_2026_KW} kW): not used for the energy balance (its '
                 'deploy includes the MGU-H\'s direct path, energy that never enters the store).')
    base = fresh & car26
    W = windows(t, segments(t, gen, base, E_WINDOW_S), E_WINDOW_S)
    keep = np.array([E[i:j + 1].min() > E_MARGIN_J and E[i:j + 1].max() < cap - E_MARGIN_J and
                     (mode[i:j + 1] == mode[i]).all() for i, j in W], dtype=bool)
    W = W[keep] if len(W) else W
    a, b = W[:, 0], W[:, 1]
    CH, CD = cumtrapz(hk, t), cumtrapz(dp, t)
    dE, H, D = E[b] - E[a], CH[b] - CH[a], CD[b] - CD[a]
    wm = mode[a].astype(int)
    nH, nD, nDrop = int((H >= WINDOW_MIN_J).sum()), int((D >= WINDOW_MIN_J).sum()), int((dE <= -WINDOW_MIN_J).sum())
    kh = kd = float('nan')
    if nH >= 3 and nD >= 3:
        (kh, kd), *_ = np.linalg.lstsq(np.stack([H, -D], 1), dE, rcond=None)
    elif nH >= 3:
        kh = float(np.dot(H, dE) / np.dot(H, H))
    elif nD >= 3:
        kd = float(-np.dot(D, dE) / np.dot(D, D))
    r = corr(dE, H - D)
    res = float(np.median(np.abs(dE - (H - D)))) / 1e3 if len(W) else float('nan')
    by_mode = ', '.join(f'{MODES.get(m, m)} {int((wm == m).sum())}' for m in sorted(set(wm.tolist())))
    bal = (f'over {len(W)} fresh 1 s windows of a 2026 car in one ERS mode ({by_mode}), store between '
           f'{E_MARGIN_J / 1e6:.2f} MJ and full − {E_MARGIN_J / 1e6:.2f} MJ: ΔE = {kh:.3f} × ∫harvest_k dt − {kd:.3f} × '
           f'∫deploy dt (least squares), r(ΔE, ∫(harvest_k − deploy) dt) = {r:.4f}, median |ΔE − ∫(harvest_k − deploy) '
           f'dt| = {res:.1f} kJ')
    full = base & (E >= cap - 1e3)
    at_limit = base & (c['lap_ok'] == 1) & (c['harvest_limit_mj'] > 0) & \
        (c['harvest_lap_mj'] >= c['harvest_limit_mj'] - 0.005)

    def stops(m, where):
        # harvest_k is the energy entering the store: 0 once it cannot take more, except in the record whose step
        # got it there
        on = m & (hk > 1e3)
        most = max((b - a + 1 for a, b in runs(on)), default=0)
        return (f'; harvest_k > 1 kW in {int(on.sum())} of {int(m.sum())} fresh records {where} (at most {most} in a '
                'row: the step that got there)') if m.any() else ''
    rest = stops(full, 'at a full store') + stops(at_limit, 'at the lap harvest limit') + \
        (f'; harvest_h max {hh[base].max() / 1e3:.0f} kW' if base.any() else '')
    if nH < 10:
        rep.verdict('Recharge (harvest power)', 'NO DATA', f'{nH} fresh windows harvesting > 50 kJ; {bal}',
                    'brake hard into a few corners with the battery below full')
    else:
        ok = r >= 0.98 and abs(kh - 1) <= 0.05
        rep.verdict('Recharge (harvest power)', 'PASS' if ok else 'FAIL',
                    f'{bal}; {nH} windows harvesting > 50 kJ{rest}',
                    '' if ok else 'harvest_k does not account for the battery\'s rise: send the log')
    # deploy by mode at full throttle where no speed taper applies (150-250 km/h)
    ft = base & (c['throttle'] > 0.95) & (c['brake'] < 0.05) & (E > 0.2e6)
    band = ft & (c['speed_kmh'] >= 150) & (c['speed_kmh'] <= 250)
    per = []
    for m in (1, 3, 2):
        k = band & (mode == m)
        if k.sum() >= 20:
            per.append(f'{MODES[m]}: deploying in {pct(float((dp[k] > DEPLOY_ON_KW * 1e3).mean()))} of {int(k.sum())}, '
                       f'p95 {np.percentile(dp[k], 95) / 1e3:.0f} kW')
    m0 = base & (mode == 0)
    if m0.any():
        per.append(f'None (mode 0): deploy max {dp[m0].max() / 1e3:.0f} kW, harvest max {hk[m0].max() / 1e3:.0f} kW over '
                   f'{int(m0.sum())} records')
    per_txt = ('; at full throttle 150–250 km/h by mode: ' + '; '.join(per)) if per else ''
    if nD < 10 and nDrop < 10:
        rep.verdict('Deploy (deploy power)', 'NO DATA', f'{nD} fresh windows deploying > 50 kJ{per_txt}',
                    'accelerate flat out down a straight in a 2026 car')
    elif nD < 10:
        rep.verdict('Deploy (deploy power)', 'FAIL',
                    f'the battery fell by > 50 kJ in {nDrop} fresh 1 s windows while deploy accounted for > 50 kJ in only '
                    f'{nD}; {bal}{per_txt}', 'deploy does not account for the battery\'s fall: send the log')
    else:
        ok = r >= 0.98 and abs(kd - 1) <= 0.05
        rep.verdict('Deploy (deploy power)', 'PASS' if ok else 'FAIL', f'{bal}; {nD} windows deploying > 50 kJ{per_txt}',
                    '' if ok else 'deploy does not account for the battery\'s fall: send the log')
    # the speed taper: median deploy at full throttle by 20 km/h band, per mode
    lines = []
    for m in (1, 3, 2):
        cells = []
        for lo in range(200, 360, 20):
            k = ft & (mode == m) & (c['speed_kmh'] >= lo) & (c['speed_kmh'] < lo + 20)
            if k.sum() >= 10:
                cells.append(f'{lo}–{lo + 20}: {np.median(dp[k]) / 1e3:.0f}')
        if cells:
            lines.append(f'{MODES[m]} ' + ', '.join(cells))
    if lines:
        rep.text('- Deploy at full throttle by speed (median kW, fresh records, battery > 0.2 MJ): ' + '; '.join(lines) + '.')


# ---------------------------------------------------------------- timing tower (tower_<stamp>.csv)
#
# The companion log written next to the halo's (native/src/diag_log.cpp write_tower): 10 records a second with the
# raw reads behind docs/timing-tower/field-traces.md §1-6 and what the tower showed; tyres, penalties and warnings
# once a second. Per-car columns hold one token per vehicle id (0..the last id with data, '-' = none). Each check
# below compares a read with another, independent game structure or with the rule that field-traces.md derived
# from the game's code, so a wrong offset fails instead of looking plausible. The team badges (§10, leaves v4) have
# no second game structure to compare with: their check holds the reads to the rules every real grid follows
# (teammates share one badge, a car keeps its own) and the rows to the cars they show.

TOWER_FIELDS = ('Tower: systems found', 'Tower: classification (results R)', 'Tower: gaps and intervals',
                'Tower: tyres', 'Tower: safety car', 'Tower: penalties', 'Tower: warnings', 'Tower: shown values',
                'Tower: cost', 'Tower: yellow flag', 'Tower: red flag', 'Tower: team badges')
TOWER_CARS = 24
RACE_TYPES = (15, 16, 17)
VISUAL_OF = {3: 16, 4: 17, 5: 18, 7: 7, 8: 8}       # compound enum -> the game's visual id (field-traces.md §1)
LETTER_OF = {3: 'S', 4: 'M', 5: 'H', 7: 'I', 8: 'W'}
CLEARS_GAP = set(range(2, 8)) | {14, 15}            # pit states whose gap flags the game clears (§6)
IN_PIT = set(range(2, 16))                          # the full-grid list's PIT rule
PIT_WINDOW_S = 90.0                                 # a tyre change must follow a pit-lane visit within this
SYSTEMS = (('R', 'results'), ('T', 'timing'), ('P', 'pit state'), ('S', 'safety car'), ('Z', 'penalty log'),
           ('1', 'misconduct'), ('Y', 'tyres'), ('G', 'progress'), ('M', 'marshal zones'), ('F', 'red flag'))
FLAG_FLICKER_S = 0.6   # a header state that lasts less than this between two others is a flicker (2 reads at 4 Hz)
HS_NAME = {0: 'normal', 1: 'SC', 2: 'VSC', 3: 'red flag', 4: 'chequered', 5: 'yellow'}
FLAG_TODO = {'yellow': 'in a race, stop on track (or crash and lose a wheel) and stay there about 30 s; retry if a '
                       'safety car comes instead (test-drive.md, Flags)',
             'red': 'in a race with red flags on, crash hard enough for debris; retry if a safety car comes instead '
                    '(test-drive.md, Flags)'}
KIND = {0: 'off', 1: 'word', 2: 'time', 3: 'lapped', 4: 'PIT', 5: 'out', 6: 'unavailable'}


def tower_path(halo_path):
    """halo_<stamp>.csv -> tower_<stamp>.csv in the same folder; other names (synthetic logs) -> <stem>.tower.csv."""
    d, b = os.path.split(halo_path)
    if b.startswith('halo_'):
        return os.path.join(d, 'tower_' + b[len('halo_'):])
    return os.path.splitext(halo_path)[0] + '.tower.csv'


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return float('nan')


def gap_text(ms):
    """native/src/tower_model.cpp race_gap_text: one decimal, cut; minutes from 60 s."""
    tenths = int(ms) // 100
    if tenths < 600:
        return f'+{tenths // 10}.{tenths % 10}'
    return f'+{tenths // 600}:{(tenths % 600) // 10:02d}.{tenths % 10}'


def checked_letter(tok):
    """A tyre token's letter after the visual-byte cross-check ('' when the read is not state 1 or disagrees)."""
    if not tok or tok[0] != '1':
        return ''
    p = tok.split('.')
    if len(p) != 7:
        return ''
    vis, enum = int(p[3]), int(p[5])
    return LETTER_OF.get(enum, '') if VISUAL_OF.get(enum) == vis else ''


class TowerLog:
    SCALARS = ('t', 'frame', 'generation', 'session', 'on', 'mode', 'rows', 'start', 'count', 'player', 'pidx', 'held',
               'lead', 'hs', 'lapna', 'cls_ok', 'cls_n', 'holes', 'dups', 'sorted', 'entries', 't_ok', 't_entries',
               'pit_ok', 'laps_ok', 'sc', 'sc_extra', 'pen_ok', 'pen_n', 'pen_seq', 'mc_ok', 'read_us', 'model_us',
               'publish_us', 'writes', 'halo_writes', 'copies', 'jobs', 'dropped', 'red', 'psec', 'fseq')

    def __init__(self, rows):
        self.recs, self.n = rows, len(rows)
        for k in self.SCALARS:
            setattr(self, k, np.array([num(r.get(k)) for r in rows]))
        n = self.n
        self.pos = np.full((n, TOWER_CARS), np.nan)
        self.laps = np.full((n, TOWER_CARS), np.nan)
        self.tpen = np.full((n, TOWER_CARS), np.nan)
        self.status = np.full((n, TOWER_CARS), np.nan)
        self.pit = np.full((n, TOWER_CARS), np.nan)
        self.gl, self.gi = np.full((n, TOWER_CARS), np.nan), np.full((n, TOWER_CARS), np.nan)
        self.glv = np.full((n, TOWER_CARS), -1, dtype=np.int8)
        self.giv = np.full((n, TOWER_CARS), -1, dtype=np.int8)
        self.slow = np.zeros(n, dtype=bool)
        self.tyre = [None] * n
        self.dt = np.full((n, TOWER_CARS), np.nan)
        self.sg = np.full((n, TOWER_CARS), np.nan)
        self.warn = np.full((n, TOWER_CARS, 2), np.nan)
        for i, r in enumerate(rows):
            for key, arr in (('pos', self.pos), ('laps', self.laps), ('tpen', self.tpen)):
                for v, tok in enumerate(r[key].split(' ')[:TOWER_CARS]):
                    if tok not in ('-', ''):
                        arr[i, v] = num(tok)
            for key, arr, base in (('status', self.status, 10), ('pit', self.pit, 16)):
                for v, ch in enumerate(r[key][:TOWER_CARS]):
                    if ch != '-':
                        arr[i, v] = int(ch, base)
            for key, ms, fl in (('gl', self.gl, self.glv), ('gi', self.gi, self.giv)):
                for v, tok in enumerate(r[key].split(' ')[:TOWER_CARS]):
                    if len(tok) > 1:
                        ms[i, v] = num(tok[:-1])
                        fl[i, v] = 1 if tok[-1] == 'v' else 0
            if r['tyre'] != '-':
                self.slow[i] = True
                self.tyre[i] = r['tyre'].split(' ')[:TOWER_CARS]
                for key, arr in (('dt', self.dt), ('sg', self.sg)):
                    for v, ch in enumerate(r[key][:TOWER_CARS]):
                        if ch.isdigit():
                            arr[i, v] = int(ch)
                for v, tok in enumerate(r['warn'].split(' ')[:TOWER_CARS]):
                    if '/' in tok:
                        a, b = tok.split('/')
                        self.warn[i, v] = (num(a), num(b))
        self.race = np.isin(self.session, RACE_TYPES)
        self.timed = (self.session >= 1) & (self.session <= 14)
        # flags (leaves v3, 2026-11-09): absent from older logs
        self.has_flags = bool(rows) and 'zones' in rows[0]
        self.zones = [r.get('zones') or '-' for r in rows]
        self.fshown = [r.get('fshown') or '-' for r in rows]
        self.ysec = [r.get('ysec') or '-' for r in rows]
        # team badges (leaves v4, 2026-11-09): absent from older logs
        self.has_badges = bool(rows) and 'bdg' in rows[0]
        self.bdg = [r.get('bdg') or '' for r in rows]
        self.rbdg = [r.get('rbdg') or '' for r in rows]
        self.bdgkeys = [r.get('bdgkeys') or '-' for r in rows]
        self.bdgvec = [r.get('bdgvec') or '' for r in rows]   # since 2026-11-09; absent before
        # vehicle ids by classification position (unclassified last)
        self.order = np.argsort(np.where(np.isnan(self.pos), np.inf, self.pos), axis=1, kind='stable')


def tower_found(rep, T):
    # older logs have fewer letters (no marshal zones / red flag before leaves v3): those systems are not judged
    width = min(len(SYSTEMS), min((len(r['found']) for r in T.recs), default=0))
    systems = SYSTEMS[:width]

    def share(mask):
        idx = np.nonzero(mask)[0]
        if not len(idx):
            return None
        return [sum(T.recs[i]['found'][k] != '.' for i in idx) / len(idx) for k in range(width)]
    race, timed = share(T.race), share(T.timed)
    drop = int(np.nanmax(T.dropped)) if T.n else 0
    if race is None:
        rep.verdict(TOWER_FIELDS[0], 'NO DATA', 'no race records in the tower log', 'drive a race (test-drive.md)')
        return
    low = [name for (_c, name), s in zip(systems, race) if s < 0.95]
    ev = 'race records: ' + ', '.join(f'{name} {pct(s)}' for (_c, name), s in zip(systems, race))
    if timed is not None:
        ev += '; practice / qualifying records: ' + ', '.join(f'{name} {pct(s)}' for (_c, name), s in zip(systems, timed))
    if width < len(SYSTEMS):
        ev += '; not in this log (older build): ' + ', '.join(name for _c, name in SYSTEMS[width:])
    ev += f'; {drop} tower records dropped'
    rep.verdict(TOWER_FIELDS[0], 'FAIL' if low else 'PASS', ev,
                f'not found in race records: {", ".join(low)} (registry key or build)' if low else '')


TIMING_LIVE_S = 3.0   # the order and gap identities are judged only while the game's timing moves


def timing_live(T):
    """Records in which some car's leader gap, interval or position changed within the last TIMING_LIVE_S seconds (a
    new generation counts as a change). In the 2026-11-09 race logs a paused game froze all timing for up to 300 s and
    a red flag froze the classification for 276 s; counting every record of such a stretch counted one frozen moment
    hundreds of times (one car passed just before a pause showed up as 1000 order 'errors')."""
    X = np.concatenate([T.gl, T.gi, T.pos], axis=1)
    same = ((X[1:] == X[:-1]) | (np.isnan(X[1:]) & np.isnan(X[:-1]))).all(axis=1)
    changed = np.concatenate(([True], ~same | (T.generation[1:] != T.generation[:-1])))
    last = np.maximum.accumulate(np.where(changed, np.arange(T.n), 0))
    return T.t - T.t[last] <= TIMING_LIVE_S


def green_racing(T):
    """Records outside SC / VSC / red flag. Under a safety car the game's interval is not the difference of the leader
    gaps (2026-11-09 16:39 log: 74 % within 1 s, median 333 ms), and a red flag freezes a classification that its gaps
    contradict. Older logs have no red flag column; their red flags read as SC byte 1 (field-traces.md §7)."""
    g = ~np.isin(T.sc, (1, 2))
    if T.has_flags:
        g &= ~red_signal(T)
    return g


def tower_cls(rep, T):
    # race records, leaving out a session being torn down (no results entries and the tower off: quitting the race
    # logged 34 such records in the 2026-11-09 17:44 log)
    teardown = T.race & (T.entries == 0) & (T.on != 1)
    m = T.race & ~teardown
    ok = m & (T.cls_ok == 1)
    if not ok.any():
        rep.verdict(TOWER_FIELDS[1], 'NO DATA', 'no valid classification read in a race', 'drive a race')
        return
    ok_share = ok.sum() / m.sum()
    torn = int((m & (T.dups > 0)).sum())
    holes = int((ok & (T.holes > 0)).sum())
    sorted_share = float((T.sorted[ok] == 1).mean())
    # independent: the timing system's gaps to the leader must grow down the results order (green racing, timing live)
    timed, live, green = ok & (T.t_ok == 1), timing_live(T), green_racing(T)
    frozen, neutral = int((timed & ~live).sum()), int((timed & live & ~green).sum())
    I = np.nonzero(timed & live & green)[0]
    o = T.order[I]
    g = np.take_along_axis(T.gl[I], o, 1)
    gv = np.take_along_axis(T.glv[I], o, 1)
    st = np.take_along_axis(T.status[I], o, 1)
    pv = np.take_along_axis(T.pos[I], o, 1)
    pair = ((gv[:, :-1] == 1) & (gv[:, 1:] == 1) & (st[:, :-1] == 2) & (st[:, 1:] == 2) & np.isfinite(pv[:, 1:]) &
            np.isfinite(pv[:, :-1]))
    viol = pair & (g[:, 1:] < g[:, :-1] - 1000)
    pairs, bad = int(pair.sum()), int(viol.sum())
    ev = (f'valid in {pct(ok_share)} of race records ({torn} torn reads, {holes} with holes; {int(teardown.sum())} '
          f'records of a session being torn down left out); the game\'s sorted list '
          f'agrees in {pct(sorted_share)}; gap to the leader grows down the order in {pairs - bad} of {pairs} '
          f'neighbour pairs (both running, both flags valid, 1 s tolerance; green-flag records with the timing moving: '
          f'{frozen} frozen records - game paused or classification frozen - and {neutral} under SC / VSC / red flag '
          f'left out)')
    if pairs < 100:
        rep.verdict(TOWER_FIELDS[1], 'NO DATA', ev, 'race at least two laps with the gaps valid')
        return
    good = ok_share >= 0.99 and sorted_share >= 0.99 and bad <= 0.02 * pairs
    rep.verdict(TOWER_FIELDS[1], 'PASS' if good else 'FAIL', ev,
                '' if good else 'positions disagree with the game\'s own order or gaps: check the results offsets')


def tower_gaps(rep, T):
    m = T.race & (T.cls_ok == 1) & (T.t_ok == 1)
    if not m.any():
        rep.verdict(TOWER_FIELDS[2], 'NO DATA', 'no race records with timing and classification', 'drive a race')
        return
    I = np.nonzero(m)[0]
    o = T.order[I]
    gl = np.take_along_axis(T.gl[I], o, 1)
    gi = np.take_along_axis(T.gi[I], o, 1)
    glv = np.take_along_axis(T.glv[I], o, 1)
    giv = np.take_along_axis(T.giv[I], o, 1)
    pv = np.take_along_axis(T.pos[I], o, 1)
    # identity: interval = own gap to the leader - the car ahead's (the leader's own counts as 0)
    ahead = np.zeros_like(gl)
    ahead_ok = np.zeros(gl.shape, dtype=bool)
    ahead[:, 1:] = np.where(pv[:, :-1] == 1, 0.0, gl[:, :-1])
    ahead_ok[:, 1:] = (pv[:, :-1] == 1) | (glv[:, :-1] == 1)
    use = (giv == 1) & (glv == 1) & ahead_ok & np.isfinite(pv) & (pv >= 2)
    judged = (timing_live(T) & green_racing(T))[I]   # the identity: green racing with the timing moving (timing_live)
    left_out = int((~judged).sum())
    err = np.abs(gi - (gl - ahead))[use & judged[:, None]]
    # the leader: no car ahead (interval flag 0) and the reference of the leader gap (flag 0)
    lead = pv[:, 0] == 1
    lead_x = float(((glv[lead, 0] == 0) & (giv[lead, 0] == 0)).mean()) if lead.any() else float('nan')
    # pit lane / garage: the game clears both flags (pit states 2-7, 14-15)
    pit = np.isin(T.pit[I], list(CLEARS_GAP))
    have = (T.glv[I] >= 0) & (T.giv[I] >= 0)
    pit_n = int((pit & have).sum())
    pit_x = float(((T.glv[I] == 0) & (T.giv[I] == 0))[pit & have].mean()) if pit_n else float('nan')
    out = np.isin(T.status[I], (5, 7)) & have
    out_x = float(((T.glv[I] == 0) & (T.giv[I] == 0))[out].mean()) if out.any() else float('nan')
    # lapped cars: running, outside the pits, flag cleared, the leader a lap or more ahead on the game's counters
    lead_vid = T.order[I, 0]
    lead_lap = T.laps[I, lead_vid]
    lapped = ((T.status[I] == 2) & (T.glv[I] == 0) & ~np.isin(T.pit[I], list(IN_PIT)) &
              (lead_lap[:, None] - T.laps[I] >= 1))
    lapped_cars = sorted({int(v) for v in np.nonzero(lapped)[1]})
    # the race start: the first valid flag of each race generation
    starts = []
    for gen in np.unique(T.generation[m]):
        gi_ = np.nonzero(m & (T.generation == gen))[0]
        anyv = (T.glv[gi_] == 1).any(axis=1) | (T.giv[gi_] == 1).any(axis=1)
        if anyv.any():
            starts.append(float(T.t[gi_[np.argmax(anyv)]] - T.t[gi_[0]]))
    ev = (f'interval = own leader gap - the car ahead\'s in {pct(float((err <= 1000).mean()) if len(err) else float("nan"))} '
          f'of {len(err)} samples (median error {np.median(err) if len(err) else float("nan"):.0f} ms; {left_out} records '
          f'paused, frozen or under SC / VSC / red flag left out); leader\'s flags '
          f'cleared in {pct(lead_x)}; both flags cleared in the pit lane in {pct(pit_x)} of {pit_n} samples; for '
          f'retired / disqualified cars in {pct(out_x)}; lapped cars seen: {", ".join(map(str, lapped_cars)) or "none"}; '
          f'first valid flag {", ".join(f"{s:.1f} s" for s in starts) or "never"} after the race log starts')
    if len(err) < 100:
        rep.verdict(TOWER_FIELDS[2], 'NO DATA', ev, 'race at least two laps')
        return
    core = np.median(err) <= 300 and (err <= 1000).mean() >= 0.9 and lead_x >= 0.99
    rules = (math.isnan(pit_x) or pit_x >= 0.9) and (math.isnan(out_x) or out_x >= 0.95)
    if not (core and rules):
        rep.verdict(TOWER_FIELDS[2], 'FAIL', ev, 'the gap / interval offsets or the flag rules (field-traces.md §6) '
                    'disagree with the game')
    elif not pit_n:
        rep.verdict(TOWER_FIELDS[2], 'NO DATA', ev, 'make one pit stop: the pit-lane rule was not exercised')
    else:
        rep.verdict(TOWER_FIELDS[2], 'PASS', ev, 'compare a few gaps with the game\'s own timing screen (test-drive.md)')


def tower_settle(T, settled):
    """[(generation, start t, settled t)] for the tyre-change check: the halo log's settle windows when it was read,
    else a fixed SETTLE_TOWER_S after each generation change in the tower log (its first generation is not a change)
    and after each restart (the leader's lap counter going back)."""
    if settled is not None:
        return [(g, a, b) for g, a, b, _cause in settled]
    out = []
    if not T.n:
        return out
    lead = np.nanmax(np.where(np.isfinite(T.laps), T.laps, -1), axis=1)
    for i in range(1, T.n):
        if T.generation[i] != T.generation[i - 1] and T.generation[i] != T.generation[0]:
            out.append((T.generation[i], float(T.t[i]), float(T.t[i]) + SETTLE_TOWER_S))
        elif T.generation[i] == T.generation[i - 1] and 0 <= lead[i] < lead[i - 1] - 0.5:
            out.append((T.generation[i], float(T.t[i]), float(T.t[i]) + SETTLE_TOWER_S))
    return out


def tower_tyres(rep, T, settled=None):
    agree = total = stale = unavail = skipped = 0
    windows = tower_settle(T, settled)
    seen_vis, seen_enum = Counter(), Counter()
    changes, near_pit = [], 0
    last = {}
    pit_t = defaultdict(list)                     # vid -> times in the pit lane (10 Hz)
    for v in range(TOWER_CARS):
        pit_t[v] = T.t[np.isin(T.pit[:, v], list(IN_PIT))]
    for i in np.nonzero(T.slow)[0]:
        inside = [w for w in windows if w[0] == T.generation[i] and w[1] <= T.t[i]]
        if any(T.t[i] < b for _g, _a, b in inside):
            skipped += 1
            continue
        part = len(inside)                         # letters are compared within one stretch between restarts
        for v, tok in enumerate(T.tyre[i]):
            if tok in ('', '-', '0'):
                continue
            if tok == '2':
                stale += 1
                continue
            if tok == '3':
                unavail += 1
                continue
            p = tok.split('.')
            if len(p) != 7:
                continue
            vis, enum = int(p[3]), int(p[5])
            seen_vis[vis] += 1
            seen_enum[enum] += 1
            if enum in VISUAL_OF:
                total += 1
                agree += VISUAL_OF[enum] == vis
            letter = checked_letter(tok)
            key = (v, T.generation[i], T.session[i], part)
            if letter and key in last and last[key][1] != letter:
                t0, t1 = last[key][0], T.t[i]
                pt = pit_t[v]
                ok = bool(((pt >= t1 - PIT_WINDOW_S) & (pt <= t1)).any())
                near_pit += ok
                changes.append((v, last[key][1], letter, float(t1), ok))
            if letter:
                last[key] = (T.t[i], letter)
    if not total:
        rep.verdict(TOWER_FIELDS[3], 'NO DATA', 'no tyre read with a lettered compound', 'drive on track with the tower on')
        return
    allr = total + stale + unavail
    letters = ', '.join(f'{LETTER_OF[e]} {n}' for e, n in sorted(seen_enum.items()) if e in LETTER_OF)
    ev = (f'visual byte agrees with the compound enum in {agree} of {total} reads ({letters}; visual ids '
          f'{", ".join(f"{k}" for k in sorted(seen_vis))}); {len(changes)} letter changes, {near_pit} after a pit-lane '
          f'visit; stale cache {pct(stale / allr)}, unavailable {pct(unavail / allr)} of reads')
    if skipped:
        ev += f'; {skipped} tyre records in settle windows after generation changes and restarts left out'
    away = [c for c in changes if not c[4]]
    if away:
        ev += '; changes away from the pits: ' + ', '.join(f'car {v} {a}->{b} at {t:.1f} s' for v, a, b, t, _ in away[:5])
    good = agree >= 0.999 * total and not away and unavail <= 0.05 * allr
    rep.verdict(TOWER_FIELDS[3], 'PASS' if good else 'FAIL', ev,
                'compare the letters with the game\'s tyre icons at the start and after the stop (test-drive.md)' if good
                else 'the tyre chain (field-traces.md §1) reads another field')


def tower_sc(rep, T):
    m = T.race
    if not m.any():
        rep.verdict(TOWER_FIELDS[4], 'NO DATA', 'no race records', 'drive a race with safety cars set to increased')
        return
    found = np.array([T.recs[i]['found'][3] == 'S' for i in range(T.n)])
    unread = float((T.sc[m & found] == -1).mean()) if (m & found).any() else float('nan')
    values = Counter(int(x) for x in T.sc[m])
    periods, flaps = [], []
    # the game also sets the SC byte to 1 during a red flag (in-game log 2026-11-09 16:39): those records belong to
    # the red flag (Tower: red flag), and an SC run that touches one is not a flap
    red_all = red_signal(T) if T.has_flags else np.isin(T.red, (1, 2))
    for gen in np.unique(T.generation[m]):
        idx = np.nonzero(m & (T.generation == gen))[0]
        sc, red = T.sc[idx], red_all[idx]
        for val, name in ((1, 'SC'), (2, 'VSC'), (3, 'formation')):
            for a, b in runs((sc == val) & ~red):
                dur = float(T.t[idx[b]] - T.t[idx[a]]) + 0.1
                if dur < 5.0 and ((0 < a and red[a - 1]) or (b < len(idx) - 1 and red[b + 1])):
                    continue                       # the SC byte rose a read before the red flag byte (4 Hz)
                periods.append((float(T.t[idx[a]]), float(T.t[idx[b]]), name, dur))
                if val in (1, 2) and dur < 5.0 and 0 < a and b < len(idx) - 1:
                    flaps.append((name, float(T.t[idx[a]]), dur))
    periods.sort()
    ev = (f'SC byte values in race records: {", ".join(f"{k}: {n}" for k, n in sorted(values.items()))}; unreadable '
          f'in {pct(unread)} of records with the system found; periods: ' +
          (', '.join(f'{name} {a:.1f}-{b:.1f} s' for a, b, name, _d in periods) or 'none'))
    if (m & red_all & (T.sc == 1)).any():
        ev += f'; SC byte 1 in {int((m & red_all & (T.sc == 1)).sum())} red-flag records (judged by Tower: red flag)'
    if flaps:
        ev += '; shorter than 5 s: ' + ', '.join(f'{n} at {t:.1f} s ({d:.1f} s)' for n, t, d in flaps[:5])
    bad = bool(flaps) or (not math.isnan(unread) and unread > 0.01)
    if bad:
        rep.verdict(TOWER_FIELDS[4], 'FAIL', ev, 'the byte at +0x108 does not behave like the race state')
    elif not any(p[2] in ('SC', 'VSC') for p in periods):
        rep.verdict(TOWER_FIELDS[4], 'NO DATA', ev, 'no SC or VSC in this drive: safety cars "increased", race until one')
    else:
        rep.verdict(TOWER_FIELDS[4], 'PASS', ev, 'match each period with the game\'s SC / VSC banners (test-drive.md)')


def zone_info(tok):
    """(readable, yellow zones, their sectors, a yellow zone without a sector) from a log 'zones' token: one char per
    zone, the flag digit, a yellow zone as its sector letter (A = 1) or '?'; '.' an empty list, '-' unreadable."""
    if tok in ('', '-'):
        return False, 0, set(), False
    ys = [ch for ch in tok if ch.isalpha() or ch == '?']
    return True, len(ys), {ord(ch) - ord('A') + 1 for ch in ys if ch.isalpha()}, '?' in ys


def zones_all_red(tok):
    """Every zone of a readable, non-empty 'zones' token at 4 (the red flag in game: 2026-11-09 17:44 log)."""
    return tok not in ('', '-', '.') and set(tok) == {'4'}


def red_signal(T):
    """Records with a red flag source: the red flag byte at 1 or 2, or every marshal zone at 4 (no hold)."""
    return np.isin(T.red, (1, 2)) | np.array([zones_all_red(z) for z in T.zones], dtype=bool)


def flag_replay(T):
    """The model's flag rules (tower_model.cpp) replayed on the logged reads, record by record: expected header state
    (-1 where it cannot be known: a read the log missed, the tower off, the chequered flag), yellow, its sector text,
    the no-sector flag and the red flag. One flags read per new 'fseq'; the yellow is held over one non-yellow read and
    dropped at once on an unreadable list; the red flag needs the red flag byte at 1 or 2, or every zone at 4 (held and
    dropped like the yellow); 4 chequered > 3 red > 1 SC > 2 VSC > 5 yellow."""
    n = T.n
    exp = np.full(n, -1)
    yel = np.zeros(n, dtype=bool)
    redx = np.zeros(n, dtype=bool)
    text_ = ['-'] * n
    na = np.zeros(n, dtype=bool)
    key, seq, y, miss, txt, nas, known, streak = None, None, False, 0, '-', False, False, 0
    zr, zmiss, zknown = False, 0, True
    for i in range(n):
        k = (T.generation[i], T.session[i])
        if k != key or T.on[i] != 1:
            key, seq, y, miss, known, streak = (k if T.on[i] == 1 else None), None, False, 0, False, 0
            zr, zmiss, zknown = False, 0, True
            if T.on[i] != 1:
                continue
        s_ = T.fseq[i]
        if not np.isfinite(s_):
            continue
        if s_ != seq:
            jump = seq is None or s_ != seq + 1    # reads the log did not see: the hold state is unknown
            seq = s_
            ok, ny, secs, unm = zone_info(T.zones[i])
            # the zones' red: held over one other read; after reads the log missed, a held red is unknown for a read
            if not ok:
                zr, zmiss, zknown = False, 0, True
            elif zones_all_red(T.zones[i]):
                zr, zmiss, zknown = True, 0, True
            elif jump:
                zknown = not zr
                zr, zmiss = False, 0
            elif zr and zmiss < 1:
                zmiss, zknown = zmiss + 1, True
            else:
                zr, zmiss, zknown = False, 0, True
            if not ok:
                y, miss, known = False, 0, True
            elif ny:
                y, miss, known = True, 0, True
                nas = unm or not secs
                txt = '-' if nas else '_'.join(str(x) for x in sorted(secs))
            elif jump or not known:
                y, miss = False, 0                  # two non-yellow reads in a row end any hold
                streak = 1 if jump else streak + 1
                known = streak >= 2
            elif y and miss < 1:
                miss += 1
            else:
                y, miss = False, 0
        if not known or not zknown or T.hs[i] == 4:
            continue
        red = T.red[i] in (1, 2) or zr
        race = T.race[i]
        exp[i] = 3 if red else 1 if race and T.sc[i] == 1 else 2 if race and T.sc[i] == 2 else 5 if y else 0
        yel[i] = y
        redx[i] = red
        text_[i] = txt if y else '-'
        na[i] = y and nas
    return exp, yel, text_, na, redx


def flag_runs(T, mask):
    """[(t0, t1, first index, last index)] of runs of mask within one generation."""
    out = []
    for g in np.unique(T.generation):
        idx = np.nonzero(T.generation == g)[0]
        for a, b in runs(mask[idx]):
            out.append((float(T.t[idx[a]]), float(T.t[idx[b]]), int(idx[a]), int(idx[b])))
    return sorted(out)


def flickers(T, state, value):
    """Short runs of the header in `value` between two equal other states, and short gaps out of it between two runs
    of it (both shorter than FLAG_FLICKER_S): what a viewer would see blink."""
    bad = []
    on = T.on == 1
    for g in np.unique(T.generation):
        idx = np.nonzero((T.generation == g) & on)[0]
        if len(idx) < 3:
            continue
        st = state[idx]
        cut = np.nonzero(np.diff(st) != 0)[0]
        seg = np.split(np.arange(len(idx)), cut + 1)
        for k in range(1, len(seg) - 1):
            a, b = seg[k][0], seg[k][-1]
            dur = float(T.t[idx[min(b + 1, len(idx) - 1)]] - T.t[idx[a]])
            prev, nxt, cur = st[seg[k - 1][0]], st[seg[k + 1][0]], st[a]
            if dur < FLAG_FLICKER_S and ((cur == value and prev == nxt) or (cur != value and prev == value == nxt)):
                bad.append(float(T.t[idx[a]]))
    return bad


def tower_flags(rep, T):
    yf, rf = TOWER_FIELDS[9], TOWER_FIELDS[10]
    if not T.has_flags:
        why = 'this tower log has no flag columns (a build before leaves v3)'
        rep.verdict(yf, 'NO DATA', why, 'drive with this build; ' + FLAG_TODO['yellow'])
        rep.verdict(rf, 'NO DATA', why, 'drive with this build; ' + FLAG_TODO['red'])
        return
    on = T.on == 1
    if not on.any():
        rep.verdict(yf, 'NO DATA', 'the tower was never on', 'drive with the Timing tower option on')
        rep.verdict(rf, 'NO DATA', 'the tower was never on', 'drive with the Timing tower option on')
        return
    exp, yel, ytext, na, redx = flag_replay(T)
    hs = T.hs
    known = on & (exp >= 0)
    shown_r = np.array(['r' in x for x in T.fshown])
    shown_y = np.array(['y' in x for x in T.fshown])
    shown_n = np.array(['n' in x for x in T.fshown])
    found_m = np.array([len(r['found']) > 8 and r['found'][8] == 'M' for r in T.recs])
    found_f = np.array([len(r['found']) > 9 and r['found'][9] == 'F' for r in T.recs])
    zinfo = [zone_info(z) for z in T.zones]
    yread = np.array([z[1] > 0 for z in zinfo])
    zread = np.array([z[0] for z in zinfo])

    # --- red: the red flag system's byte or every zone at 4 (the model's hold, replayed); the header must show it over
    # the SC (in game the SC byte reads 1 then). In the 2026-11-09 17:44 log only the zones moved.
    red = redx
    zones_red = int((on & np.array([zones_all_red(z) for z in T.zones], dtype=bool)).sum())
    r_unread = float((T.red[on & found_f] == -1).mean()) if (on & found_f).any() else float('nan')
    r_cmp = known & (hs != 4)
    r_bad = r_cmp & (((hs == 3) != red) | (shown_r != red))
    r_runs = flag_runs(T, red & on)
    r_flick = flickers(T, np.where(red, 1, 0), 1) + flickers(T, np.where(hs == 3, 1, 0), 1)
    seq = []
    for g in np.unique(T.generation[on]):
        vals = T.red[on & (T.generation == g)]
        vals = vals[vals >= 0]
        seq_g = [int(v) for k, v in enumerate(vals) if k == 0 or v != vals[k - 1]]
        if len(seq_g) > 1:
            seq.append('→'.join(map(str, seq_g)))
    under_sc = int((red & on & (T.sc == 1)).sum())
    ev = (f'red flag byte {", ".join(f"{int(k)}: {int(v)}" for k, v in sorted(Counter(T.red[on].tolist()).items()))} '
          f'records; unreadable in {pct(r_unread)} of records with the system found; periods: ' +
          (', '.join(f'{a:.1f}–{b:.1f} s' for a, b, _i, _j in r_runs) or 'none') +
          (f'; sequence {"; ".join(seq)}' if seq else '') +
          f'; every marshal zone at 4 in {zones_red} records'
          f'; header red where the byte or the zones say so in {int((r_cmp & ~r_bad & red).sum())} of '
          f'{int((r_cmp & red).sum())} records, {int(r_bad.sum())} disagreeing records in all; SC byte 1 in {under_sc} '
          f'red-flag records (the header must still say red)')
    if r_flick:
        ev += '; flicker at ' + ', '.join(f'{x:.1f} s' for x in r_flick[:5])
    if not (red & on).any():
        rep.verdict(rf, 'FAIL' if r_bad.any() else 'NO DATA', ev, FLAG_TODO['red'] if not r_bad.any() else
                    'the header showed the red flag without the red flag byte or every zone at 4')
    else:
        bad = r_bad.sum() > 0.01 * max(int(r_cmp.sum()), 1) or bool(r_flick) or (not math.isnan(r_unread) and r_unread > 0.01)
        rep.verdict(rf, 'FAIL' if bad else 'PASS', ev,
                    'the header does not follow the red flag byte / every zone at 4 with the priority red > SC '
                    '(field-traces.md §7.8)'
                    if bad else 'match the period with the game\'s RED FLAG box (test-drive.md, Flags)')

    # --- yellow: the marshal zones; the header must follow the zones with the hold and the priority
    z_unread = float((~zread[on & found_m]).mean()) if (on & found_m).any() else float('nan')
    involved = known & (yel | (hs == 5) | shown_y)
    y_hs = involved & (hs != exp) & (exp != 3)   # where red is expected, the red check judges the header
    y_bool = known & ((shown_y != yel) | (shown_n != na))
    y_text = known & yel & (np.array(T.ysec) != np.array(ytext))
    y_bad = y_hs | y_bool | y_text
    y_runs = flag_runs(T, yread & on)
    y_flick = flickers(T, np.where(hs == 5, 1, 0), 1)
    parts = []
    for a, b, i, j in y_runs[:8]:
        secs = set().union(*(zinfo[k][2] for k in range(i, j + 1)))
        unm = any(zinfo[k][3] for k in range(i, j + 1))
        ps = Counter(int(x) for x in T.psec[i:j + 1] if np.isfinite(x) and x > 0)
        parts.append(f'{a:.1f}–{b:.1f} s sector {"/".join(map(str, sorted(secs))) or "?"}' + (' (+ unmapped)' if unm else '') +
                     (f', player in sector {ps.most_common(1)[0][0]}' if ps else ''))
    hidden = int((known & yel & np.isin(exp, (1, 2, 3))).sum())
    ev = (f'yellow zones read in {int((yread & on).sum())} records, list unreadable in {pct(z_unread)} of records with '
          f'the system found; periods: {"; ".join(parts) or "none"}; header yellow in {int((known & (hs == 5)).sum())} '
          f'records, {hidden} yellow records under SC / VSC / red (the higher state shown); {int(y_hs.sum())} records '
          f'with the wrong header, {int(y_bool.sum())} with the wrong yellow bools, {int(y_text.sum())} with the wrong '
          f'sector text')
    if y_flick:
        ev += '; flicker at ' + ', '.join(f'{x:.1f} s' for x in y_flick[:5])
    if not (yread & on).any():
        rep.verdict(yf, 'FAIL' if y_bad.any() else 'NO DATA', ev, FLAG_TODO['yellow'] if not y_bad.any() else
                    'the header showed a yellow without a yellow zone')
    else:
        bad = (y_bad.sum() > 0.01 * max(int(involved.sum()), 1) or bool(y_flick) or
               (not math.isnan(z_unread) and z_unread > 0.05))
        rep.verdict(yf, 'FAIL' if bad else 'PASS', ev,
                    'the header does not follow the zone flags with the hold and the priority 3 > 1 > 2 > 5 '
                    '(field-traces.md §7.8)' if bad else
                    'match each period with the game\'s CAUTION box and its sector (test-drive.md, Flags)')


def pen_lists(T):
    """(t, generation, [record tuples]) at every logged change of the penalty log."""
    out = []
    for i, r in enumerate(T.recs):
        s = r.get('pen_recs', '-')
        if s in ('-', ''):
            continue
        recs = [] if s == '0' else [tuple(int(x) for x in q.split(':')) for q in s.split(';')]
        out.append((float(T.t[i]), T.generation[i], recs))
    return out


def pen_restarts(lists):
    """Times at which the game cleared its whole penalty log within one car set: a restarted session (the car set
    may survive a restart). Only when the old records never come back: a list that reads empty and then returns
    with its old records is a bad read, and tower_penalties fails it."""
    out = []
    prev, prev_gen = [], None
    for k, (t, gen, recs) in enumerate(lists):
        if gen == prev_gen and prev and not recs:
            nxt = next((r for _t, g, r in lists[k + 1:] if g == gen and r), None)
            if nxt is None or nxt[0] != prev[0]:
                out.append(t)
        prev, prev_gen = recs, gen
    return out


def tower_penalties(rep, T):
    lists = pen_lists(T)
    restarts = pen_restarts(lists)
    issues, notes = [], []
    prev, prev_gen = [], None
    new, before = [], 0
    for t, gen, recs in lists:
        if gen != prev_gen:              # the first list of a car set: issued before the log saw them, not judged
            prev, prev_gen = recs, gen
            before += len(recs)
            continue
        if t in restarts:                # a restarted session starts an empty log: what follows is judged afresh
            prev = recs
            continue
        if recs[:len(prev)] != prev and len(recs) <= 96:
            issues.append(f'records changed or vanished at {t:.1f} s')
        new += [(t, r) for r in recs[len(prev):]]
        prev = recs
    slow = np.nonzero(T.slow)[0]
    checked = 0
    for t, r in new:
        vid, typ, _reason, secs = r[0], r[1], r[2], r[3]
        if vid >= TOWER_CARS or typ not in (0, 1, 4):
            continue
        checked += 1
        name = {0: 'drive-through', 1: 'stop-go', 4: f'{secs} s time penalty'}[typ]
        if typ in (0, 1):
            arr = T.dt if typ == 0 else T.sg
            after = [i for i in slow if t <= T.t[i] <= t + 5.0]
            if not any(arr[i, vid] >= 1 for i in after):
                issues.append(f'{name} for car {vid} at {t:.1f} s never showed as pending')
                continue
            later = [i for i in slow if T.t[i] > t + 5.0 and T.generation[i] == T.generation[after[0]]]
            served = next((T.t[i] for i in later if arr[i, vid] == 0), None)
            notes.append(f'{name} for car {vid} at {t:.1f} s: pending' +
                         (f', cleared at {served:.1f} s (served?)' if served is not None else ', still pending at the end'))
        else:
            # the total may rise a read before the record lands (2026-11-09 17:44 log: 0.1 s): compare from 1 s before
            pre = T.tpen[(T.t < t - 1.0) & (T.t >= t - 5.0), vid]
            post = T.tpen[(T.t >= t - 1.0) & (T.t <= t + 5.0), vid]
            b = pre[np.isfinite(pre)][-1] if np.isfinite(pre).any() else 0.0
            a = np.nanmax(post) if np.isfinite(post).any() else float('nan')
            if not (math.isfinite(a) and abs(a - b - secs) < 0.01):
                issues.append(f'{name} for car {vid} at {t:.1f} s: total {b:g} -> {a:g} s')
                continue
            # open question (field-traces.md §3b): does the total drop once the penalty is served at a stop?
            late = T.t > t + 5.0
            tail, tail_t = T.tpen[late, vid], T.t[late]
            low = np.nonzero(np.isfinite(tail) & (tail < a - 0.01))[0]
            if not len(low):
                why = '; kept to the end of the log'
            else:
                td = float(tail_t[low[0]])
                if any(abs(td - r) <= 1.0 for r in restarts):
                    why = f'; cleared at {td:.1f} s by the session restart'
                else:
                    stop = bool(np.isin(T.pit[(T.t >= td - 60.0) & (T.t <= td), vid], list(IN_PIT)).any())
                    why = f'; it dropped at {td:.1f} s' + (' after a pit stop (served there)' if stop else
                                                         ', with no pit stop in the minute before')
            notes.append(f'{name} for car {vid} at {t:.1f} s: total {b:g} -> {a:g} s' + why)
    ev = (f'{len(lists)} logged changes, {before} records before the log, {len(new)} new records, {checked} '
          f'drive-through / stop-go / time penalties: ' +
          ('; '.join(notes) if notes else 'none'))
    if restarts:
        ev += '; log cleared (session restart) at ' + ', '.join(f'{t:.1f} s' for t in restarts)
    if issues:
        ev += '; problems: ' + '; '.join(issues[:5])
        rep.verdict(TOWER_FIELDS[5], 'FAIL', ev, 'the penalty chain (field-traces.md §3) disagrees with itself')
    elif not checked:
        rep.verdict(TOWER_FIELDS[5], 'NO DATA', ev, 'strict penalties: cut corners until the game gives a time penalty')
    else:
        rep.verdict(TOWER_FIELDS[5], 'PASS', ev, 'match each record with the game\'s penalty messages (test-drive.md)')


def tower_warnings(rep, T):
    slow = np.nonzero(T.slow)[0]
    restarts = pen_restarts(pen_lists(T))   # a restarted session clears the log, and the counts with it
    drops, final = [], {}
    prev = {}
    last_t, seg = -math.inf, 0
    for i in slow:
        if any(last_t < r <= T.t[i] for r in restarts):
            prev, seg = {}, seg + 1
        last_t = T.t[i]
        key0 = (T.generation[i], T.session[i], seg)
        for v in range(TOWER_CARS):
            w = T.warn[i, v]
            if not np.isfinite(w).all():
                continue
            key = key0 + (v,)
            if key in prev and (w[0] < prev[key][0] or w[1] < prev[key][1]):
                drops.append(f'car {v} {int(prev[key][0])}/{int(prev[key][1])} -> {int(w[0])}/{int(w[1])} at {T.t[i]:.1f} s')
            prev[key] = w
            if w[0] > 0:
                final[key] = w
    players = {(int(T.generation[i]), int(T.session[i])): int(T.player[i]) for i in slow if T.player[i] >= 0}
    mine = [f'session {int(s)}{" after a restart" if sg else ""}: {int(w[0])} warnings ({int(w[1])} track limits)'
            for (g, s, sg, v), w in sorted(final.items()) if players.get((int(g), int(s))) == v]
    cars = sorted({k[3] for k in final})
    ev = f'cars with warnings: {", ".join(map(str, cars)) or "none"}; the player: {"; ".join(mine) or "none"}; '
    ev += f'counts fell: {"; ".join(drops[:5])}' if drops else 'counts never fall'
    if restarts:
        ev += ' (counted afresh after the session restart at ' + ', '.join(f'{t:.1f} s' for t in restarts) + ')'
    if drops:
        rep.verdict(TOWER_FIELDS[6], 'FAIL', ev, 'the warning count must only grow within a session')
    elif not final:
        rep.verdict(TOWER_FIELDS[6], 'NO DATA', ev, 'cut a corner three times in qualifying')
    else:
        rep.verdict(TOWER_FIELDS[6], 'PASS', ev, 'match the player\'s count with the game\'s warning messages')


def expected_row(T, i, idx, settings):
    """What native/src/tower_model.cpp shows for classification index idx in record i: (kind, text, tyre, flags)."""
    vid = int(T.order[i, idx])
    st = T.status[i, vid]
    race = T.session[i] in RACE_TYPES
    lead = T.lead[i] == 1
    out = st in (4, 5, 6, 7)
    flags = set()
    if out:
        flags.add('o')
    else:
        if T.pit[i, vid] in IN_PIT:
            flags.add('p')
    if T.pos[i, vid] == 1:
        flags.add('1')
    if 'm' in settings and vid == T.player[i]:
        flags.add('m')
    if 'g' not in settings:
        return vid, 0, '', flags
    if out:
        return vid, 5, {5: 'DSQ', 6: 'NC'}.get(int(st), 'Out'), flags
    if not race:
        return vid, 6, '', flags | {'g'}
    if T.pos[i, vid] == 1:
        return vid, 1, 'Leader' if lead else 'Interval', flags
    if T.t_ok[i] != 1 or (T.glv[i, vid] if lead else T.giv[i, vid]) < 0:
        return vid, 6, '', flags | {'g'}
    valid = (T.glv[i, vid] if lead else T.giv[i, vid]) == 1
    ms = T.gl[i, vid] if lead else T.gi[i, vid]
    if valid and st in (2, 3) and 0 <= ms <= 3 * 3600 * 1000:
        return vid, 2, gap_text(ms), flags
    if valid:
        return vid, 6, '', flags | {'g'}
    if T.pit[i, vid] in CLEARS_GAP:
        return vid, 4, 'PIT', flags
    ref = int(T.order[i, 0]) if lead else (int(T.order[i, idx - 1]) if idx > 0 else -1)
    if st == 2 and ref >= 0 and np.isfinite(T.laps[i, ref]) and np.isfinite(T.laps[i, vid]):
        n = int(T.laps[i, ref] - T.laps[i, vid])
        if 1 <= n <= 99:
            return vid, 3, '+1 LAP' if n == 1 else f'+{n} LAPS', flags
    return vid, 6, '', flags | {'g'}


def tower_shown(rep, T):
    on = (T.on == 1) & (T.held == 0)
    if not on.any():
        rep.verdict(TOWER_FIELDS[7], 'NO DATA', 'the tower was never on', 'drive with the Timing tower option on')
        return
    rows_n = bad = 0
    examples = []
    window_bad = header_bad = arrows_bad = arrows_n = 0
    last_change = {}                               # (generation, vid) -> (t, +1 better / -1 worse)
    prev_pos = {}
    for i in range(T.n):
        g = T.generation[i]
        if T.cls_ok[i] == 1:
            for v in range(TOWER_CARS):
                p = T.pos[i, v]
                if np.isfinite(p):
                    if (g, v) in prev_pos and prev_pos[(g, v)] != p:
                        last_change[(g, v)] = (T.t[i], 1 if p < prev_pos[(g, v)] else -1)
                    prev_pos[(g, v)] = p
        if not on[i]:
            continue
        settings = T.recs[i].get('set') or 'htagcm'
        toks = [] if T.recs[i]['shown'] == '-' else T.recs[i]['shown'].split(' ')
        count, rows, start, pidx = int(T.count[i]), int(T.rows[i]), int(T.start[i]), int(T.pidx[i])
        mode = int(T.mode[i])
        if mode == 1 and pidx >= 0:
            want_start = min(max(pidx - rows // 2, 0), count - rows)
        else:
            want_start = 0
        if len(toks) != rows or start != want_start or (mode == 0 and rows != min(count, 22)):
            window_bad += 1
            if len(examples) < 5:
                examples.append(f'{T.t[i]:.1f} s: window start {start} rows {rows} ({len(toks)} shown), want start {want_start}')
            continue
        if T.session[i] in RACE_TYPES and 'h' in settings:
            lead_vid = int(T.order[i, 0])
            if T.pos[i, lead_vid] == 1 and np.isfinite(T.laps[i, lead_vid]):
                want = int(T.laps[i, lead_vid]) + (0 if T.status[i, lead_vid] == 3 else 1)
                got = T.recs[i]['lap']
                if want >= 1 and got != str(want):
                    header_bad += 1
                    if len(examples) < 5:
                        examples.append(f'{T.t[i]:.1f} s: header lap {got}, want {want}')
        for k, tok in enumerate(toks):
            rows_n += 1
            # vid:pos:kind:gap:tyre:flags, where a gap of a minute or more has a colon of its own (+1:01.0)
            p = tok.split(':', 3)
            q = p[3].rsplit(':', 2) if len(p) == 4 else []
            vid, kind, text_, flags = expected_row(T, i, start + k, settings)
            if len(q) < 2:
                bad += 1
                if len(examples) < 5:
                    examples.append(f'{T.t[i]:.1f} s row {k}: unreadable token {tok}')
                continue
            got_vid, got_pos, got_kind, got_gap, got_tyre = int(p[0]), int(p[1]), int(p[2]), q[0], q[1]
            got_flags = set(q[2]) if len(q) > 2 else set()
            want_gap = text_.replace(' ', '_') or '-'
            core_flags = {'o', 'p', '1', 'm', 'g'}
            ok = (got_vid == vid and got_pos == int(T.pos[i, vid]) and got_kind == kind and got_gap == want_gap and
                  (got_flags & core_flags) == (flags & core_flags))
            # tyre letter: only on the 1 Hz records that carry the read
            if ok and T.slow[i] and 't' in settings and 'o' not in flags and vid < len(T.tyre[i]):
                want_l = checked_letter(T.tyre[i][vid])
                if want_l:
                    ok = got_tyre == want_l
                elif T.tyre[i][vid] == '2':
                    ok = (got_tyre == '-' and 't' in got_flags) or 'h' in got_flags
                else:
                    ok = got_tyre == '-' and 't' in got_flags
            # arrows: an arrow needs a position change of that car within the last 4 s (plus the log's 0.1 s). Soft:
            # the log samples the 10 Hz reads, so a change and its reversal inside 0.1 s can be missing here
            for f_, d in (('u', 1), ('d', -1)):
                if f_ in got_flags:
                    arrows_n += 1
                    lc = last_change.get((g, vid))
                    if not lc or lc[1] != d or T.t[i] - lc[0] > 4.3:
                        arrows_bad += 1
            if not ok:
                bad += 1
                if len(examples) < 5:
                    examples.append(f'{T.t[i]:.1f} s row {k}: shown {tok}, expected car {vid} '
                                    f'{KIND[kind]} {want_gap} {"".join(sorted(flags))}')
    ev = (f'{rows_n} shown rows in {int(on.sum())} records: {rows_n - bad} as the reads say; window wrong in '
          f'{window_bad} records, header lap wrong in {header_bad}; {arrows_n - arrows_bad} of {arrows_n} arrows follow a '
          f'logged position change')
    if examples:
        ev += '; first: ' + '; '.join(examples)
    good = not bad and not window_bad and not header_bad and arrows_bad <= 0.01 * max(arrows_n, 1)
    rep.verdict(TOWER_FIELDS[7], 'PASS' if good else 'FAIL', ev,
                'compare the tower with the game\'s own leaderboard in a few screenshots (test-drive.md)' if good
                else 'the model (native/src/tower_model.cpp) disagrees with its own reads')


def tower_cost(rep, T):
    m = T.on == 1
    if not m.any():
        rep.verdict(TOWER_FIELDS[8], 'NO DATA', 'the tower was never on', 'drive with the Timing tower option on')
        return
    tot = (T.read_us + T.model_us + T.publish_us)[m]
    w = (T.writes + T.halo_writes)[m]
    mean, p99, mx = float(np.mean(tot)), float(np.percentile(tot, 99)), float(np.max(tot))
    ev = (f'read + model + leaves {mean:.1f} us mean, {p99:.1f} us p99, {mx:.1f} us max per frame (one frame per '
          f'record); leaf writes per frame with the halo\'s {np.mean(w):.1f} mean, {int(np.max(w))} max (queue 64, budget '
          f'56); copies per frame {np.mean(T.copies[m]):.1f} mean, {int(np.max(T.copies[m]))} max; '
          f'{int(np.nanmax(T.dropped))} records dropped')
    good = mean <= 50 and p99 <= 250 and np.max(w) <= 56
    rep.verdict(TOWER_FIELDS[8], 'PASS' if good else 'FAIL', ev, '' if good else 'the tower costs more than budgeted')


BADGE_SETTLE_S = 1.0      # a new car set reads its badges within 0.4 s (six cars per 10 Hz classification run)
BADGE_SHARE = 0.99        # every running classified car has its badge in at least this share of its settled records
BADGE_STEP = {'1': 'game mode context not in the registry', '2': 'the game pointer ([GMC+0x88]+0x260)',
              '3': 'the entrant vector (see bdgvec)', '4': 'no entrant with the vehicle id', '5': 'team kind above 2',
              '6': 'the kind\'s team table', '7': 'index past the table or no record', '8': 'record or key pointer',
              '9': 'key not 1..39 printable characters', '.': 'not read yet', '': 'no column entry'}
# bdgvec (diag_log.cpp): the game's entrant vector at the last badge run, a record count or one of these
BADGE_VEC = {'-': 'not reached', 'u': 'bounds unreadable', 's': 'not sane (or over 1024 records)',
             'c': 'records unreadable'}


def badge_sets(T):
    """Car sets (consecutive records with one generation and session; the reader starts again with each) and their
    letter -> key tables: the union of the bdgkeys listings, which only grow within a car set. Returns the set index
    per record, the tables, the first record of each set and the letters listed with two different keys."""
    seg = np.zeros(T.n, dtype=int)
    tables, first, conflicts = [{}], [0], []
    s = 0
    for i in range(T.n):
        if i and (T.generation[i] != T.generation[i - 1] or T.session[i] != T.session[i - 1] or T.t[i] < T.t[i - 1]):
            s += 1
            tables.append({})
            first.append(i)
        seg[i] = s
        tok = T.bdgkeys[i]
        if tok in ('-', '.', ''):
            continue
        for item in tok.split(' '):
            letter, _, key = item.partition('=')
            key = unquote(key)
            if letter in tables[s] and tables[s][letter] != key:
                conflicts.append(f'{T.t[i]:.1f} s: {letter} = {tables[s][letter]} and {key}')
            tables[s][letter] = key
    return seg, tables, first, conflicts


def tower_badges(rep, T):
    """leaves v4 (field-traces.md §10): every running classified car has its team's badge, a car's badge never
    changes within a session, no badge is on more than two cars (teammates), and every shown row carries its own
    car's badge, also in the records where positions changed."""
    field = TOWER_FIELDS[11]
    if not T.has_badges:
        rep.verdict(field, 'NO DATA', 'a tower log from before leaves v4 (no badge columns)',
                    'drive with this build and the Validation log on')
        return
    seg, tables, first, conflicts = badge_sets(T)
    settled = np.array([T.t[i] - T.t[first[seg[i]]] >= BADGE_SETTLE_S for i in range(T.n)])
    use = settled & (T.cls_ok == 1) & (T.race | T.timed)
    if not use.any():
        rep.verdict(field, 'NO DATA', 'no settled practice, qualifying or race record with a classification',
                    'drive a session with the tower on')
        return
    seen, ok_n, other_n, steps = Counter(), Counter(), Counter(), Counter()
    first_miss = {}
    session_key = {}                   # (session run, vid) -> key
    n_changes, change_examples, crowded, keys_seen = 0, [], [], set()
    run_id, run_no = np.zeros(T.n, dtype=int), 0
    for i in range(1, T.n):
        if T.session[i] != T.session[i - 1] or T.t[i] < T.t[i - 1]:
            run_no += 1
        run_id[i] = run_no
    rows_n = rows_bad = moved_n = 0
    row_examples = []
    prev_rows = None
    for i in np.nonzero(use)[0]:
        table = tables[seg[i]]
        bdg = T.bdg[i]
        per_key = Counter()
        for v in range(min(len(bdg), TOWER_CARS)):
            ch = bdg[v]
            key = table.get(ch) if 'a' <= ch <= 'x' else None
            if key is not None:
                per_key[key] += 1
                keys_seen.add(key)
                prev = session_key.get((run_id[i], v))
                if prev is not None and prev != key:
                    n_changes += 1
                    if len(change_examples) < 5:
                        change_examples.append(f'car {v} {prev} -> {key} at {T.t[i]:.1f} s')
                session_key[(run_id[i], v)] = key
        for key, n in per_key.items():
            if n > 2:
                crowded.append(f'{T.t[i]:.1f} s: {key} on {n} cars')
        for v in range(TOWER_CARS):
            if not (np.isfinite(T.pos[i, v]) and T.status[i, v] == 2):
                continue
            seen[v] += 1
            ch = bdg[v] if v < len(bdg) else ''
            if 'a' <= ch <= 'x' and ch in table:
                ok_n[v] += 1
            elif ch == '?':
                ok_n[v] += 1
                other_n[v] += 1
            else:
                steps[ch if ch in BADGE_STEP else 'unmapped letter'] += 1
                first_miss.setdefault(v, (T.t[i], ch))
        # rows: rbdg[k] is the letter of the row's car, '-' when it has none (the model takes the badge from the
        # same snapshot, so this holds exactly in every record)
        if T.on[i] == 1 and T.rows[i] > 0:
            toks = [] if T.recs[i]['shown'] == '-' else T.recs[i]['shown'].split(' ')
            vids = [int(tok.split(':', 1)[0]) for tok in toks]
            rb = T.rbdg[i]
            for k, v in enumerate(vids):
                rows_n += 1
                ch = bdg[v] if v < len(bdg) else ''
                want = ch if ('a' <= ch <= 'x') else '-'
                got = rb[k] if k < len(rb) else ''
                moved = prev_rows is not None and k < len(prev_rows) and prev_rows[k] != v
                moved_n += moved
                if got != want:
                    rows_bad += 1
                    if len(row_examples) < 5:
                        shows = table.get(got) or ('nothing' if got in ('', '-') else got)
                        row_examples.append(f'{T.t[i]:.1f} s row {k}: car {v} shows {shows}, '
                                            f'its badge is {table.get(want, "none")}')
            prev_rows = vids
        else:
            prev_rows = None
    short = [v for v in seen if ok_n[v] < BADGE_SHARE * seen[v]]
    cars_key = sum(1 for v in seen if ok_n[v] - other_n[v] > 0)
    ev = (f'{len(seen)} running classified cars over {int(use.sum())} settled records: {cars_key} with a key '
          f'({len(keys_seen)} keys: {", ".join(sorted(keys_seen)[:12])}{"..." if len(keys_seen) > 12 else ""})')
    if other_n:
        ev += (f'; the game builds another badge (My Team / render badge, no logo by design) for car(s) '
               f'{", ".join(str(v) for v in sorted(other_n))}')
    if steps:
        ev += ('; car-records without a badge: ' +
               ', '.join(f'{n} {BADGE_STEP.get(k, k)}' for k, n in steps.most_common()))
    vec = Counter(T.bdgvec[i] for i in np.nonzero(use)[0] if T.bdgvec[i])
    if vec:
        ev += ('; the game\'s entrant vector (records: state): ' +
               ', '.join(f'{n}: {k + " entries" if k.isdigit() else BADGE_VEC.get(k, k)}' for k, n in vec.most_common(4)))
    if short:
        ev += '; below 99 %: ' + ', '.join(
            f'car {v} {pct(ok_n[v] / seen[v])} (first at {first_miss[v][0]:.1f} s, '
            f'{BADGE_STEP.get(first_miss[v][1], first_miss[v][1])})' for v in sorted(short)[:5])
    ev += f'; {n_changes} badge changes within a session'
    if change_examples:
        ev += ' (' + '; '.join(change_examples) + ')'
    ev += f'; {len(crowded)} records with a badge on more than two cars'
    if crowded:
        ev += f' (first: {crowded[0]})'
    ev += (f'; rows: {rows_n} shown, {rows_n - rows_bad} with their car\'s badge, {moved_n} of them right after the '
           f'row\'s car changed')
    if row_examples:
        ev += '; first: ' + '; '.join(row_examples)
    if conflicts:
        ev += '; letters listed with two keys: ' + '; '.join(conflicts[:3])
    if not keys_seen and not short:
        rep.verdict(field, 'NO DATA', ev, 'no car had a team key: drive an F1 session with the tower on')
        return
    good = not short and not n_changes and not crowded and not rows_bad and not conflicts
    rep.verdict(field, 'PASS' if good else 'FAIL', ev,
                'check each row\'s logo against its driver\'s team on the game\'s standings screen (test-drive.md)' if good
                else 'the badge chain (field-traces.md §10) or the model (rows) disagrees with itself: send the log')


def tower_checks(rep, halo_path=None, path=None, settled=None):
    path = path or tower_path(halo_path)
    rows = []
    if os.path.exists(path):
        with open(path, newline='', encoding='utf-8', errors='replace') as f:
            rows = list(csv.DictReader(line for line in f if not line.startswith('#')))
    if not rows:
        why = 'no tower log next to the halo log (a build without the timing tower)' if not os.path.exists(path) \
            else 'the tower log is empty'
        for field in TOWER_FIELDS:
            rep.verdict(field, 'NO DATA', why, 'drive with this build and the Validation log on')
        return 0
    T = TowerLog(rows)
    tower_found(rep, T)
    tower_cls(rep, T)
    tower_gaps(rep, T)
    tower_tyres(rep, T, settled)
    tower_sc(rep, T)
    tower_flags(rep, T)
    tower_penalties(rep, T)
    tower_warnings(rep, T)
    tower_shown(rep, T)
    tower_cost(rep, T)
    tower_badges(rep, T)
    rep.text(f'- Timing tower log: `{os.path.basename(path)}`, {T.n} records '
             f'({float(T.t[-1] - T.t[0]):.0f} s).')
    return T.n


def finish(rep, path, n, dur, run_s=None, tower=True, settled=None):
    if tower:
        tower_checks(rep, halo_path=path, settled=settled)
    out = sys.argv[2] if len(sys.argv) > 2 else 'report.md'
    text_ = rep.render(path, n, dur, run_s)
    open(out, 'w', encoding='utf-8').write(text_)
    sys.stdout.buffer.write(text_.encode('utf-8'))


def car_table(rep, c, n, t, live, named):
    """The vehicle table's identity checks: the per-slot status of every scan (log column "slots")."""
    sl = text(c['slots'])
    tab = (c['compatible'] == 1) & (sl != '-') & (sl != '')
    if not tab.any():
        rep.verdict('Car table (identity)', 'NO DATA', 'the vehicle table was never read', 'drive on track with the addon enabled')
        return
    width = max(len(s) for s in sl[tab])
    grid = np.array([list(s.ljust(width, '-')) if ok else ['-'] * width for s, ok in zip(sl, tab)])
    cnt = Counter(''.join(sl[tab]))
    mix = ', '.join(f"'{k}' {cnt[k]}" for k in '.snuti?' if cnt[k])
    counts = sorted(set(c['vcount'][tab].astype(int).tolist()))
    length_off = int(sum(len(s) != int(v) for s, v, ok in zip(sl, c['vcount'], tab) if ok))
    # the player car's slot, named by the game's ControllerSystem (independent of the table's identity check)
    pk = np.nonzero(named & tab)[0]
    pst = np.array([grid[k, int(c['ctrl_vid'][k])] if int(c['ctrl_vid'][k]) < width else '-' for k in pk], dtype='<U1')
    p_car = np.isin(pst, ['.', 's'])
    p_in = float(p_car.mean()) if len(pst) else float('nan')
    p_mask = np.zeros(n, dtype=bool)
    p_mask[pk[~p_car]] = True
    p_s, p_at = longest(p_mask, t)
    # any slot rejected for longer than the churn while cars are created or destroyed
    worst = (0.0, None, None)
    for j in range(width):
        m = tab & np.isin(grid[:, j], list(SLOT_REJECT))
        if m.any():
            s, at = longest(m, t)
            if s > worst[0]:
                worst = (s, j, at)
    sc = float(np.mean([s.count('s') == 1 for s in sl[tab]]))
    ev = (f'vehicle count {counts}; slot statuses over {int(tab.sum())} records: {mix}' +
          (f'; {length_off} records whose slot list differs from the count in length' if length_off else '') +
          f"; the player car's slot (vehicle named by the ControllerSystem) held a car in {pct(p_in)} of {len(pst)} records" +
          (f" (otherwise {dict(Counter(pst[~p_car].tolist()))}, longest {p_s:.1f} s from t = {t[p_at]:.1f} s)"
           if p_at is not None else '') +
          f'; longest rejection of any slot {worst[0]:.1f} s' +
          (f" (slot {worst[1]}, '{grid[worst[2], worst[1]]}', from t = {t[worst[2]]:.1f} s)" if worst[1] is not None else '') +
          f"; exactly one car without ERS ('s', the safety car) in {pct(sc)} of records")
    if 'old_check' in c:
        oc = c['old_check']
        lv = live & (oc >= 0)
        mv = lv & (c['speed_kmh'] > 5)
        drop = float((oc[lv] == 0).mean()) if lv.any() else float('nan')
        drop_mv = float((oc[mv] == 0).mean()) if mv.any() else float('nan')
        ev += (f'; the check used before 2026-11-09 (CarLive+0x0 read as a vtable) would have dropped the player car in '
               f'{pct(drop)} of {int(lv.sum())} live records ({pct(drop_mv)} of {int(mv.sum())} moving)')
    ok = p_s <= LOST_MAX_S and worst[0] <= LOST_MAX_S
    if not ok:
        verdict, todo = 'FAIL', ("send the log: 't' means the container vptr (+0x380) or the lock pointer (+0x98) differ, "
                                 "'i' the vehicle id (+0xe8) is not the slot, 'u' the car could not be copied")
    elif not len(pst):
        verdict, todo = 'NO DATA', 'the ControllerSystem never named a player car: drive on track'
    else:
        verdict, todo = 'PASS', ''
    rep.verdict('Car table (identity)', verdict, ev, todo)
    rep.text("- Slot statuses: '.' a car with ERS, 's' a car without ERS (the safety car), 'n' null slot, 'u' unreadable, "
             "'t' not a CarLive, 'i' vehicle id not the slot index.")


def main():
    path = sys.argv[1]
    if os.path.basename(path).startswith('tower_'):
        rep = Report()
        n = tower_checks(rep, path=path)
        finish(rep, path, n, 0.0, tower=False)
        return
    c, n = load(path)
    t = c['t']
    rep = Report()
    live = (c['veh_ok'] == 1) & (c['compatible'] == 1)
    dur = float(t[live][-1] - t[live][0]) if live.any() else 0.0
    fresh = fresh_records(c, live)
    settle, settled = settle_windows(c, live)
    rate = fresh & ~settle                 # rate checks skip the settle window after each generation change

    # --- lifecycle
    gens = np.unique(c['generation'])
    rej = c['rejects']
    rep.verdict('Lifecycle', 'PASS' if live.any() else 'NO DATA',
                f'{len(gens)} car/session generations, player car found in {100 * live.mean():.0f}% of records, '
                f'max {int(rej.max())} rejected table slots in a frame, {int(c["dropped"].max())} records dropped',
                '' if live.any() else 'drive on track with the addon enabled')
    if 'humans' in c:
        act = (c['active'] == 1) & (c['compatible'] == 1)
        one = float((c['humans'][act] == 1).mean()) if act.any() else float('nan')
        rep.text(f'- is_ai rule: exactly one human-driven car in {100 * one:.0f}% of in-session records; '
                 f'{int(((c["humans"] != 1) & act & (c["veh_ok"] == 1)).sum())} records kept the held car '
                 f'(AI handover / loading), {int((act & (c["veh_ok"] == 0)).sum())} records had no player (halo hidden).')
    named = np.zeros(n, dtype=bool)
    if 'ctrl_hits' in c:
        act = (c['active'] == 1) & (c['compatible'] == 1)
        # the game names the player car (one local HumanController) but the provider has none: the halo is blank
        # while the player drives (an early build's table check rejected the car after the pit exit)
        named = (c['compatible'] == 1) & (c['ctrl_hits'] == 1) & (c['ctrl_vid'] >= 0)
        lost = named & (c['veh_ok'] == 0)
        lost_s, lost_at = longest(lost, t)
        lost_txt = (f'no player car while the ControllerSystem named one in {int(lost.sum())} of {int(named.sum())} '
                    f'records' + (f' (longest {lost_s:.1f} s from t = {t[lost_at]:.1f} s, vehicle '
                                  f'{int(c["ctrl_vid"][lost_at])})' if lost_at is not None else ''))
        lost_todo = 'the provider rejected the car the game names; Car table (identity) shows why (logs from 2026-11-09 on)'
        worst3 = sorted(((float(t[b] - t[a]) + RECORD_S, a, b) for a, b in runs(lost)), reverse=True)[:3]
        if worst3:
            sl = text(c['slots']) if 'slots' in c else None

            def at(k):
                vid = int(c['ctrl_vid'][k])
                st = sl[k][vid] if sl is not None and vid < len(sl[k]) and sl[k] != '-' else None
                return f'vehicle {vid}' + (f", slot '{st}'" if st else '')
            rep.text('- Player car lost while the ControllerSystem named it (longest first): ' +
                     ', '.join(f't = {t[a]:.1f}–{t[b]:.1f} s ({s:.1f} s, {at(a)})' for s, a, b in worst3) + '.')
        if act.any():
            hits = c['ctrl_hits'][act]
            readable = float((hits >= 0).mean())
            single = float((hits == 1).mean())
            both = act & (c['ctrl_vid'] >= 0) & (c['isai_vid'] >= 0)
            agree = float((c['ctrl_vid'][both] == c['isai_vid'][both]).mean()) if both.any() else float('nan')
            src = c['player_src'][act]
            spect = int((c['spect_vid'][act] >= 0).sum())
            ok = readable > 0.95 and single > 0.9 and (math.isnan(agree) or agree > 0.99)
            verdict = 'PASS' if ok and lost_s <= LOST_MAX_S else ('NO DATA' if readable == 0 else 'FAIL')
            rep.verdict('Player car (ControllerSystem)', verdict,
                        f'system readable in {100 * readable:.0f}% of in-session records, exactly one local human car in '
                        f'{100 * single:.0f}%; agrees with the is_ai rule in '
                        f'{"n/a" if math.isnan(agree) else f"{100 * agree:.1f}%"} of {int(both.sum())} records where both '
                        f'name a car; player source: ControllerSystem {100 * float((src == 2).mean()):.0f}%, is_ai fallback '
                        f'{100 * float((src == 3).mean()):.0f}%, none {100 * float((src == 0).mean()):.0f}%; '
                        f'spectate flag set in {spect} records (expect 0 while driving); {lost_txt}',
                        lost_todo if lost_s > LOST_MAX_S else 'include a formation lap and a pit stop (AI handovers)')
        elif named.any():
            rep.verdict('Player car (ControllerSystem)', 'FAIL', f'no car passed validation; {lost_txt}', lost_todo)
    if 'slots' in c:
        car_table(rep, c, n, t, live, named)
    L = {k: v[live] for k, v in c.items()}
    if not live.any():
        finish(rep, path, n, dur, settled=settled)
        return
    tl = L['t']

    run_s = frozen_text(rep, c, live, fresh)
    settle_text(rep, settled)

    # --- speed vs the game's own distance counter (independent object: VehicleProgressSystem)
    speed_check(rep, c, live, rate)
    sp = L['speed_kmh']
    still = (L['speed_ok'] == 1) & (sp < 1)
    rep.text(f'- Stationary samples: {still.sum()} (speed < 1 km/h); speed while stationary max {sp[still].max() if still.any() else float("nan"):.2f} km/h.')

    # --- gear: discrete, sequential, one rpm/speed ratio per gear (per stint: one car)
    gear_check(rep, c, live, fresh)

    # --- rpm: idle, limiter, drops on upshift
    rpm = L['rpm'][L['rpm_ok'] == 1]
    lim = L['limiter_rpm'][L['limiter_ok'] == 1]
    idle = L['rpm'][(L['rpm_ok'] == 1) & (L['speed_kmh'] < 1) & (L['throttle'] < 0.05)]
    up = np.nonzero(np.diff(L['gear']) == 1)[0]
    drops = [L['rpm'][i] - L['rpm'][min(i + 3, len(L['rpm']) - 1)] for i in up if L['speed_kmh'][i] > 40]
    ok = len(rpm) > 50 and rpm.max() <= (lim.max() * 1.02 if len(lim) else 20000) and (not drops or np.median(drops) > 500)
    rep.verdict('RPM', 'PASS' if ok else ('NO DATA' if len(rpm) <= 50 else 'FAIL'),
                f'range {rpm.min():.0f}–{rpm.max():.0f} rpm, limiter {np.median(lim) if len(lim) else float("nan"):.0f}, '
                f'idle median {np.median(idle) if len(idle) else float("nan"):.0f}, median drop on upshift '
                f'{np.median(drops) if drops else float("nan"):.0f} rpm over {len(drops)} upshifts')

    # --- pedals and g fields vs the car's own motion (fresh records, windows of several simulation steps)
    accel_checks(rep, c, live, rate)
    thr, brk = L['throttle'], L['brake']
    mv = (L['input_ok'] == 1) & (L['speed_kmh'] > 30)
    both = mv & (thr > 0.5) & (brk > 0.5)
    rep.text(f'- Throttle and brake both above 50%: {both.sum()} samples (should be near 0).')
    rev = (L['gear'] == -1) & (L['input_ok'] == 1)
    rep.text(f'- Reverse samples: {rev.sum()}; input flags seen: {sorted(set(L["input_flags"].astype(int).tolist()))}.')

    # --- energy: the battery's own energy vs the power channels (balance over fresh 1 s windows, by ERS mode)
    energy_checks(rep, c, live, rate)

    # --- ERS mode: Boost is mode 2 (the Boost control's handler writes it; the stock HUD shows eActive for it)
    modes = sorted(set(L['ers_mode'][L['mode_ok'] == 1].astype(int).tolist()))
    ch = np.nonzero(np.diff(L['ers_mode']) != 0)[0]
    boost = (L['mode_ok'] == 1) & (L['ers_mode'] == 2)
    presses = runs(boost)
    held = [float(tl[b] - tl[a]) + RECORD_S for a, b in presses]
    hud_b = int(((L['hud_boost'] == 1) != boost).sum())
    # deploy at full throttle in fresh records of a 2026 car, 150-250 km/h (below the speed taper)
    ft = (fresh[live] & (L['throttle'] > 0.95) & (L['brake'] < 0.05) & (L['speed_kmh'] >= 150) &
          (L['speed_kmh'] <= 250) & (L['power_ok'] == 1) & (L['store_mj'] > 0.2) & (L['max_deploy_ok'] == 1) &
          (L['max_deploy_kw'] >= ERS_2026_KW))
    on, off = ft & boost, ft & ~boost & (L['mode_ok'] == 1)
    d_on = float(np.median(L['deploy_kw'][on])) if on.sum() > 10 else float('nan')
    d_off = float(np.median(L['deploy_kw'][off])) if off.sum() > 10 else float('nan')
    if hud_b:
        b_verdict, b_todo = 'FAIL', "the halo's Boost light does not follow the mode: send the log"
    elif len(presses) >= 2:
        b_verdict, b_todo = 'PASS', ("check that the halo's Boost light came on with the game's own Boost indicator "
                                     '(the log cannot see the button)')
    else:
        b_verdict, b_todo = 'NO DATA', ("press Boost twice (hold it once, tap it once) and watch the halo's Boost light "
                                        "against the game's own Boost indicator")
    rep.verdict('Boost (ERS mode 2)', b_verdict,
                f'modes seen {modes}, {len(ch)} mode changes; {len(presses)} Boost activations' +
                (f' (median {np.median(held):.1f} s, longest {max(held):.1f} s)' if held else '') +
                f'; HUD Boost lit in {100 * L["hud_boost"].mean():.0f}% of records, disagreeing with mode 2 in {hud_b}; '
                f'median deploy at full throttle 150–250 km/h (fresh records) {d_on:.0f} kW in Boost, {d_off:.0f} kW '
                f'in the other modes', b_todo)
    flags = L['ers_flags']
    hexs = [v if isinstance(v, str) else f'{int(v):08d}' for v in flags.tolist()]  # all-digit values parse as numbers
    om = np.array([int(h[4:6], 16) != 0 if len(h) == 8 else False for h in hexs])  # +0x1a62: Overtake Mode active
    lt = (L['session_type'] >= 1) & (L['session_type'] <= 14) & (L['speed_kmh'] > 30)
    rc = (L['session_type'] >= 15) & (L['session_type'] <= 17) & (L['speed_kmh'] > 30)
    if lt.sum() > 50:
        share = float(om[lt].mean())
        rep.verdict('Overtake (Overtake Mode active, +0x1a62)', 'PASS' if share > 0.9 else 'FAIL',
                    f'set in {100 * share:.0f}% of moving practice/qualifying records (2026 rule: active at all times in '
                    f'lap-time sessions), {100 * float(om[rc].mean()) if rc.any() else float("nan"):.0f}% in races; '
                    "the halo binds the game's own om_active",
                    'a FAIL with a 2026 car means the game does not apply that rule: check OVERTAKE against the MFD')
    else:
        rep.verdict('Overtake (Overtake Mode active, +0x1a62)', 'NO DATA', 'no moving practice/qualifying records',
                    'drive a practice lap in a 2026 car')
    uniq = sorted(set(flags.tolist()))
    rep.text(f'- Overtake Mode bytes +0x1a60..63 (eligible, armed at detection, active, earned while suspended) seen: '
             f'{uniq[:12]}{" …" if len(uniq) > 12 else ""}.')

    # --- progress (per stint: one track, one lap counter)
    lap_check(rep, c, live)

    # --- turn number, position and arrow (per stint: one track)
    turn_checks(rep, c, live, fresh)

    # --- position: the session classification the game's own UI shows (the results system's entries)
    if 'classified' in L:
        def positions(s):
            s = str(s)
            return [int(s[1 + 2 * i:3 + 2 * i], 16) for i in range((len(s) - 1) // 2)] if s.startswith('p') else []
        found = L['results_found'] == 1
        cl = (L['classified'] == 1) & (L['session_type'] != 18)
        perm, rival_ok, rival_n = 0, 0, 0
        for k in np.nonzero(cl)[0]:
            p = positions(L['cls'][k])
            got = sorted(x for x in p if x)
            perm += len(got) >= 2 and got == list(range(1, len(got) + 1))
            own = int(L['own_pos'][k])
            want = 2 if own == 1 else own - 1
            rid = int(L['hud_rival_id'][k])
            if want in p:
                rival_n += 1
                rival_ok += 0 <= rid < len(p) and p[rid] == want
        race = cl & (L['session_type'] >= 15) & (L['session_type'] <= 17) & (L['player_rank'] >= 0) & (L['progress_ok'] == 1)
        agree = float((L['own_pos'][race] == L['player_rank'][race] + 1).mean()) if race.sum() > 50 else float('nan')
        if not found.any():
            rep.verdict('Position (classification)', 'FAIL', 'the results system was never found in the component registry',
                        'send the log: the registry key may differ in this build')
        elif not cl.any():
            rep.verdict('Position (classification)', 'NO DATA', f'results system found in {100 * found.mean():.0f}% of records, '
                        'classification never complete', 'drive a practice session for a lap')
        else:
            perm_ok = perm >= 0.95 * cl.sum()
            race_ok = math.isnan(agree) or agree >= 0.8
            rv_ok = rival_n == 0 or rival_ok == rival_n
            rep.verdict('Position (classification)', 'PASS' if perm_ok and race_ok and rv_ok else 'FAIL',
                        f'results system found in {100 * found.mean():.0f}% of records; a full permutation 1..N in '
                        f'{100 * perm / cl.sum():.0f}% of {cl.sum()} classified records; race: own position = road order in '
                        f'{"n/a" if math.isnan(agree) else f"{100 * agree:.0f}%"} of {race.sum()} records; '
                        f'rival lane = one place ahead in {rival_ok}/{rival_n} records',
                        'in practice or qualifying, check that the rival name is the car one place above you on the '
                        "game's timing tower (that order is L2)")
    else:
        rep.verdict('Position (classification)', 'NO DATA', 'log written by an older build (no classification columns)',
                    'update the addon')

    # --- HUD shows what was read (pedal slats are eased with a 35 ms time constant: within one slat)
    hk = (L['hud_speed_ok'] == 1)
    mis = int((np.abs(L['hud_kmh'][hk] - np.round(L['speed_kmh'][hk])) > 1).sum())
    gmis = int(((L['hud_gear'] != L['gear']) & (L['hud_gear_ok'] == 1)).sum())
    pmis = int((L['hud_pedals_ok'] != L['input_ok']).sum())
    pd = (L['hud_pedals_ok'] == 1) & (L['input_ok'] == 1)
    th_ok = br_ok = float('nan')
    if pd.sum() > 50:
        th_ok = float((np.abs(L['hud_th_lv'][pd] - np.round(np.clip(L['throttle'][pd], 0, 1) * STRIPES)) <= 1).mean())
        br_ok = float((np.abs(L['hud_br_lv'][pd] - np.round(np.clip(L['brake'][pd], 0, 1) * STRIPES)) <= 1).mean())
    slats_ok = math.isnan(th_ok) or (th_ok >= 0.9 and br_ok >= 0.9)
    rep.verdict('HUD = state', 'PASS' if mis == 0 and gmis == 0 and pmis == 0 and hud_b == 0 and slats_ok else 'FAIL',
                f'{mis} km/h mismatches, {gmis} gear mismatches, {hud_b} Boost mismatches, {pmis} pedal-availability '
                f'mismatches between the read state and the published leaves; throttle slats within one of the read '
                f'throttle in {pct(th_ok)}, brake slats in {pct(br_ok)} of {int(pd.sum())} records')

    # --- the G-force meter (option, off by default): against the read g and its own rules
    gmeter_checks(rep, c, live, fresh)

    # --- the halo's own cost on the game's flow thread (whole log, not only live frames)
    if 'cost_frames' in c:
        fr = c['cost_frames']
        ok = fr > 0
        if ok.any():
            mean = float((c['cost_mean_us'][ok] * fr[ok]).sum() / fr[ok].sum())
            p99 = float(np.percentile(c['cost_max_us'][ok], 99))
            worst = float(c['cost_max_us'][ok].max())
            fps = float(fr[ok].sum() / max(1e-9, t[-1] - t[0]))
            budget = 1e6 / fps if fps > 0 else 0
            rep.verdict('Performance', 'PASS' if mean < 0.01 * budget and p99 < 1000 else 'FAIL',
                        f'{mean:.1f} us/frame mean, {p99:.0f} us p99 of the per-record worst, {worst:.0f} us worst; '
                        f'{fps:.0f} fps, so the mean is {100 * mean / budget:.2f} % of a frame' if budget else 'no frame rate',
                        '' if mean < 0.01 * budget else 'report the CPU and frame rate')
    else:
        rep.verdict('Performance', 'NO DATA', 'log written by an older build (no cost columns)', 'update the addon')

    finish(rep, path, n, dur, run_s, settled=settled)


if __name__ == '__main__':
    main()
