// 2026 halo onboard HUD — reference renderer (v3).
// Units: broadcast pixels of a 640x360 frame (x3 = 1080p), origin = dial centre, y down.
// The C++ overlay addon is generated from this file: its textures are rendered from these
// functions and its dynamic parts use the same numbers in G (geometry) and P (palette).
//
// The wings are drawn the way the broadcast maps them onto the curved halo: text runs along
// the band, but letter verticals lean toward the centre ("lean", degrees from screen-vertical,
// positive = top to the right) instead of staying perpendicular to the baseline.
const HALO = (() => {
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
    disc: { r: 39.37, inner: 34.4, rim: 35.0, ring: 1.2, light: 36.47, lightW: 0.55, dot: 2.2, dotY: 2.0, dotR: 0.3, stagger: false },
    kmh: { y: -23.934, fs: 4.974, tr: 0.02 },
    speed: { y: -14.874, fs: 13.529, tr: 0.35, sx: 1.068 },
    boost: { y: -2.617, w: 27.8, h: 5.423, r: 3.0, fs: 3.938, tr: 0.5, hatchR: [15.6, 18.5, 20.8, 22.5, 24.0, 25.6, 26.9], hy0: -6.5, hy1: 0.5 },
    ot: { y: 4.718, w: 46.629, h: 5.05, fs: 3.924, tr: 0.243 },
    mph: { y: 13.459, fs: 11.012, tr: 0.5, sx: 1.013 },
    mphLbl: { y: 21.88, fs: 4.388, tr: 0.595 },
    batt: { x: 0.0, y: 32.41, w: 24.9, h: 7.45, r: 1.9, nubW: 0.75, nubH: 3.0, bolt: 0.86, bx: -0.19, by: 32.19 },
    // capsules: annulus rIn..rOut between yTop and yBot; letters upright, evenly spaced in angle on radius txtR
    caps: { rIn: 39.311, rOut: 50.854, yTop: -18.105, yBot: 22.059, rcOut: 3.0, rcIn: 2.0, fs: 3.602, txtR: 45.142, txtA0: -15.518, txtA1: 24.508 },
    // slats: n parallelograms with vertical ends on circles (rIn, centre y cyIn) and (rOut, cyOut); slat 0 = bottom,
    // centre y at x = xRef is y0 - i * pitch; every slat slopes k (down toward the outside)
    stripes: { rIn: 53.058, cyIn: 2.805, rOut: 66.528, cyOut: 1.075, n: 10, y0: 22.781, pitch: 3.54, xRef: 59, k: 0.233, th: 2.16, pad: 0.9 },
    brakeLbl: { x: -53.423, y: 31.523, rot: -15.979, lean: 16.193 },
    throttleLbl: { x: 51.665, y: 30.667, rot: 13.023, lean: 2.98 },
    lblFs: 4.541,
    // values below were fitted against two Melbourne frames, t=205 s and t=262 s (fit.html, normalised cross-correlation)
    turn: {
      arrow: { x: -87.419, y: 12.119, s: 1, rot: -53.081, lean: -28.65 },
      lbl: { x: -82.816, y: 23.817, fs: 4.497, rot: -20.6, lean: -1.6, tr: 0.3 },
      num: { x: -83.922, y: 31.143, fs: 7.934, rot: -20.6, lean: -1.6, tr: 0.3 },
    },
    // "<position> <SURNAME>": the number ends at numEnd (lane u), the surname starts numGap after it
    names: { x: -106.759, y: 37.261, rot: -26.18, bend: 0.002305, lean: -11, leanRel: 22, drvV: 0.73, laneGap: 13.784, drvFs: 8.508, rivFs: 6.963, rivShift: 3.703, tr: 1.26,
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
  };

  const P = {
    bandTop: 'rgba(24,62,78,0.50)', band: 'rgba(8,26,40,0.50)', bandBot: 'rgba(6,18,28,0.40)',
    bandEdge: 'rgba(150,212,222,0.42)', bandGlow: 'rgba(90,200,210,0.10)',
    wingFill: 'rgba(10,22,32,0.55)', wingLine: 'rgba(150,186,202,0.50)',
    discOuter: 'rgba(4,30,52,0.92)', discTop: 'rgba(118,134,142,0.96)', discMid: 'rgba(45,73,88,0.96)', discBot: 'rgba(32,48,63,0.96)',
    ringTop: 'rgba(160,184,200,0.95)', ringMid: 'rgba(125,146,166,0.88)', ringBot: 'rgba(60,85,100,0.35)', ringLight: 'rgba(132,151,163,0.85)',
    white: '#F4F7F8', label: '#E4F0F3', dim: '#93A9BB', discDot: 'rgba(150,178,192,0.13)',
    boostFill: '#475A6D', boostLine: '#5B7183', boostText: '#9CADBC', hatch: 'rgba(120,146,170,0.85)',
    boostOn: '#33ADF7', boostOnLine: '#A6DDFF', boostOnText: '#062238', hatchOn: 'rgba(127,214,255,0.95)',
    // OVERTAKE lit: bright green outline and letters on a dark-green fill (docs/research 3.3)
    otOnTop: '#1A7438', otOnBot: '#12602C', otOnLine: '#52C878', otOnText: '#58C070', otOnGlow: 'rgba(80,200,120,0.30)',
    otOff: 'rgba(92,101,108,0.92)', otOffLine: 'rgba(130,140,148,0.8)', otOffText: '#283035',
    capOff: 'rgba(30,84,124,0.95)', capOffLine: '#3A88B8', capOffText: '#5DB0D6',
    capOnTop: '#3A9AEE', capOnBot: '#1784CE', capOnLine: '#44B0E4', capOnText: '#58A2F0',
    // unlit slats dark grey; lit brake red (207,84,101), lit throttle teal-green (48,186,158) as measured on
    // compressed footage, lifted a little toward the source colours (docs/research 3.6)
    stripePanel: 'rgba(18,30,40,0.80)', stripeOff: 'rgba(66,78,88,0.92)',
    throttle: '#18D6A0', throttleTop: '#26DCA9', brake: '#E2566A', brakeTop: '#EC6A7C',
    battLine: '#4FB8E1', battFillTop: '#1489D6', battFillBot: '#0F7DCB', battIn: '#235079', battCharge: '#0E4877', bolt: '#4FE0F5',
    aeroOn: '#45E4D4', aeroBar: '#C9D3D8', gearDim: 'rgba(205,216,222,0.86)', track: 'rgba(160,182,195,0.55)', gearLbl: '#C9D5DD',
    gRing: 'rgba(206,150,182,0.75)', gTeal: '#3FD3CC', gWhite: '#F5F7F8', gRed: '#F0444E',
  };

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
  const BAND_TOP = [[-215, 65], [-182, 44], [-160, 29], [-138, 15], [-117, 4], [-97, -4], [-77, -10.5], [-58, -17], [-36, -24], [0, -27], [36, -24], [58, -17], [76, -11.5], [98, -6], [122, 3], [146, 15], [168, 29], [190, 45], [220, 68]];
  const BAND_BOT = [[220, 112], [188, 90], [166, 75], [144, 62], [122, 51], [100, 40], [80, 30], [64, 24.5], [36, 28], [0, 29], [-36, 28], [-64, 25.5], [-80, 32], [-100, 42], [-122, 54], [-144, 66], [-166, 79], [-186, 91], [-215, 108]];
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
  function drawSlat(g, left, i, col, glow) {
    const s = G.stripes, xm = (stripeXin(i) + stripeXout(i)) / 2, ym = stripeLine(i, xm);
    if (glow) { poly(g, slatPts(i, left, 0.5)); g.fillStyle = col; g.globalAlpha = 0.22; g.fill(); g.globalAlpha = 1; }
    // a slight top-to-bottom shade, like the broadcast's lit slats
    const gr = g.createLinearGradient(0, ym - s.th / 2, 0, ym + s.th / 2);
    gr.addColorStop(0, col); gr.addColorStop(1, shade(col, glow ? 0.86 : 0.92));
    poly(g, slatPts(i, left)); g.fillStyle = gr; g.fill(); g.strokeStyle = gr; g.lineWidth = 0.3; g.stroke();
  }
  // darken a #rrggbb or rgba() colour by factor k (alpha kept)
  function shade(col, k) {
    let r, gg, b, a = 1;
    if (col[0] === '#') { r = parseInt(col.slice(1, 3), 16); gg = parseInt(col.slice(3, 5), 16); b = parseInt(col.slice(5, 7), 16); }
    else { [r, gg, b, a = 1] = col.match(/[\d.]+/g).map(Number); }
    return `rgba(${Math.round(r * k)},${Math.round(gg * k)},${Math.round(b * k)},${a})`;
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

  function drawDisc(g) {
    const d = G.disc;
    const gr = g.createLinearGradient(0, -d.inner, 0, d.inner); gr.addColorStop(0, P.discTop); gr.addColorStop(0.3, P.discMid); gr.addColorStop(1, P.discBot);
    g.beginPath(); g.arc(0, 0, d.inner, 0, 7); g.fillStyle = gr; g.fill();
    // fine dot texture over the face (broadcast: "dark translucent disc with a dot texture", docs/research 3.1)
    g.save(); g.beginPath(); g.arc(0, 0, d.inner - 0.4, 0, 7); g.clip(); g.fillStyle = P.discDot;
    const dy = d.dotY || d.dot;
    for (let y = -d.inner; y <= d.inner; y += dy) for (let x = -d.inner; x <= d.inner; x += d.dot) { g.beginPath(); g.arc(x + (d.stagger !== false && (Math.round(y / dy) & 1) ? d.dot / 2 : 0), y, d.dotR, 0, 7); g.fill(); }
    g.restore();
    const rg = g.createLinearGradient(0, -d.rim, 0, d.rim); rg.addColorStop(0, P.ringTop); rg.addColorStop(0.55, P.ringMid); rg.addColorStop(0.95, P.ringBot);
    g.beginPath(); g.arc(0, 0, d.rim, 0, 7); g.strokeStyle = 'rgba(150,205,220,0.10)'; g.lineWidth = 2.4; g.stroke();
    g.strokeStyle = rg; g.lineWidth = d.ring; g.stroke();
    if (d.light) { g.beginPath(); g.arc(0, 0, d.light, 0, 7); g.strokeStyle = P.ringLight; g.lineWidth = d.lightW; g.stroke(); }
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
  const speedText = (g, kmh) => text(g, String(Math.round(kmh)), 0, G.speed.y, G.speed.fs, P.white, { tr: G.speed.tr, sx: G.speed.sx, w: 780 });
  const mphText = (g, kmh) => text(g, String(Math.round(kmh * 0.621371)), 0, G.mph.y, G.mph.fs, P.white, { tr: G.mph.tr, sx: G.mph.sx, w: 780 });
  function drawDial(g, st) {
    drawDisc(g);
    if (st.mode === 'spa') return drawGDial(g, st);
    text(g, 'KM/H', 0, G.kmh.y, G.kmh.fs, P.label, { tr: G.kmh.tr });
    speedText(g, st.kmh);
    drawBoost(g, st.boost);
    drawOT(g, st.ot);
    mphText(g, st.kmh);
    text(g, 'MPH', 0, G.mphLbl.y, G.mphLbl.fs, P.label, { tr: G.mphLbl.tr });
    drawBattery(g, st.soc, st.recharge > 0.3);
  }

  function drawGStatic(g) {
    [32.2, 27.6, 23.0, 17.8].forEach(r => { g.beginPath(); g.arc(0, 0, r, 0, 7); g.strokeStyle = P.gRing; g.lineWidth = 0.4; g.stroke(); });
    text(g, 'G-FORCE', 0, 5.2, 2.7, P.label, { tr: 0.3 });
  }
  const gText = (g, m) => text(g, m.toFixed(1), 0, -1.6, 9.6, P.white, { tr: 0.4, sx: 1.05, w: 780 });
  function drawGDial(g, st) {
    // Spa-style G meter: four mauve rings and a three-layer wedge pointing along the G vector
    [32.2, 27.6, 23.0, 17.8].forEach(r => { g.beginPath(); g.arc(0, 0, r, 0, 7); g.strokeStyle = P.gRing; g.lineWidth = 0.4; g.stroke(); });
    const phi = st.gDir * D, m = st.g;
    const layer = (r0, r1, half, col, show) => { if (!show) return; g.beginPath(); g.arc(0, 0, r1, phi - half * D, phi + half * D); g.arc(0, 0, r0, phi + half * D, phi - half * D, true); g.closePath(); g.fillStyle = col; g.fill(); };
    layer(12.5, 15.8, 70, P.gTeal, m > 0.15);
    layer(18.4, 23.7, 19, P.gWhite, m > 1.4);
    layer(24.3, 30.3, 18, P.gRed, m > 2.4);
    gText(g, m);
    text(g, 'G-FORCE', 0, 5.2, 2.7, P.label, { tr: 0.3 });
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
    if (st.turn) { drawTurnArrow(g, st.turnDir === 'R'); drawTurnNumber(g, st.turn); }
    drawTurnLabel(g);
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
  function drawAeroBars(g, straight, col) {
    const a = G.aero;
    g.fillStyle = col;
    const bar = (cx, cy, len, ang, th = a.barTh) => { g.save(); g.translate(cx, cy); g.rotate(ang * D); rr(g, -len / 2, -th / 2, len, th, th / 2); g.fill(); g.restore(); };
    if (straight) { // "=" (sheared with the wing): two flat bars, the lower one set back toward the centre
      bar(a.barX + a.barDx / 2, a.barY + a.barDy / 2, a.barLen, a.barAng);
      bar(a.barX - a.barDx / 2, a.barY - a.barDy / 2, a.barLen, a.barAng);
    } else {         // "//": two steep slashes
      bar(a.barX - a.slHx, a.barY - a.slHy, a.slLen, a.slAng, a.slTh); bar(a.barX + a.slHx, a.barY + a.slHy, a.slLen, a.slAng, a.slTh);
    }
  }
  function drawAero(g, st) {
    // white in both modes on the broadcast (docs/research 3.9); aeroTint only reproduces the fan-made screenshot
    const straight = st.aero, tint = straight && st.aeroTint && st.theme === 'screenshot';
    drawAeroLabel(g, tint ? P.aeroOn : P.white);
    drawAeroBars(g, straight, tint ? P.aeroOn : P.aeroBar);
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
    text(g, 'N12345678'[i], x, y, on ? q.fsOn : q.fs, on ? P.white : P.gearDim, { rot: Math.atan2(ty, tx) / D, lean: q.lean, w: on ? 780 : 700 });
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
    g.beginPath(); g.arc(0, 0, G.disc.r, 0, 7); g.fillStyle = P.discOuter; g.fill();   // navy collar around the dial
    if (st.mode !== 'spa') { drawCapsule(g, true, st.recharge, 'RECHARGE'); drawCapsule(g, false, st.deploy, 'DEPLOY'); }
    else { [true, false].forEach(l => { poly(g, capsulePts(l)); g.strokeStyle = 'rgba(140,175,195,0.22)'; g.lineWidth = 0.45; g.stroke(); }); }
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
    drawAero(g, st);
    drawGears(g, st);
    g.restore();
  }

  // Static / moving pieces for the addon's texture export (export.html).
  const internals = {
    D, FONT, CAP, text, frame, rr, poly, lerp, bez, bezTan, lanePoint, laneAngle, laneText, capsulePts, stripePanelPts,
    capsXin, capsXout, stripeXin, stripeXout, stripeLine, slatPts, slatColour, stripeY, stripePitch, drawSlat, centreFrame, drawCentreLabels, drawBand, drawWing, drawStripes, drawCapsule, drawDisc, drawBoost, drawOT, speedText,
    mphText, battInterior, battFill, battOutline, battBolt, drawGStatic, gText, turnArrow, drawTurnArrow, drawTurnNumber,
    drawTurnLabel, drawRails, drawAeroLabel, drawAeroBars, gearPt, drawGearTrack, drawRpmBar, drawGearMarker,
    drawGearDigit, drawGearLabels, RPM_T0, RPM_T1,
  };
  return { draw, G, P, internals, parts: { drawCentre, drawNames, drawTurn, drawAero, drawGears, drawDial, drawBand, drawWing } };
})();
