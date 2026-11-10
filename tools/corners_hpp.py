# corners_hpp.py <dl_dir> <out.hpp> : official corner table for the F1 25 tracks (from MultiViewer circuit data)
#
# Run it with python -I: the circuit files are downloaded data. Each file holds one car's lap as a polyline (x, y in
# about 0.1 m units, from the first position sample after the timing line) and the official corners, each at a
# distance ('length') along that polyline.
#
# Position: the corner's distance as a fraction of the lap. The lap is the polyline plus its closing gap (the stretch
# between the last and the first sample, across the line: up to 28 m), so late corners are not pushed back by it.
# The game's lap distance can start apart from this origin (Bahrain: the game's corners sit 33 m later); the HUD
# measures that offset on the first lap (halo_track.cpp), so the table stays in official terms.
#
# Direction: the heading change over +-25 m around the corner: the difference of the heading at the window's ends,
# each from the chord over +-5 m of track (the polyline's jitter and near-duplicate samples cancel out). Under 6
# degrees (a long, gentle corner, often marked at its exit), the bend the marker lies in decides: the run of one bend
# direction around it, when that turns 4 degrees or more; else the corner's own stretch (from halfway to the previous
# corner to halfway to the next, at most 60 m either side). The old fallback, a plain +-60 m window, reached into the
# next corner: Sakhir T5 and Silverstone T10 came out right-handed. REVIEWED holds the corners no window settles, with
# the evidence. Checked in game: every Sakhir turn (in-game logs).
import json, math, os, sys
d, out = sys.argv[1], sys.argv[2]
# F1 25 UDP track id -> (F1 live-timing circuit key, official length in metres)
TRACKS = {0: (10, 5278), 2: (49, 5451), 3: (63, 5412), 4: (15, 4657), 5: (22, 3337), 6: (23, 4361), 7: (2, 5891),
          9: (4, 4381), 10: (7, 7004), 11: (39, 5793), 12: (61, 4940), 13: (46, 5807), 14: (70, 5281), 15: (9, 5513),
          16: (14, 4309), 17: (19, 4318), 19: (65, 4304), 20: (144, 6003), 26: (55, 4259), 27: (6, 4909),
          29: (149, 6174), 30: (151, 5412), 31: (152, 6201), 32: (150, 5419)}
