// 2026 halo onboard HUD — reference renderer (v3).
// Units: broadcast pixels of a 640x360 frame (x3 = 1080p), origin = dial centre, y down.
// The C++ overlay addon is generated from this file: its textures are rendered from these
// functions and its dynamic parts use the same numbers in G (geometry) and P (palette).
//
// The wings are drawn the way the broadcast maps them onto the curved halo: text runs along
// the band, but letter verticals lean toward the centre ("lean", degrees from screen-vertical,
// positive = top to the right) instead of staying perpendicular to the baseline.
const HALO_MAKE = (LAYOUT) => {
  const D = Math.PI / 180;
  const FONT = (typeof window !== 'undefined' && window.HALO_FONT) || 'HaloSaira';
  const CAP = 0.688; // Saira cap height / em

  const G = {
    // Centre cluster (dial, capsules, slat columns, labels): measured on the Interlagos reference in the rectified
    // design plane D (dial bright-ring radius 35.0, text horizontal, mirror-symmetric; docs/visual/reference-analysis.md).
    // The game HUD draws D as-is (theme 'authentic'). perspShot is the Interlagos camera's view of that plane
    // (canvas transform a,b,c,d = M_DS), used only by theme 'screenshot' to overlay the reference frame.
    centreScale: 1.0,
    perspShot: [0.999042, -0.032283, -0.043768, 0.853476],
    // look (docs/qa/discrepancies.md V17-V22, measured on the Interlagos reference in this plane): the collar is a
    // ring from just inside the face out to r, see-through above collarFade[0] and full from collarFade[1] down (the
    // broadcast shows the scene round the dial's upper half); the face is translucent (P.face) with a square mesh of
    // lines `w` wide and `pitch` apart (P.mesh, P.mesh2: every second line a little stronger), its ink set so the mesh's
    // contrast stays about even down the face as on the reference (lighter ink on the light top, stronger below)
    disc: { r: 39.37, inner: 34.4, rim: 35.0, ring: 1.2, light: 36.47, lightW: 0.55, collarFade: [-7.5, -3.5], collarLow: [16, 29], mesh: { pitch: 1.0, w: 0.28 } },
    kmh: { y: -23.934, fs: 4.974, tr: 0.02 },
    // speed and mph are live texts (the game's font in game): Saira at its own width here (no x1.068 /
    // x1.013 stretches fitted to the broadcast face)
    speed: { y: -14.874, fs: 13.529, tr: 0.35 },
    boost: { y: -2.617, w: 27.8, h: 5.423, r: 3.0, fs: 3.938, tr: 0.5, hatchR: [15.6, 18.5, 20.8, 22.5, 24.0, 25.6, 26.9], hy0: -6.5, hy1: 0.5 },
    ot: { y: 4.718, w: 46.629, h: 5.05, fs: 3.924, tr: 0.243 },
    mph: { y: 13.459, fs: 11.012, tr: 0.5 },
    mphLbl: { y: 21.88, fs: 4.388, tr: 0.595 },
    batt: { x: 0.0, y: 32.41, w: 24.9, h: 7.45, r: 1.9, nubW: 0.75, nubH: 3.0, bolt: 0.86, bx: -0.19, by: 32.19 },
    // capsules: annulus rIn..rOut between yTop and yBot; letters upright, evenly spaced in angle on radius txtR
    caps: { rIn: 39.311, rOut: 50.854, yTop: -18.105, yBot: 22.059, rcOut: 3.0, rcIn: 2.0, fs: 3.602, txtR: 45.142, txtA0: -15.518, txtA1: 24.508 },
    // slats: n parallelograms with vertical ends on circles (rIn, centre y cyIn) and (rOut, cyOut); slat 0 = bottom,
    // centre y at x = xRef is y0 - i * pitch; every slat slopes k (down toward the outside)
    // th: 2.40 (was the NCC fit's 2.16): the separators' FWHM then matches the reference's 0.75-0.84 (V8)
    // litGap: the gap between two lit slats in their colour at this brightness (V20)
    stripes: { rIn: 53.058, cyIn: 2.805, rOut: 66.528, cyOut: 1.075, n: 10, y0: 22.781, pitch: 3.54, xRef: 59, k: 0.233, th: 2.40, pad: 0.9, litGap: 0.5 },
    // BRAKE / THROTTLE: `lean` is the stems' angle from the screen's vertical (frame()). On the Interlagos reference both
    // labels stand upright on screen on their tilted baselines (label-box NCC against our label at known
    // leans peaks at -2..+4 for BRAKE, +4..+6 for THROTTLE; the stem-edge angle reads -4 / +3), so their shear
    // against the baseline stays: the reference shows it. BRAKE was +16.2 (a Melbourne fit, 32 deg against its baseline).
    brakeLbl: { x: -53.423, y: 31.523, rot: -15.979, lean: -2.0 },
    throttleLbl: { x: 51.665, y: 30.667, rot: 13.023, lean: 2.98 },
    lblFs: 4.541,
    // values below were fitted against two Melbourne frames, t=205 s and t=262 s (fit.html, normalised cross-correlation)
    // TURN and its number turned -20.6 degrees with no shear (lean = rot, was -1.6): the number is a live game
    // text, which the game turns but cannot shear, and TURN (a sprite, shown only with a number) takes the
    // number's transform, so the two match in the game
    turn: {
      arrow: { x: -87.419, y: 12.119, s: 1, rot: -53.081, lean: -28.65 },
      lbl: { x: -82.816, y: 23.817, fs: 4.497, rot: -20.6, lean: -20.6, tr: 0.3 },
      num: { x: -83.922, y: 31.143, fs: 7.934, rot: -20.6, lean: -20.6, tr: 0.3 },
    },
    // "<position> <SURNAME>": the number ends at numEnd (lane u), the surname starts numGap after it. leanRel 0 =
    // upright on the lane, as the game draws these live texts (docs/qa/discrepancies.md V11), without the
    // broadcast's 22-degree lean (a shear beyond Saira's own axes)
    names: { x: -106.759, y: 37.261, rot: -26.18, bend: 0.002305, lean: -11, leanRel: 0, drvV: 0.73, laneGap: 13.784, drvFs: 8.508, rivFs: 6.963, rivShift: 3.703, tr: 1.26,
             lineA: -7.495, lineB: 7.858, lineW: 0.8, railA0: 3.01, railB0: -3.02, cardEnd: -84.44, numEnd: -67.686, numGap: 6.86, numBox: 14.0, nameBox: 62.0 },
    aero: { x1: 89.654, y1: 4.458, x2: 88.54, y2: 8.787, rot: 16.347, lean: 13.047, fs: 4.371, tr: 0.587,
            barX: 85.19, barY: 19.65, barDx: 3.85, barDy: -3.76, barLen: 12.24, barAng: 15.5, slHx: 2.78, slHy: 0.76, slLen: 8.84, slAng: -52.1, slTh: 1.25, barTh: 1.1 },
    gears: { p0: [107.887, 19.578], p1: [149.139, 34.689], p2: [188.881, 63.902], fs: 6.916, fsOn: 6.557, lean: 13.377, track: 7.107, trackW: 1.9,
             mx: 97.901, my: 26.019, mr: 0,
             gx: 154.802, gy: 30.048, grot: 28.62, rx: 142.439, ry: 49.863, rrot: 28.804, lfs: 4.251, llean: 15.7,
             r0t: -0.046, r15t: 1.108, rEndOff: 4.642, rEndFs: 5.023 },
    band: { dx: 0.65, dy: 5.0 },
    wings: { L: { xi: -71.17, tilt: 3.9, top: 5.0, bot: 3.5, r: 3.4, xFar: -215 },
             R: { xi: 71.65, tilt: 9.8, top: 1.8, bot: 5.0, r: 3.4, xFar: 220 } },
    // G-force variant (optional, off by default; docs/gmeter/design.md). Measured on the Spa clip (Belgian GP Q2,
    // 18 Jul 2026, 640x360) in this plane D, with the outer ring = the rim (35.0). Angles: 0 = right, 90 = down.
    // rings: the three inner rings; val: the speed digits' size (cap 9.3 measured) with tighter tracking (Saira is
    // wider than the broadcast face: '4.5' ink 23 units); arc: cyan, built from whole segments of `seg` degrees
    // (edges at 22.5 + 45k): the two segments nearest the felt-force direction, three centred on it when wide;
    // white / red: bars of half-height halfH on the nearest axis (right, down, left, up), between the rings;
    // thresholds in g: indicator from `on`, wide arc from `wide`, red bar from `redOn`, red digits `digitsRed`.
    gm: { rings: [28.41, 23.41, 17.27], ringW: 0.5,
          val: { y: 0.0, fs: 13.529, tr: -0.45, sx: 1.0 }, lbl: { y: 7.0, fs: 3.6, tr: 0.25 },
          arc: { r0: 12.0, r1: 17.0, seg: 45 }, white: { r0: 17.8, r1: 22.9, halfH: 7.3 }, red: { r0: 23.9, r1: 27.9, halfH: 7.3 },
          on: 0.3, wide: 2.0, redOn: 2.3, digitsRed: 4.3 },
  };

  const P = {
    bandTop: 'rgba(24,62,78,0.50)', band: 'rgba(8,26,40,0.50)', bandBot: 'rgba(6,18,28,0.40)',
    bandEdge: 'rgba(150,212,222,0.42)', bandGlow: 'rgba(90,200,210,0.10)',
    wingFill: 'rgba(10,22,32,0.55)', wingLine: 'rgba(150,186,202,0.50)',
    // dial (V17-V22): collar at the sides / above the waist; the face's tint stops (0 = its top, 1 = its bottom),
    // translucent (alpha 0.8) and set so that over the reference's scene they give the measured face; the mesh's ink
    // down the face (mesh2: added on every second line, a quarter of it); rings as [stop, colour] lists, fading toward
    // the bottom like the reference's (bright ring at rim, its soft edge ringGlow, the thin light ring further out)
    discOuterTop: 'rgba(23,36,52,0)', discOuter: 'rgba(23,36,52,0.92)', discOuterBot: 'rgba(18,32,44,0.92)',
    face: [[0, 'rgba(170,183,189,0.8)'], [0.05, 'rgba(170,183,189,0.8)'], [0.151, 'rgba(136,152,163,0.8)'], [0.195, 'rgba(120,137,150,0.8)'],
           [0.238, 'rgba(95,124,144,0.8)'], [0.282, 'rgba(86,106,126,0.8)'], [0.34, 'rgba(81,106,129,0.8)'], [0.413, 'rgba(59,84,108,0.8)'],
           [0.762, 'rgba(49,70,91,0.8)'],
           [0.878, 'rgba(28,52,66,0.8)'], [1, 'rgba(28,52,66,0.8)']],
    mesh: [[0, 'rgba(6,14,22,0.068)'], [0.05, 'rgba(6,14,22,0.068)'], [0.2, 'rgba(6,14,22,0.096)'], [0.34, 'rgba(6,14,22,0.150)'], [0.78, 'rgba(6,14,22,0.156)'], [1, 'rgba(6,14,22,0.152)']],
    mesh2: [[0, 'rgba(6,14,22,0.017)'], [0.05, 'rgba(6,14,22,0.017)'], [0.2, 'rgba(6,14,22,0.024)'], [0.34, 'rgba(6,14,22,0.0375)'], [0.78, 'rgba(6,14,22,0.039)'], [1, 'rgba(6,14,22,0.038)']],
    ring: [[0, 'rgba(162,174,184,0.76)'], [0.02, 'rgba(162,174,184,0.78)'], [0.07, 'rgba(162,174,184,0.94)'], [0.15, 'rgba(162,174,184,0.95)'], [0.25, 'rgba(160,172,183,0.80)'], [0.63, 'rgba(158,170,181,0.83)'], [0.75, 'rgba(150,162,174,0.65)'],
           [0.85, 'rgba(120,135,148,0.32)'], [1, 'rgba(100,115,128,0.50)']],
    ringGlow: [[0, 'rgba(150,162,170,0.16)'], [0.25, 'rgba(150,162,170,0.14)'], [0.37, 'rgba(150,162,170,0.10)'], [0.63, 'rgba(150,162,170,0.08)'], [0.85, 'rgba(150,162,170,0)']],
    ringLight: [[0, 'rgba(176,184,190,0.60)'], [0.02, 'rgba(176,184,190,0.62)'], [0.07, 'rgba(176,184,190,0.83)'], [0.1, 'rgba(176,184,190,0.82)'], [0.25, 'rgba(176,184,190,0.73)'], [0.37, 'rgba(174,182,189,0.72)'], [0.63, 'rgba(170,178,186,0.645)'],
                [0.75, 'rgba(160,170,178,0.57)'], [0.85, 'rgba(130,140,150,0.24)'], [0.93, 'rgba(110,120,130,0)']],
    white: '#F4F7F8', label: '#E4F0F3', dim: '#93A9BB',
    boostFill: '#475A6D', boostLine: '#5B7183', boostText: '#9CADBC', hatch: 'rgba(120,146,170,0.85)',
    boostOn: '#33ADF7', boostOnLine: '#A6DDFF', boostOnText: '#062238', hatchOn: 'rgba(127,214,255,0.95)',
    // OVERTAKE lit: bright green outline and letters on a dark-green fill (docs/research 3.3)
    otOnTop: '#1A7438', otOnBot: '#12602C', otOnLine: '#52C878', otOnText: '#58C070', otOnGlow: 'rgba(80,200,120,0.30)',
    otOff: 'rgba(92,101,108,0.92)', otOffLine: 'rgba(130,140,148,0.8)', otOffText: '#283035',
    capOff: 'rgba(30,84,124,0.95)', capOffLine: '#3A88B8', capOffText: '#5DB0D6',
    // lit capsule fill (V22): a little darker, to the reference's DEPLOY-lit #1686CA-#1986D1 (was #3A9AEE / #1784CE)
    capOnTop: '#2793E1', capOnBot: '#0F7EC3', capOnLine: '#44B0E4', capOnText: '#58A2F0',
    // unlit slats blue-grey; lit brake red (207,84,101) as measured on compressed footage, lifted a little toward the
    // source colours (docs/research 3.6). V20: the panel between the slats, the unlit slats and the lit throttle
    // from the Interlagos reference (separators (35,58,76), unlit (56,79,97), lit throttle (44,216,191))
    stripePanel: 'rgba(33,58,79,0.85)', stripeOff: 'rgba(58,82,99,0.92)',
    throttle: '#2CD8BF', throttleTop: '#36DDC6', brake: '#E2566A', brakeTop: '#EC6A7C',
    battLine: '#4FB8E1', battFillTop: '#1489D6', battFillBot: '#0F7DCB', battIn: '#235079', battCharge: '#0E4877', bolt: '#4FE0F5',
    aeroOn: '#45E4D4', aeroBar: '#C9D3D8', gearDim: 'rgba(205,216,222,0.86)', track: 'rgba(160,182,195,0.55)', gearLbl: '#C9D5DD',
    // G-force variant: Spa clip samples (360p, compressed) cyan (125-134, 209-222, 220-228), white (228, 234, 238),
    // red block (226, 118, 130), lifted a little toward the source colours like the slats; rings are sub-pixel there
    gRing: 'rgba(196,172,208,0.62)', gCyan: '#86DDE6', gWhite: '#F2F6F8', gRed: '#EE5866',
  };

  // ---------- car classes (docs/halo-car-classes.md). st.carClass picks which car's halo is drawn:
  //   '2026' (default, also when unset): today's halo, unchanged;
  //   '2025': F1 25's own 2025 cars: a DRS pill in place of the active-aero symbol, the ERS deploy mode in the
  //           Boost / Overtake area, capsules on the 2025 MGU-K scale (capsKW);
  //   'f2':   the same halo without battery, capsules and pills, plus the DRS pill.
  // capsKW is the power a full capsule stands for: the DLL's scale for st.recharge / st.deploy (level = kW / capsKW).
  // The variant parts' geometry and colours live in GV / PV, not in G / P, so the 2026 export header is unchanged.
  const CLASSES = {
    '2026': { aero: true, drs: false, battery: true, capsules: true, capsKW: 350, pills: 'boost_ot' },
    '2025': { aero: false, drs: true, battery: true, capsules: true, capsKW: 120, pills: 'ers_mode' },
    f2: { aero: false, drs: true, battery: false, capsules: false, capsKW: null, pills: null },
  };
  const carClass = st => CLASSES[st && st.carClass] || CLASSES['2026'];
  // st.drs: the pill's look ('off' | 'avail' | 'open') or the game's drs_pit_state (docs/halo-car-classes.md 2.3).
  // drs_distance and drs_active show the outline (a proposal, doc 6.1); the pit limiter states show grey.
  const DRS_LOOK = { off: 'off', avail: 'avail', open: 'open', invalid: 'off', drs_unavailable: 'off', drs_distance: 'avail',
                     drs_active: 'avail', drs_live: 'open', pit_distance: 'off', pit_active: 'off', pit_live: 'off' };
  const drsLook = st => DRS_LOOK[st && st.drs] || 'off';
  // st.ersMode: the game's ers_mode (ui32, view-model order 0 None, 1 Medium, 2 Hotlap, 3 Overtake) or the name
  const ERS_MODES = ['NONE', 'MEDIUM', 'HOTLAP', 'OVERTAKE'];
  const ersModeIndex = st => {
    const m = st && st.ersMode, i = typeof m === 'string' ? ERS_MODES.indexOf(m.toUpperCase()) : m;
    return Number.isInteger(i) && i >= 0 && i < ERS_MODES.length ? i : null;
  };
  const GV = {
    // DRS pill: in the active-aero spot on the right wing, sheared with the wing like the ACTIVE AERO label
    drs: { x: 86.9, y: 11.9, w: 17.6, h: 7.2, r: 1.5, fs: 5.1, tr: 0.62, rot: 16.347, lean: 13.047, line: 0.8 },
    // ERS deploy mode (2025): the caption takes the Boost slot, the mode pill the Overtake slot (the OVERTAKE pill's size)
    ersCap: { y: -2.617, fs: 3.938, tr: 0.5 },
    ersPill: { y: 4.718, w: 46.629, h: 5.05, r: 1, fs: 3.924, tr: 0.243 },
  };
  const PV = {
    // DRS: grey = the OVERTAKE pill's off look; available = a white outline; open = the game's own DRS green
    // (rgba(34,188,52): the stock DRS bar's drs_rad_green key, dial_pit_lane_slider.idf drs_rad_bg frame 40)
    drsOff: 'rgba(92,101,108,0.92)', drsOffLine: 'rgba(130,140,148,0.8)', drsOffText: '#283035',
    drsAvailFill: 'rgba(8,20,30,0.45)', drsAvailLine: '#F4F7F8', drsAvailText: '#F4F7F8',
    drsOpen: '#22BC34', drsOpenLine: '#8CF09A', drsOpenText: '#04240B', drsOpenGlow: 'rgba(60,220,90,0.32)',
  };

  // ---------- layout variant 'cam' ("Default camera"): a symmetric halo for the game's centred T-cam. Both wings
  // have one shape, their top edge follows the car's own halo bar as the default camera shows it (
  // measured on one capture; the numbers below come from that measure and from today's set by one rule: every part
  // keeps its x and its share of the band's height and turns with the band). The layout draws 4/3 as large in game.
  // Today's set ('tv', the broadcast's off-centre camera) is every number above and the two band tables below.
  const CAM = {
    bandTop: [[-218.0, 54.55], [-190, 33.15], [-168, 20.43], [-146, 10.2], [-122, 1.2], [-98, -6.01], [-77.0, -11.0], [-58, -17], [-36, -24], [0, -27], [36, -24], [58, -17], [77.0, -11.0], [98, -6.01], [122, 1.2], [146, 10.2], [168, 20.43], [190, 33.15], [218.0, 54.55]],
    bandBot: [[218.0, 98.13], [188, 77.27], [166, 66.05], [144, 57.12], [122, 49.0], [100, 39.66], [80, 31.0], [64, 25.0], [36, 28], [0, 29], [-36, 28], [-64, 25.0], [-80, 31.0], [-100, 39.66], [-122, 49.0], [-144, 57.12], [-166, 66.05], [-188, 77.27], [-218.0, 98.13]],
    brakeLbl: { x: -52.544, y: 31.095, rot: -14.501, lean: -2.49 },
    throttleLbl: { x: 52.544, y: 31.095, rot: 14.501, lean: 2.49 },
    turn: { arrow: { x: -87.419, y: 10.516, s: 1, rot: -49.669, lean: -25.238 }, lbl: { x: -82.816, y: 22.476, fs: 4.497, rot: -17.188, lean: -17.188, tr: 0.3 }, num: { x: -83.922, y: 29.682, fs: 7.934, rot: -17.188, lean: -17.188, tr: 0.3 } },
    names: { x: -106.759, y: 28.697, rot: -17.18, bend: 0.001167, lean: -11, leanRel: 0, drvV: 0.73, laneGap: 13.784, drvFs: 8.508, rivFs: 6.963, rivShift: 3.703, tr: 1.26, lineA: -7.495, lineB: 7.858, lineW: 0.8, railA0: 3.01, railB0: -3.02, cardEnd: -84.44, numEnd: -67.686, numGap: 6.86, numBox: 14.0, nameBox: 62.0 },
    aero: { x1: 89.654, y1: 4.916, x2: 88.54, y2: 9.322, rot: 14.189, lean: 10.889, fs: 4.371, tr: 0.587, barX: 85.19, barY: 20.457, barDx: 3.85, barDy: -3.76, barLen: 12.24, barAng: 13.342, slHx: 2.78, slHy: 0.76, slLen: 8.84, slAng: -54.258, slTh: 1.25, barTh: 1.1 },
    // gear digits: larger and bolder than the 'tv' set's 6.916 / 700 and 6.557 / 780
    gears: { p0: [107.887, 19.155], p1: [149.139, 30.672], p2: [188.881, 52.287], fs: 7.7, fsOn: 7.7, w: 800, wOn: 880, lean: 5.762, track: 7.107, trackW: 1.9, mx: 97.901, my: 26.182, mr: 0, gx: 154.802, gy: 24.141, grot: 20.456, rx: 142.439, ry: 45.689, rrot: 21.994, lfs: 4.251, llean: 8.085, r0t: -0.046, r15t: 1.108, rEndOff: 4.642, rEndFs: 5.023 },
    band: { dx: 0.0, dy: 5.0 },
    wings: { L: { xi: -71.41, tilt: 6.85, top: 3.4, bot: 4.25, r: 3.4, xFar: -218.0 }, R: { xi: 71.41, tilt: 6.85, top: 3.4, bot: 4.25, r: 3.4, xFar: 218.0 } },
    drs: { y: 12.527, rot: 14.189, lean: 10.889 },
  };
  const cam = LAYOUT === 'cam';
  if (cam) { for (const k of Object.keys(G)) if (CAM[k] && !Array.isArray(CAM[k]) && k !== 'drs') G[k] = CAM[k]; Object.assign(GV.drs, CAM.drs); }

  // ---------- text
  let WEIGHT = 700;
  function font(g, px) { g.font = `${WEIGHT} ${px}px ${FONT}`; g.fontStretch = 'expanded'; }
  function adv(g, s, px) { font(g, px); return [...s].map(ch => g.measureText(ch).width); }
  const sum = a => a.reduce((p, q) => p + q, 0);
  // Glyph frame: baseline along `rot`, verticals along `lean` (both degrees, screen space).
  function frame(g, rot, lean) {
    const r = rot * D, l = (lean === undefined ? rot : lean) * D;
    g.transform(Math.cos(r), Math.sin(r), -Math.sin(l), Math.cos(l), 0, 0);
  }
  // Text with its cap height centred on y. o: align, tr (tracking), sx, rot, lean, w (weight)
  function text(g, s, x, y, px, color, o = {}) {
    const { align = 'center', tr = 0, sx = 1, rot = 0, lean, w: wt = 700 } = o; const prevW = WEIGHT; WEIGHT = wt;
    g.save(); g.translate(x, y); frame(g, rot, lean); g.scale(sx, 1);
    const a = adv(g, s, px); const w = sum(a) + tr * (a.length - 1);
    let cx = align === 'center' ? -w / 2 : align === 'right' ? -w : 0;
    g.fillStyle = color; g.textBaseline = 'alphabetic';
    [...s].forEach((ch, i) => { g.fillText(ch, cx, CAP * px / 2); cx += a[i] + tr; });
    g.restore(); WEIGHT = prevW; return w * sx;
  }

  // ---------- geometry helpers
  const lerp = (a, b, t) => a + (b - a) * t;
  function rr(g, x, y, w, h, r) { g.beginPath(); g.roundRect(x, y, w, h, r); }
  function poly(g, pts, close = true) { g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); if (close) g.closePath(); }
  function smoothPts(pts, closed, per = 8) { // Catmull-Rom sampled to points
    const n = pts.length, out = [];
    for (let i = 0; i < (closed ? n : n - 1); i++) {
      const p0 = pts[(i - 1 + n) % n], p1 = pts[i], p2 = pts[(i + 1) % n], p3 = pts[(i + 2) % n];
      const q0 = closed || i > 0 ? p0 : p1, q3 = closed || i < n - 2 ? p3 : p2;
      for (let k = 0; k < per; k++) {
        const t = k / per, t2 = t * t, t3 = t2 * t;
        out.push([0, 1].map(j => 0.5 * ((2 * p1[j]) + (-q0[j] + p2[j]) * t + (2 * q0[j] - 5 * p1[j] + 4 * p2[j] - q3[j]) * t2 + (-q0[j] + 3 * p1[j] - 3 * p2[j] + q3[j]) * t3)));
      }
    }
    if (!closed) out.push(pts[n - 1]);
    return out;
  }
  function bez(p0, p1, p2, t) { const u = 1 - t; return [u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0], u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]]; }
  function bezTan(p0, p1, p2, t) { const u = 1 - t; const dx = 2 * u * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0]), dy = 2 * u * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1]); const l = Math.hypot(dx, dy); return [dx / l, dy / l]; }

  // Round selected vertices of a closed polyline: corners = [[index, radius], ...].
  function roundCorners(raw, corners) {
    const n = raw.length, out = [];
    const walk = (i, dir, dist) => {
      let a = raw[i], k = i;
      for (let guard = 0; guard < n; guard++) {
        const k2 = (k + dir + n) % n, b = raw[k2], d = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (d >= dist) { const t = dist / d; return { p: [lerp(a[0], b[0], t), lerp(a[1], b[1], t)], k: k2 }; }
        dist -= d; a = b; k = k2;
      }
      return { p: a, k };
    };
    const cs = corners.slice().sort((a, b) => a[0] - b[0]);
    cs.forEach(([i, r], c) => {
      const A = walk(i, -1, r), B = walk(i, 1, r), C = raw[i];
      for (let s = 0; s <= 6; s++) { const t = s / 6, u = 1 - t; out.push([u * u * A.p[0] + 2 * u * t * C[0] + t * t * B.p[0], u * u * A.p[1] + 2 * u * t * C[1] + t * t * B.p[1]]); }
      const [ni, nr] = cs[(c + 1) % cs.length], Bn = walk(ni, -1, nr);
      let k = B.k; for (let guard = 0; k !== Bn.k && guard < n; guard++) { out.push(raw[k]); k = (k + 1) % n; }
    });
    return out;
  }
  // Shape between an inner edge x = xin(y) and an outer edge x = xout(y) over y in [yT, yB] (right side; mirrored for the left).
  function sideShape(xin, xout, yT, yB, rcO, rcI, left) {
    const N = 40, raw = [], corners = [];
    corners.push([raw.length, rcI]); raw.push([xin(yT), yT]);
    corners.push([raw.length, rcO]); raw.push([xout(yT), yT]);
    for (let i = 1; i < N; i++) { const y = lerp(yT, yB, i / N); raw.push([xout(y), y]); }
    corners.push([raw.length, rcO]); raw.push([xout(yB), yB]);
    corners.push([raw.length, rcI]); raw.push([xin(yB), yB]);
    for (let i = N - 1; i > 0; i--) { const y = lerp(yT, yB, i / N); raw.push([xin(y), y]); }
    const out = roundCorners(raw, corners);
    return left ? out.map(([x, y]) => [-x, y]) : out;
  }
  const capsXin = y => Math.sqrt(G.caps.rIn ** 2 - y * y);
  const capsXout = y => { const c = G.caps; if (c.rOut) return Math.sqrt(c.rOut ** 2 - y * y); const ym = (c.yTop + c.yBot) / 2; return c.xOut - c.kOut * (y - ym) ** 2; };
  const capsulePts = left => sideShape(capsXin, capsXout, G.caps.yTop, G.caps.yBot, G.caps.rcOut, G.caps.rcIn, left);
  // slat geometry (right side; the left side mirrors x): centre line y = stripeY(i) + k * (x - xRef)
  const stripeLine = (i, x) => stripeY(i) + G.stripes.k * (x - G.stripes.xRef);
  const circleX = (r, cy, i, off) => { let x = r; for (let n = 0; n < 6; n++) x = Math.sqrt(Math.max(0, r * r - (stripeLine(i, x) + off - cy) ** 2)); return x; };
  const stripeXin = (i, off = 0) => circleX(G.stripes.rIn, G.stripes.cyIn, i, off);
  const stripeXout = (i, off = 0) => circleX(G.stripes.rOut, G.stripes.cyOut, i, off);
  const slatPts = (i, left, grow = 0) => {
    const s = G.stripes, h = s.th / 2 + grow, xa = stripeXin(i) - grow, xb = stripeXout(i) + grow;
    const pts = [[xa, stripeLine(i, xa) - h], [xb, stripeLine(i, xb) - h], [xb, stripeLine(i, xb) + h], [xa, stripeLine(i, xa) + h]];
    return left ? pts.map(([x, y]) => [-x, y]) : pts;
  };
  const stripePanelPts = left => {
    const s = G.stripes, pad = s.pad, top = s.n - 1, pts = [];
    const xi0 = stripeXin(top, -s.th / 2 - pad) - pad, xo0 = stripeXout(top, -s.th / 2 - pad) + pad;
    const xi1 = stripeXin(0, s.th / 2 + pad) - pad, xo1 = stripeXout(0, s.th / 2 + pad) + pad;
    const yT = x => stripeLine(top, x) - s.th / 2 - pad, yB = x => stripeLine(0, x) + s.th / 2 + pad;
    const arc = (r, cy, ya, yb) => { for (let j = 0; j <= 16; j++) { const y = lerp(ya, yb, j / 16); pts.push([Math.sqrt(r * r - (y - cy) ** 2), y]); } };
    arc(s.rIn - pad, s.cyIn, yT(xi0), yB(xi1));
    arc(s.rOut + pad, s.cyOut, yB(xo1), yT(xo0));
    return left ? pts.map(([x, y]) => [-x, y]) : pts;
  };

  // ---------- backdrop band and wing frames
  const BAND_TOP = cam ? CAM.bandTop : [[-215, 65], [-182, 44], [-160, 29], [-138, 15], [-117, 4], [-97, -4], [-77, -10.5], [-58, -17], [-36, -24], [0, -27], [36, -24], [58, -17], [76, -11.5], [98, -6], [122, 3], [146, 15], [168, 29], [190, 45], [220, 68]];
  const BAND_BOT = cam ? CAM.bandBot : [[220, 112], [188, 90], [166, 75], [144, 62], [122, 51], [100, 40], [80, 30], [64, 24.5], [36, 28], [0, 29], [-36, 28], [-64, 25.5], [-80, 32], [-100, 42], [-122, 54], [-144, 66], [-166, 79], [-186, 91], [-215, 108]];
  const bandTopPts = smoothPts(BAND_TOP, false), bandBotPts = smoothPts(BAND_BOT, false);
  const yAt = (pts, x) => { for (let i = 1; i < pts.length; i++) { const a = pts[i - 1], b = pts[i]; if ((x - a[0]) * (x - b[0]) <= 0 && a[0] !== b[0]) return lerp(a[1], b[1], (x - a[0]) / (b[0] - a[0])); } return pts[x < 0 ? 0 : pts.length - 1][1]; };

  function drawBand(g) {
    g.save(); g.translate(G.band.dx, G.band.dy);
    poly(g, [...bandTopPts, ...bandBotPts]);
    const gr = g.createLinearGradient(0, -27, 0, 70); gr.addColorStop(0, P.bandTop); gr.addColorStop(0.16, P.band); gr.addColorStop(1, P.bandBot);
    g.fillStyle = gr; g.fill();
    poly(g, bandTopPts, false);
    g.strokeStyle = P.bandGlow; g.lineWidth = 3.0; g.stroke();
    g.strokeStyle = P.bandEdge; g.lineWidth = 0.45; g.stroke();
    g.restore();
  }
  // Wing frame: follows the band edges (inset) from the far end to a slightly tilted inner end with rounded corners.
  function wingPts(W, side) {
    const N = 60, yT = x => yAt(bandTopPts, x) + W.top, yB = x => yAt(bandBotPts, x) - W.bot;
    const h = yB(W.xi) - yT(W.xi), k = Math.tan(W.tilt * D) * h / 2;
    const xTop = W.xi + side * k, xBot = W.xi - side * k;
    const raw = [];
    for (let i = 0; i <= N; i++) { const x = lerp(W.xFar, xTop, i / N); raw.push([x, yT(x)]); }
    const cTop = raw.length - 1;
    for (let i = 1; i < 8; i++) { const t = i / 8; raw.push([lerp(xTop, xBot, t), lerp(yT(xTop), yB(xBot), t)]); }
    const cBot = raw.length; raw.push([xBot, yB(xBot)]);
    for (let i = 1; i <= N; i++) { const x = lerp(xBot, W.xFar, i / N); raw.push([x, yB(x)]); }
    return roundCorners(raw, [[cTop, W.r], [cBot, W.r]]);
  }
  function drawWing(g, W, side) {
    const pts = wingPts(W, side);
    g.save(); g.translate(G.band.dx, G.band.dy);
    poly(g, pts); g.fillStyle = P.wingFill; g.fill();
    g.strokeStyle = P.wingLine; g.lineWidth = 0.42; g.stroke();
    g.restore();
  }

  // ---------- centre cluster
  function drawStripes(g, left, value, on, onTop) {
    const s = G.stripes, pts = stripePanelPts(left);
    poly(g, pts); g.fillStyle = P.stripePanel; g.fill(); g.strokeStyle = 'rgba(120,160,180,0.30)'; g.lineWidth = 0.45; g.stroke();
    const lit = Math.round(value * s.n);
    for (let i = 0; i < s.n; i++) {
      const isOn = i < lit;
      drawSlat(g, left, i, isOn ? slatColour(i, on, onTop) : P.stripeOff, isOn);
    }
  }
  // slat i (0 = bottom): centre y at x = xRef
  const stripePitch = () => G.stripes.pitch;
  const stripeY = i => G.stripes.y0 - i * G.stripes.pitch;
  const slatColour = (i, on, onTop) => (i >= G.stripes.n * 0.62 ? onTop : on);
  // '#RRGGBB' at k of its brightness
  const scaleHex = (hex, k) => `rgb(${[1, 3, 5].map(j => Math.round(parseInt(hex.slice(j, j + 2), 16) * k)).join(',')})`;
  function drawSlat(g, left, i, col, lit) {
    // lit slats (V20): the gap down to the slat below (always lit too, as the lit slats run up from slat 0) in the
    // slat's colour at half brightness, as the reference's lit gaps measure (20,113,95) against its slats' (49,219,195);
    // this replaced an earlier build's 22 % glow round each lit slat. Each lit slat is one sprite in the game, so the gap is part of it.
    if (lit && i > 0) {
      const a = slatPts(i - 1, left, 0.15), b = slatPts(i, left, 0.15);   // 0.15: clear of the slats' 0.3 outline
      poly(g, [a[0], a[1], b[2], b[3]]); g.fillStyle = scaleHex(col, G.stripes.litGap); g.fill();
    }
    // one flat colour along the whole slat (V20: the reference keeps its lightness end to end; the old
    // top-to-bottom shade darkened the sloping slats toward their outer ends)
    poly(g, slatPts(i, left)); g.fillStyle = col; g.fill(); g.strokeStyle = col; g.lineWidth = 0.3; g.stroke();
  }

  function drawCapsule(g, left, level, word) {
    const c = G.caps, pts = capsulePts(left), y0 = c.yTop, y1 = c.yBot;
    poly(g, pts); g.fillStyle = P.capOff; g.fill();
    const lv = Math.min(1, Math.max(0, level)), topY = lerp(y1, y0, lv);
    if (lv > 0.02) {
      g.save(); poly(g, pts); g.clip();
      const gr = g.createLinearGradient(0, y0, 0, y1); gr.addColorStop(0, P.capOnTop); gr.addColorStop(1, P.capOnBot);
      g.fillStyle = gr; g.fillRect(-80, topY, 160, y1 - topY + 1); g.restore();
    }
    const lit = lv > 0.5;
    poly(g, pts);
    if (lit) { g.strokeStyle = 'rgba(80,200,255,0.25)'; g.lineWidth = 2.2; g.stroke(); }
    g.strokeStyle = lit ? P.capOnLine : P.capOffLine; g.lineWidth = 0.6; g.stroke();
    const n = word.length, ya = y0 + 3.6, yb = y1 - 3.6;
    [...word].forEach((ch, i) => {
      const t = n === 1 ? 0.5 : i / (n - 1);
      let x, y;
      if (c.txtR) { const a = lerp(c.txtA0, c.txtA1, t) * D; x = c.txtR * Math.cos(a); y = c.txtR * Math.sin(a); }
      else { y = lerp(ya, yb, t); x = (capsXin(y) + capsXout(y)) / 2; }
      if (left) x = -x;
      text(g, ch, x, y, c.fs, lv > 0.02 && y >= topY ? P.capOnText : P.capOffText, { w: 760 });
    });
  }

  // Battery parts (split so the addon can export the frame, the fill and the bolt as separate layers;
  // the fill sits 0.1 inside the glow, so drawing the frame before the fill looks the same).
  function battInterior(g, charging) { const b = G.batt; rr(g, b.x - b.w / 2, b.y - b.h / 2, b.w, b.h, b.r); g.fillStyle = charging ? P.battCharge : P.battIn; g.fill(); }
  function battFill(g, soc) {
    const b = G.batt, x = b.x - b.w / 2, y = b.y - b.h / 2;
    const gr = g.createLinearGradient(0, y, 0, y + b.h); gr.addColorStop(0, P.battFillTop); gr.addColorStop(1, P.battFillBot);
    rr(g, x + 0.9, y + 0.9, (b.w - 1.8) * Math.min(1, soc), b.h - 1.8, 0.9); g.fillStyle = gr; g.fill();
  }
  function battOutline(g) {
    const b = G.batt, x = b.x - b.w / 2, y = b.y - b.h / 2;
    rr(g, x, y, b.w, b.h, b.r); g.strokeStyle = 'rgba(98,194,242,0.22)'; g.lineWidth = 1.6; g.stroke();
    g.strokeStyle = P.battLine; g.lineWidth = 0.55; g.stroke();
    const nw = b.nubW || 1.5, nh = b.nubH || 3.4; rr(g, x + b.w + 0.3, b.y - nh / 2, nw, nh, nw / 2); g.fillStyle = P.battLine; g.fill();
  }
  function battBolt(g) {
    const b = G.batt, cx = b.bx ?? b.x, cy = b.by ?? b.y, k = b.bolt || 1;
    poly(g, [[1.1, -2.9], [-1.4, 0.4], [-0.1, 0.4], [-0.9, 2.9], [1.5, -0.4], [0.2, -0.4]].map(([x, y]) => [cx + k * x, cy + k * y]));
    g.fillStyle = P.bolt; g.fill();
  }
  function drawBattery(g, soc, charging) {
    battInterior(g, charging);
    if (soc > 0) battFill(g, soc);
    battOutline(g);
    battBolt(g); // always shown (docs/research 3.4)
  }

  // a vertical gradient over y0..y1 from a [[stop, colour], ...] list
  function vGrad(g, y0, y1, stops) { const gr = g.createLinearGradient(0, y0, 0, y1); stops.forEach(([t, c]) => gr.addColorStop(t, c)); return gr; }
  // the collar (V17): a ring from just inside the face out to G.disc.r, see-through round the dial's upper half
  // (P.discOuterTop above collarFade[0]) and dark from collarFade[1] down, a little darker below the dial's middle
  // (P.discOuter to P.discOuterBot over collarLow); nothing under the face, so its translucency shows the scene
  function drawCollar(g) {
    const d = G.disc, [ya, yb] = d.collarFade, [yc, yd] = d.collarLow, T = y => (y - ya) / (d.r - ya);
    g.beginPath(); g.arc(0, 0, d.r, 0, 2 * Math.PI); g.moveTo(d.inner - 0.2, 0); g.arc(0, 0, d.inner - 0.2, 0, 2 * Math.PI);
    g.fillStyle = vGrad(g, ya, d.r, [[0, P.discOuterTop], [T(yb), P.discOuter], [T(yc), P.discOuter], [T(yd), P.discOuterBot], [1, P.discOuterBot]]);
    g.fill('evenodd');
  }
  function drawDisc(g) {
    const d = G.disc, m = d.mesh;
    // translucent face (V18): tint stops P.face, alpha in the colours
    g.beginPath(); g.arc(0, 0, d.inner, 0, 2 * Math.PI); g.fillStyle = vGrad(g, -d.inner, d.inner, P.face); g.fill();
    // square mesh over the face (V19; was dots on a 2.2 lattice): lines m.w wide, m.pitch apart, on both axes,
    // the ink set per height (P.mesh: light on the light top, stronger lower down, so the contrast stays about even as on
    // the reference); every second line once more (P.mesh2, the reference's 2.0 harmonic). One stroke per path, so
    // crossings are not darker than the lines.
    g.save(); g.beginPath(); g.arc(0, 0, d.inner - 0.2, 0, 2 * Math.PI); g.clip();
    const n = Math.ceil(d.inner / m.pitch) + 1;
    const lines = keep => {
      g.beginPath();
      for (let k = -n; k < n; k++) {
        if (!keep(k)) continue;
        const p = (k + 0.5) * m.pitch;
        g.moveTo(p, -d.inner); g.lineTo(p, d.inner); g.moveTo(-d.inner, p); g.lineTo(d.inner, p);
      }
    };
    g.lineWidth = m.w; g.lineCap = 'butt';
    lines(() => true); g.strokeStyle = vGrad(g, -d.inner, d.inner, P.mesh); g.stroke();
    lines(k => (k & 1) === 0); g.strokeStyle = vGrad(g, -d.inner, d.inner, P.mesh2); g.stroke();
    g.restore();
    // rings (V21): the bright ring at rim with its soft edge, the thin light ring further out; both neutral,
    // fading toward the bottom and a little at the very top (from 60 degrees up), like the reference's
    g.beginPath(); g.arc(0, 0, d.rim, 0, 2 * Math.PI);
    g.strokeStyle = vGrad(g, -d.rim, d.rim, P.ringGlow); g.lineWidth = 2.4; g.stroke();
    g.strokeStyle = vGrad(g, -d.rim, d.rim, P.ring); g.lineWidth = d.ring; g.stroke();
    if (d.light) { g.beginPath(); g.arc(0, 0, d.light, 0, 2 * Math.PI); g.strokeStyle = vGrad(g, -d.light, d.light, P.ringLight); g.lineWidth = d.lightW; g.stroke(); }
  }
  function drawBoost(g, on) {
    const B = G.boost;
    const radii = B.hatchR || [...Array(B.hatchN).keys()].map(i => B.hatch0 + i * B.hatchStep);
    for (let i = 0; i < radii.length; i++) {
      const r = radii[i], y0 = B.hy0 ?? B.y - B.hatchHalf, y1 = B.hy1 ?? B.y + B.hatchHalf;
      const aTop = Math.asin(y0 / r), aBot = Math.asin(y1 / r);
      g.strokeStyle = on ? P.hatchOn : P.hatch; g.lineWidth = 0.45;
      g.globalAlpha = on ? 1 - i * 0.1 : 0.95 - i * 0.08;
      g.beginPath(); g.arc(0, 0, r, aTop, aBot); g.stroke();
      g.beginPath(); g.arc(0, 0, r, Math.PI - aBot, Math.PI - aTop); g.stroke();
    }
    g.globalAlpha = 1;
    rr(g, -B.w / 2, B.y - B.h / 2, B.w, B.h, B.r ?? 0.5); g.fillStyle = on ? P.boostOn : P.boostFill; g.fill();
    g.strokeStyle = on ? P.boostOnLine : P.boostLine; g.lineWidth = 0.3; g.stroke();
    text(g, 'BOOST', 0, B.y, B.fs, on ? P.boostOnText : (P.boostText || P.dim), { tr: B.tr });
  }
  function drawOT(g, on) {
    const O = G.ot, ox = -O.w / 2, oy = O.y - O.h / 2;
    if (on) {
      rr(g, ox, oy, O.w, O.h, 1); g.strokeStyle = P.otOnGlow; g.lineWidth = 2.4; g.stroke();
      const og = g.createLinearGradient(0, oy, 0, oy + O.h); og.addColorStop(0, P.otOnTop); og.addColorStop(1, P.otOnBot);
      rr(g, ox, oy, O.w, O.h, 1); g.fillStyle = og; g.fill(); g.strokeStyle = P.otOnLine; g.lineWidth = 1.1; g.stroke();
      // letters glow a little, as on the broadcast
      g.save(); g.shadowColor = P.otOnGlow; g.shadowBlur = 1.6;
      text(g, 'OVERTAKE', 0, O.y, O.fs, P.otOnText, { tr: O.tr, w: 760 });
      g.restore();
    } else {
      rr(g, ox, oy, O.w, O.h, 1); g.fillStyle = P.otOff; g.fill(); g.strokeStyle = P.otOffLine; g.lineWidth = 0.5; g.stroke();
      text(g, 'OVERTAKE', 0, O.y, O.fs, P.otOffText, { tr: O.tr });
    }
  }
  // ERS deploy mode (2025 cars): caption in the Boost slot, the mode in a pill in the Overtake slot. NONE uses the
  // OVERTAKE pill's off look, MEDIUM the unlit Boost look, HOTLAP the lit Boost look, OVERTAKE the lit OVERTAKE pill.
  function drawErsCaption(g) { const c = GV.ersCap; text(g, 'ERS MODE', 0, c.y, c.fs, P.dim, { tr: c.tr }); }
  function drawErsMode(g, mode) {
    if (mode === 3) return drawOT(g, true);
    const E = GV.ersPill, ox = -E.w / 2, oy = E.y - E.h / 2;
    const look = [[P.otOff, P.otOffLine, P.otOffText, 0.5], [P.boostFill, P.boostLine, P.boostText, 0.4],
                  [P.boostOn, P.boostOnLine, P.boostOnText, 0.4]][mode];
    if (!look) return;
    rr(g, ox, oy, E.w, E.h, E.r); g.fillStyle = look[0]; g.fill(); g.strokeStyle = look[1]; g.lineWidth = look[3]; g.stroke();
    text(g, ERS_MODES[mode], 0, E.y, E.fs, look[2], { tr: E.tr, w: mode === 2 ? 760 : 700 });
  }
  const speedText = (g, kmh) => text(g, String(Math.round(kmh)), 0, G.speed.y, G.speed.fs, P.white, { tr: G.speed.tr, w: 780 });
  const mphText = (g, kmh) => text(g, String(Math.round(kmh * 0.621371)), 0, G.mph.y, G.mph.fs, P.white, { tr: G.mph.tr, w: 780 });
  function drawDial(g, st) {
    const C = carClass(st);
    drawDisc(g);
    if (gOn(st)) return drawGDial(g, st);
    text(g, 'KM/H', 0, G.kmh.y, G.kmh.fs, P.label, { tr: G.kmh.tr });
    speedText(g, st.kmh);
    if (C.pills === 'boost_ot') { drawBoost(g, st.boost); drawOT(g, st.ot); }
    else if (C.pills === 'ers_mode') { drawErsCaption(g); drawErsMode(g, ersModeIndex(st)); }
    mphText(g, st.kmh);
    text(g, 'MPH', 0, G.mphLbl.y, G.mphLbl.fs, P.label, { tr: G.mphLbl.tr });
    if (C.battery) drawBattery(g, st.soc, st.recharge > 0.3);
  }

  // ---------- G-force variant (optional, off by default): st.gmeter === true (st.mode === 'spa' is the old name).
  // The Spa 2026 world feed's centre: no speed, BOOST / OVERTAKE, battery or RECHARGE / DEPLOY; three rings, the value
  // and an indicator drawn toward the force the driver feels (a left-hand corner pushes it right, braking pushes it up).
  // State: st.gLat / st.gLong in the game's convention (g; lat + = toward the car's left, long + = speeding up), or
  // st.g (magnitude) with st.gDir (felt-force direction, degrees: 0 right, 90 down = speeding up, -90 up = braking).
  // st.gOk === false, or no g at all, = unavailable: no value and no indicator, label dimmed. st.gWide and
  // st.gRedDigits override the model's hysteresis / flash (the renderer is stateless); see docs/gmeter/design.md.
  const gOn = st => !!st && (st.gmeter === true || st.mode === 'spa');
  const gFormat = m => Math.min(9.9, Math.max(0, Math.round(m * 10) / 10)).toFixed(1);
  function gView(st) {
    const M = G.gm;
    let m = st.g, dir = st.gDir;
    if (Number.isFinite(st.gLat) && Number.isFinite(st.gLong)) { m = Math.hypot(st.gLat, st.gLong); dir = Math.atan2(st.gLong, st.gLat) / D; }
    if (st.gOk === false || !Number.isFinite(m)) return { ok: false };
    if (!Number.isFinite(dir)) dir = 0;
    const axis = ((Math.round(dir / 90) * 90) % 360 + 360) % 360;   // nearest of right / down / left / up
    const wide = st.gWide ?? m >= M.wide, S = M.arc.seg, n = Math.round(360 / S);
    // cyan arc = whole segments (segment k is centred on k * seg degrees): the two nearest dir, or three centred on it
    const k = wide ? Math.round(dir / S) - 1 : Math.floor(dir / S), count = wide ? 3 : 2;
    const segs = Array.from({ length: count }, (_, i) => (((k + i) % n) + n) % n);
    return { ok: true, g: m, dir, axis, segs, arcFrom: (k - 0.5) * S, arcTo: (k + count - 0.5) * S,
             arc: m >= M.on, wide, red: m >= M.redOn, digitsRed: st.gRedDigits ?? m >= M.digitsRed };
  }
  function drawGRings(g) { G.gm.rings.forEach(r => { g.beginPath(); g.arc(0, 0, r, 0, 7); g.strokeStyle = P.gRing; g.lineWidth = G.gm.ringW; g.stroke(); }); }
  function drawGLabel(g, dim) { const L = G.gm.lbl; text(g, 'G-FORCE', 0, L.y, L.fs, dim ? P.dim : P.label, { tr: L.tr }); }
  function drawGStatic(g) { drawGRings(g); drawGLabel(g, false); }   // the variant's fixed layer (with drawDisc)
  // the value "d.d" in fixed slots: each digit centred in the widest digit's advance, so the value does not shift
  // sideways as it changes (Saira's figures are proportional: "1" is 6.2 units wide, "8" 10.9). The game draws it
  // from one sprite per digit and place (tools/export_native.js), which needs exactly this layout.
  function gSlots(g) {
    const V = G.gm.val, prevW = WEIGHT; WEIGHT = 780; g.save();
    const a = Object.fromEntries([...'0123456789.'].map(ch => [ch, adv(g, ch, V.fs)[0]]));
    g.restore(); WEIGHT = prevW;
    const A = Math.max(...[...'0123456789'].map(ch => a[ch])), w = 2 * A + a['.'] + 2 * V.tr, x0 = -w / 2;
    return { adv: a, A, w, units: x0, dot: x0 + A + V.tr, tenths: x0 + A + V.tr + a['.'] + V.tr };
  }
  function gChar(g, ch, x, red) {
    const V = G.gm.val; text(g, ch, x * V.sx, V.y, V.fs, red ? P.gRed : P.white, { align: 'left', sx: V.sx, w: 780 });
  }
  function gText(g, m, red) {
    const L = gSlots(g), s = gFormat(m);
    gChar(g, s[0], L.units + (L.A - L.adv[s[0]]) / 2, red);
    gChar(g, '.', L.dot, red);
    gChar(g, s[2], L.tenths + (L.A - L.adv[s[2]]) / 2, red);
    return L.w * G.gm.val.sx;
  }
  function gSector(g, r0, r1, dirDeg, halfDeg, col) {
    const a0 = (dirDeg - halfDeg) * D, a1 = (dirDeg + halfDeg) * D;
    g.beginPath(); g.arc(0, 0, r1, a0, a1); g.arc(0, 0, r0, a1, a0, true); g.closePath(); g.fillStyle = col; g.fill();
  }
  // the lit segments as one sector (no seams); drawGSeg draws one segment, for a later sprite export
  function drawGArc(g, v) { const a = G.gm.arc; gSector(g, a.r0, a.r1, (v.arcFrom + v.arcTo) / 2, (v.arcTo - v.arcFrom) / 2, P.gCyan); }
  function drawGSeg(g, k) { const a = G.gm.arc; gSector(g, a.r0, a.r1, k * a.seg, a.seg / 2, P.gCyan); }
  // a bar between two rings: curved ends on the rings, straight sides parallel to the axis (Spa: the white and red
  // bars have the same height, about 15 units, although they sit at different radii)
  function drawGBlock(g, axisDeg, layer) {
    const b = G.gm[layer], a0 = Math.asin(b.halfH / b.r0), a1 = Math.asin(b.halfH / b.r1), t = axisDeg * D;
    g.beginPath(); g.arc(0, 0, b.r1, t - a1, t + a1); g.arc(0, 0, b.r0, t + a0, t - a0, true); g.closePath();
    g.fillStyle = layer === 'red' ? P.gRed : P.gWhite; g.fill();
  }
  function drawGDial(g, st) {
    drawGRings(g);
    const v = gView(st);
    if (!v.ok) return drawGLabel(g, true);
    if (v.arc) {
      drawGArc(g, v);
      drawGBlock(g, v.axis, 'white');
      if (v.red) drawGBlock(g, v.axis, 'red');
    }
    gText(g, v.g, v.digitsRed);
    drawGLabel(g, false);
  }

  // ---------- left wing: turn + name lanes
  function turnArrow(g, right) {
    // compact road-sign arrow (origin = centre of the bend): short stem rising on the right,
    // a thick 90-degree bend, and a large head pointing into the corner
    g.save(); if (right) g.scale(-1, 1);
    // road-sign arrow; its pose (G.turn.arrow) is an NCC fit to the Interlagos arrow. The reference's traced 50 % contour
    // is not used as a shape: it is invalid (it leaks into the light car body behind the panel and loses the fading stem).
    g.beginPath();
    g.moveTo(5.0, 5.0); g.lineTo(5.0, 0); g.arc(0, 0, 5.0, 0, -Math.PI / 2, true);
    g.lineTo(-1.5, -5.0); g.lineTo(-1.5, -7.6); g.lineTo(-6.1, -3.3); g.lineTo(-1.5, 1.0); g.lineTo(-1.5, -1.6);
    g.lineTo(0, -1.6); g.arc(0, 0, 1.6, -Math.PI / 2, 0, false); g.lineTo(1.6, 5.0); g.closePath();
    const sh = g.createLinearGradient(-6, -7, 5, 5); sh.addColorStop(0, '#F4F8FA'); sh.addColorStop(1, '#AFC0CA');
    g.fillStyle = sh; g.fill(); g.restore();
  }
  // right turns: the left arrow reflected across the band's normal at the arrow (band direction = TURN label angle),
  // so both arrows sit the same way in the band
  function drawTurnArrow(g, right) {
    const a = G.turn.arrow; g.save(); g.translate(a.x, a.y);
    if (right) { const p = 2 * (G.turn.lbl.rot + 90) * D; g.transform(Math.cos(p), Math.sin(p), Math.sin(p), -Math.cos(p), 0, 0); }
    frame(g, a.rot, a.lean); g.scale(a.s, a.s); turnArrow(g, false); g.restore();
  }
  function drawTurnNumber(g, s) { const n = G.turn.num; text(g, String(s), n.x, n.y, n.fs, P.white, { tr: n.tr, rot: n.rot, lean: n.lean, w: 760 }); }
  function drawTurnLabel(g) { const l = G.turn.lbl; text(g, 'TURN', l.x, l.y, l.fs, P.label, { tr: l.tr, rot: l.rot, lean: l.lean }); }
  function drawTurn(g, st) {
    if (st.turn) { drawTurnArrow(g, st.turnDir === 'R'); drawTurnNumber(g, st.turn); drawTurnLabel(g); }
  }

  function lanePoint(n, u, v) {
    const a = n.rot * D, ux = Math.cos(a), uy = Math.sin(a), vx = -uy, vy = ux;
    const vv = v + (u < 0 ? n.bend * u * u : 0);
    return [n.x + ux * u + vx * vv, n.y + uy * u + vy * vv];
  }
  function laneAngle(n, u, v = 0) { const p = lanePoint(n, u - 0.5, v), q = lanePoint(n, u + 0.5, v); return Math.atan2(q[1] - p[1], q[0] - p[0]); }
  // text along the bent lane: right-aligned to end at uEnd, or (startAt) left-aligned from it
  function laneText(g, n, s, uEnd, v, px, color, wt, startAt = false) {
    const prev = WEIGHT; WEIGHT = wt; const a = adv(g, s, px); let u = startAt ? uEnd : uEnd - (sum(a) + n.tr * (a.length - 1));
    [...s].forEach((ch, i) => {
      const uc = u + a[i] / 2, [x, y] = lanePoint(n, uc, v), ang = laneAngle(n, uc, v);
      const l = n.leanRel !== undefined ? ang + n.leanRel * D : n.lean * D;   // italic: a fixed lean from the lane normal
      g.save(); g.translate(x, y); g.transform(Math.cos(ang), Math.sin(ang), -Math.sin(l), Math.cos(l), 0, 0);
      font(g, px); g.fillStyle = color; g.textBaseline = 'alphabetic'; g.fillText(ch, -a[i] / 2, CAP * px / 2); g.restore();
      u += a[i] + n.tr;
    });
    WEIGHT = prev;
  }
  function laneLine(g, n, v, u0, u1, color, w) {
    g.beginPath(); for (let i = 0; i <= 24; i++) { const p = lanePoint(n, lerp(u0, u1, i / 24), v); i ? g.lineTo(...p) : g.moveTo(...p); }
    g.strokeStyle = color; g.lineWidth = w; g.lineCap = 'round'; g.stroke();
  }
  function drawRails(g, colour) {
    // driver card: team-colour rails above and below the driver's lane, closed at the far end, open toward the dial
    const n = G.names;
    g.beginPath();
    for (let i = 0; i <= 30; i++) { const p = lanePoint(n, lerp(n.railA0 ?? 0, n.cardEnd, i / 30), n.lineA); i ? g.lineTo(...p) : g.moveTo(...p); }
    for (let i = 0; i <= 30; i++) g.lineTo(...lanePoint(n, lerp(n.cardEnd, n.railB0 ?? 4, i / 30), n.lineB));
    g.strokeStyle = colour; g.lineWidth = n.lineW; g.lineCap = 'round'; g.lineJoin = 'round'; g.stroke();
  }
  function drawNames(g, st) {
    const n = G.names, team = st.team || '#27F4D2';
    drawRails(g, team);
    // car one place ahead above, this car below: "<position> <SURNAME>" (session classification)
    const line = (pos, name, shift, v, fs, col, wt) => {
      if (pos) laneText(g, n, String(pos), n.numEnd + shift, v, fs, col, wt);
      laneText(g, n, name, n.numEnd + shift + n.numGap, v, fs, col, wt, true);
    };
    if (st.rival) line(st.rivalPos, st.rival, n.rivShift, -n.laneGap, n.rivFs, '#E3EAEE', 740);
    line(st.pos ?? st.number, st.driver, 0, n.drvV || 0, n.drvFs, P.white, 760);
  }

  // ---------- right wing: active aero + gears
  function drawAeroLabel(g, col) {
    const a = G.aero;
    text(g, 'ACTIVE', a.x1, a.y1, a.fs, col, { tr: a.tr, rot: a.rot, lean: a.lean, w: 760 });
    text(g, 'AERO', a.x2, a.y2, a.fs, col, { tr: a.tr, rot: a.rot, lean: a.lean, w: 760 });
  }
  // one bar of the active-aero symbol: s = +1 / -1 picks the bar; straight: its "=" pose, else its "//" pose. The +1
  // slash and the +1 flat bar are the same bar in the two modes (the game turns one into the other)
  function drawAeroBar(g, straight, s, col) {
    const a = G.aero;
    g.fillStyle = col;
    const bar = (cx, cy, len, ang, th = a.barTh) => { g.save(); g.translate(cx, cy); g.rotate(ang * D); rr(g, -len / 2, -th / 2, len, th, th / 2); g.fill(); g.restore(); };
    if (straight) bar(a.barX + s * a.barDx / 2, a.barY + s * a.barDy / 2, a.barLen, a.barAng);   // "=" (sheared with the wing): two flat bars, the lower one set back toward the centre
    else bar(a.barX + s * a.slHx, a.barY + s * a.slHy, a.slLen, a.slAng, a.slTh);                 // "//": two steep slashes
  }
  function drawAeroBars(g, straight, col) {
    if (straight) { drawAeroBar(g, true, 1, col); drawAeroBar(g, true, -1, col); }
    else { drawAeroBar(g, false, -1, col); drawAeroBar(g, false, 1, col); }
  }
  function drawAero(g, st) {
    // white in both modes on the broadcast (docs/research 3.9); aeroTint only reproduces the fan-made screenshot
    const straight = st.aero, tint = straight && st.aeroTint && st.theme === 'screenshot';
    drawAeroLabel(g, tint ? P.aeroOn : P.white);
    drawAeroBars(g, straight, tint ? P.aeroOn : P.aeroBar);
  }
  // DRS pill (2025 and F2 cars), in the active-aero spot. look: 'off' (grey: unavailable), 'avail' (white outline:
  // available), 'open' (green: open); see drsLook for the game's states.
  function drawDRS(g, look) {
    const d = GV.drs;
    g.save(); g.translate(d.x, d.y); frame(g, d.rot, d.lean);
    const path = () => rr(g, -d.w / 2, -d.h / 2, d.w, d.h, d.r);
    let txt;
    if (look === 'open') {
      path(); g.strokeStyle = PV.drsOpenGlow; g.lineWidth = 2.4; g.stroke();
      path(); g.fillStyle = PV.drsOpen; g.fill(); g.strokeStyle = PV.drsOpenLine; g.lineWidth = d.line; g.stroke();
      txt = PV.drsOpenText;
    } else if (look === 'avail') {
      path(); g.fillStyle = PV.drsAvailFill; g.fill(); g.strokeStyle = PV.drsAvailLine; g.lineWidth = d.line; g.stroke();
      txt = PV.drsAvailText;
    } else {
      path(); g.fillStyle = PV.drsOff; g.fill(); g.strokeStyle = PV.drsOffLine; g.lineWidth = 0.5; g.stroke();
      txt = PV.drsOffText;
    }
    text(g, 'DRS', 0, 0, d.fs, txt, { tr: d.tr, w: 760 });
    g.restore();
  }

  // Gear strip: a quadratic bezier (digits on it) and the RPM track offset from it by `track`
  const RPM_T0 = -0.035, RPM_T1 = 1.03;
  function gearPt(t, off) { const q = G.gears, p = bez(q.p0, q.p1, q.p2, t), [tx, ty] = bezTan(q.p0, q.p1, q.p2, t); return [p[0] - ty * off, p[1] + tx * off]; }
  function rpmPath(g, a, b) { g.beginPath(); for (let i = 0; i <= 40; i++) { const p = gearPt(lerp(a, b, i / 40), G.gears.track); i ? g.lineTo(...p) : g.moveTo(...p); } }
  function drawGearTrack(g) { rpmPath(g, RPM_T0, RPM_T1); g.strokeStyle = P.track; g.lineWidth = 0.5; g.lineCap = 'round'; g.stroke(); }
  function drawRpmBar(g, rpm, team) {
    const q = G.gears, tf = lerp(RPM_T0, RPM_T1, Math.max(0, Math.min(1, rpm)));
    rpmPath(g, RPM_T0, tf); g.lineCap = 'round';
    g.strokeStyle = team; g.globalAlpha = 0.22; g.lineWidth = q.trackW * 2.3; g.stroke(); g.globalAlpha = 1; g.lineWidth = q.trackW; g.stroke();
    g.strokeStyle = 'rgba(225,255,250,0.55)'; g.lineWidth = q.trackW * 0.35; g.stroke();
  }
  function drawGearMarker(g) { const q = G.gears; if (!(q.mr > 0)) return; g.beginPath(); g.arc(q.mx, q.my, q.mr, 0, 7); g.strokeStyle = 'rgba(140,160,172,0.75)'; g.lineWidth = 0.4; g.stroke(); }
  function drawGearDigit(g, i, on) {
    const q = G.gears, t = i / 8, [x, y] = gearPt(t, 0), [tx, ty] = bezTan(q.p0, q.p1, q.p2, t);
    text(g, 'N12345678'[i], x, y, on ? q.fsOn : q.fs, on ? P.white : P.gearDim, { rot: Math.atan2(ty, tx) / D, lean: q.lean, w: on ? (q.wOn ?? 780) : (q.w ?? 700) });
  }
  function drawGearLabels(g) {
    const q = G.gears;
    text(g, 'GEARS', q.gx, q.gy, q.lfs, P.gearLbl, { rot: q.grot, lean: q.llean, tr: 0.3 });
    text(g, 'RPM x1000', q.rx, q.ry, q.lfs, P.gearLbl, { rot: q.rrot, lean: q.llean, tr: 0.25 });
    // scale ends: "0" before the bar's start, "15" past its end (x1000 rpm)
    [[q.r0t, '0'], [q.r15t, '15']].forEach(([t, s]) => {
      const [x, y] = gearPt(t, q.track + q.rEndOff), [tx, ty] = bezTan(q.p0, q.p1, q.p2, Math.min(1, Math.max(0, t)));
      text(g, s, x, y, q.rEndFs, P.gearLbl, { rot: Math.atan2(ty, tx) / D, lean: q.lean, tr: 0.2 });
    });
  }
  function drawGears(g, st) {
    drawGearTrack(g);
    drawRpmBar(g, st.rpm, st.team || '#27F4D2');
    drawGearMarker(g);
    for (let i = 0; i < 9; i++) drawGearDigit(g, i, String(st.gear) === 'N12345678'[i] || (i === 0 && st.gear === 0));
    drawGearLabels(g);
  }

  // ---------- centre cluster (capsules, stripes, labels, dial), scaled about the dial centre
  function drawCentreLabels(g) {
    const B = G.brakeLbl, T = G.throttleLbl;
    text(g, 'BRAKE', B.x, B.y, G.lblFs, '#E9EEF1', { rot: B.rot, lean: B.lean, tr: B.tr ?? 0.35 });
    text(g, 'THROTTLE', T.x, T.y, G.lblFs, '#E9EEF1', { rot: T.rot, lean: T.lean, tr: T.tr ?? 0.35 });
  }
  // design plane -> HUD units: centreScale, and for theme 'screenshot' the Interlagos camera's affine view
  function centreFrame(g, st) {
    const M = (st && st.theme === 'screenshot' && G.perspShot) || [1, 0, 0, 1], k = G.centreScale;
    g.transform(M[0] * k, M[1] * k, M[2] * k, M[3] * k, 0, 0);
  }
  function drawCentre(g, st) {
    g.save(); centreFrame(g, st);
    drawCollar(g);   // the collar around the dial (see-through above its waist)
    if (!gOn(st) && carClass(st).capsules) { drawCapsule(g, true, st.recharge, 'RECHARGE'); drawCapsule(g, false, st.deploy, 'DEPLOY'); }   // G variant, F2: no capsules
    drawStripes(g, true, st.brake, P.brake, P.brakeTop);
    drawStripes(g, false, st.throttle, P.throttle, P.throttleTop);
    drawCentreLabels(g);
    drawDial(g, st);
    g.restore();
  }

  // ---------- full HUD
  function draw(g, st) {
    g.save(); g.lineJoin = 'round';
    drawBand(g);
    drawWing(g, G.wings.L, -1); drawWing(g, G.wings.R, 1);
    drawNames(g, st);
    drawTurn(g, st);
    drawCentre(g, st);
    if (carClass(st).drs) drawDRS(g, drsLook(st)); else drawAero(g, st);
    drawGears(g, st);
    g.restore();
  }

  // Static / moving pieces for the addon's texture export (export.html).
  const internals = {
    D, FONT, CAP, text, frame, rr, poly, lerp, bez, bezTan, lanePoint, laneAngle, laneText, capsulePts, stripePanelPts,
    capsXin, capsXout, stripeXin, stripeXout, stripeLine, slatPts, slatColour, stripeY, stripePitch, drawSlat, centreFrame, drawCentreLabels, drawBand, drawWing, drawStripes, drawCapsule, drawCollar, drawDisc, drawBoost, drawOT, speedText,
    mphText, battInterior, battFill, battOutline, battBolt, drawGStatic, gText, gSlots, gChar, gOn, gView, gFormat, drawGRings, drawGLabel,
    drawGArc, drawGSeg, drawGBlock, gSector, turnArrow, drawTurnArrow, drawTurnNumber,
    drawTurnLabel, drawRails, drawAeroLabel, drawAeroBars, drawAeroBar, bandTopPts, gearPt, drawGearTrack, drawRpmBar, drawGearMarker,
    drawGearDigit, drawGearLabels, RPM_T0, RPM_T1,
    // car classes (the 2025 and F2 variants)
    CLASSES, carClass, drsLook, ersModeIndex, ERS_MODES, drawDRS, drawErsCaption, drawErsMode,
  };
  return { LAYOUT: cam ? 'cam' : 'tv', draw, G, P, GV, PV, CLASSES, internals, parts: { drawCentre, drawNames, drawTurn, drawAero, drawDRS, drawGears, drawDial, drawBand, drawWing } };
};
// window.HALO_LAYOUT = 'cam' before this file loads picks the symmetric layout; HALO_MAKE('cam') makes a second one
const HALO = HALO_MAKE(typeof window !== 'undefined' && window.HALO_LAYOUT);