# (track id, label) -> (direction, why): corners whose direction no window settles
REVIEWED = {
    (20, '9'): ('R', 'Baku castle section: T8 (26 m before) and T10 (30 m after) are lefts; the only right-hand bend '
                     'between them, -12 deg, starts 4 m after the T9 marker; +-25 m mostly measures T8'),
}
MIN_DEG, NEAR_M, FAR_M = 6.0, 25.0, 60.0
rows, review = [], []
for tid, (key, length) in sorted(TRACKS.items()):
    j = json.load(open(os.path.join(d, f'c{key}.json'), encoding='utf-8'))
    xs, ys = j['x'], j['y']; n = len(xs)
    cum = [0.0]
    for i in range(n - 1): cum.append(cum[-1] + math.hypot(xs[i+1] - xs[i], ys[i+1] - ys[i]))
    total = cum[-1]
    lap = total + math.hypot(xs[0] - xs[-1], ys[0] - ys[-1])
    m_per_unit = length / lap

    def point(s):
        s = min(max(s, 0.0), total)
        lo, hi = 0, n - 1
        while hi - lo > 1:
            m = (lo + hi) // 2
            if cum[m] <= s: lo = m
            else: hi = m
        f = (s - cum[lo]) / (cum[hi] - cum[lo]) if cum[hi] > cum[lo] else 0
        return xs[lo] + f * (xs[hi] - xs[lo]), ys[lo] + f * (ys[hi] - ys[lo])

    # heading every metre along the lap, from the chord over +-5 m (a near-duplicate or jittered sample barely
    # moves it), unwrapped so a window's heading change is the difference of its ends
    step = 1 / m_per_unit
    hs, hh = [], []
    k = 0
    while k * step <= total:
        s = k * step
        (x0, y0), (x1, y1) = point(s - 5 * step), point(s + 5 * step)
        h = math.atan2(y1 - y0, x1 - x0)
        if hh:
            h = hh[-1] + (h - hh[-1] + math.pi) % (2 * math.pi) - math.pi
        hs.append(s); hh.append(h)
        k += 1

    def heading(s):
        i = min(max(int(s / step), 0), len(hh) - 2)
        f = min(max((s - hs[i]) / step, 0.0), 1.0)
        return hh[i] + f * (hh[i + 1] - hh[i])

    def turn(s0, s1):
        return math.degrees(heading(s1) - heading(s0))

    # bend direction every metre: the heading's slope smoothed over +-10 m
    w = 10
    slope = [0.0] + [(hh[i + 1] - hh[i - 1]) / 2 for i in range(1, len(hh) - 1)] + [0.0]
    pre = [0.0]
    for v in slope: pre.append(pre[-1] + v)
    bend = [(pre[min(len(slope), i + w + 1)] - pre[max(0, i - w)]) for i in range(len(slope))]

    def lobe(s):
        """heading change (degrees) of the bend the track is in at s: the run of one bend direction around it"""
        i = min(max(int(round(s / step)), 0), len(bend) - 1)
        sg = 1 if bend[i] > 0 else -1
        a = b = i
        while a > 0 and sg * bend[a - 1] > 0: a -= 1
        while b < len(bend) - 1 and sg * bend[b + 1] > 0: b += 1
        return math.degrees(hh[b] - hh[a])

    corners = sorted(j['corners'], key=lambda c: c['length'])
    cs = []
    for i, c in enumerate(corners):
        L = c['length']
        label = f"{c['number']}{(c.get('letter') or '')[:1]}"
        near = NEAR_M / m_per_unit
        a = turn(L - near, L + near)
        how = '+-25 m'
        if abs(a) < MIN_DEG:
            prev = corners[i - 1]['length'] if i else corners[-1]['length'] - lap
            nxt = corners[i + 1]['length'] if i + 1 < len(corners) else corners[0]['length'] + lap
            far = FAR_M / m_per_unit
            own = turn(max((prev + L) / 2, L - far), min((L + nxt) / 2, L + far))
            b = lobe(L)
            a, how = (b, 'bend at marker') if abs(b) >= 4 else (own, 'own stretch')
        side = 'L' if a > 0 else 'R'
        if (tid, label) in REVIEWED:
            side, why = REVIEWED[(tid, label)]
            how = 'reviewed'
            review.append(f'{tid:2d} {j["circuitName"]} T{label}: {side} (reviewed: {why})')
        elif how != '+-25 m':
            review.append(f'{tid:2d} {j["circuitName"]} T{label}: {side} ({how}, {a:+.0f} deg)')
        frac = min(0.999, max(0.0, L / lap))
        cs.append((int(c['number']), (c.get('letter') or '')[:1], frac, side, round(a)))
    rows.append((tid, j['circuitName'], length, cs))
    print(f"{tid:2d} {j['circuitName']:18s} {len(cs):2d} corners, last at {cs[-1][2]:.3f}: " + ' '.join(f'{c[0]}{c[1]}{c[3]}' for c in cs))
print('directions not from the +-25 m window (check these when the circuit data changes):')
print('\n'.join('  ' + r for r in review))
with open(out, 'w', encoding='utf-8', newline='\n') as f:
    f.write('// Generated by corners_hpp.py from F1 live-timing circuit data (MultiViewer API): official turn numbers,\n')
    f.write('// position as a fraction of the lap from the timing line, and direction. Keyed by F1 25 UDP track id.\n')
    f.write('#pragma once\n#include <cstdint>\n\nnamespace halo {\n\nstruct Corner {\n    uint8_t number;\n    char letter;\n    bool left;\n    float frac;\n};\n\n')
    f.write('struct TrackCorners {\n    int track;\n    const char *name;\n    float length_m;\n    int count;\n    const Corner *corners;\n};\n\n')
    for tid, name, length, cs in rows:
        f.write(f'inline constexpr Corner kCorners{tid}[] = {{\n')
        for c in cs:
            letter = f"'{c[1]}'" if c[1] else '0'
            f.write(f'    {{{c[0]}, {letter}, {"true" if c[3] == "L" else "false"}, {c[2]:.4f}f}},\n')
        f.write('};\n')
    f.write('\ninline constexpr TrackCorners kTracks[] = {\n')
    for tid, name, length, cs in rows:
        f.write(f'    {{{tid}, "{name}", {length}.f, {len(cs)}, kCorners{tid}}},\n')
    f.write('};\n\n}\n')
print('wrote', out)
