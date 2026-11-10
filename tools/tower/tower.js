/* tower.js - F1 TV 2026 timing tower: reference drawing for Phase 2 (design only; nothing here runs in the game).

   One parameterised drawing in HUD units (640 x 360 frame, 1 unit = 3 px at 1080p), like tools/halo.js.
   Every size and colour comes from docs/timing-tower/measurements.md; the master unit is the row pitch
   p = 12.981 HUD (F1 TV 1080p frame: 38.942 px / 3). Origin (0, 0) = top-left corner of the tower panel.

   Game-texture slots are drawn as labelled placeholders, never as artwork: F1 logo, FIA badge, team badges
   (no F1 or team artwork is shipped; the game supplies these textures).

   Font: Saira (SIL OFL, saira.ttf + saira-OFL.txt next to this file) stands in for the broadcast "Formula1"
   family. Weights and horizontal scales were fitted to the measured text widths (fit_font.py -> fontfit.json).

   API
     TOWER.draw(ctx, state, opt) -> layout     draw a tower at the current transform (HUD units)
     TOWER.drawBanner(ctx, banner, opt) -> {w, h}
     TOWER.window(count, n, playerPos, mode)   -> {start, rows}   row window (compact / top / full)
     TOWER.size(state, opt)                    -> {w, h}          bounding box of draw() (opt: names mode widens it)
     TOWER.gameWidth(text)                     -> HUD units       ink width of a name in the game's code style
     TOWER.G, TOWER.P                          geometry (HUD units) and palette

   state = {
     session: 'race' | 'quali' | 'practice',
     header: false | { lap, laps } | { label: 'Q2', clock: '1:46' },     (race | timed sessions)
     status: null | 'yellow' | 'vsc' | 'sc' | 'red' | 'chequered',  statusText: second line (yellow / red)
     rows: [{ pos, code, name, team, col, logo, gap, tyre, pit, pen: 'inv'|'pen', arrow: 'up'|'down', out, me, ko }],
           name: full surname ('HAMILTON'), used in names mode 'surname' (falls back to the code)
           col: team colour for the bar ('#DC0000'); null / absent = no colour, no bar
           logo: false = this car has no logo (empty slot)
           gap: '+0.733' | '1:26.745' | 'Interval' | 'Out Lap' | ... | null (unavailable)
           tyre: 'S' | 'M' | 'H' | 'I' | 'W' | '' (none) | null (unavailable)
     window: { mode: 'full' | 'compact' | 'top', n, player }   (player = position of the player's car)
   }
   opt = { panelAlpha, slots (draw slot labels, default true), highlight (player highlight, default true),
           names: 'code' (default) | 'surname',   bar: team-colour bar (default false),
           logos: the Team logos setting (default true),   guides: draw the name and gap boxes (default false) }
   With the defaults (codes, no bar, logos on) the drawing is the approved one, unchanged.
*/
(function (root) {
  'use strict';

  const p = 12.981;                       // row pitch, HUD units
  const FONT = (root && root.TOWER_FONT) || 'TowerSaira';
  const CAP_EM = 0.69;                    // Saira cap height / em (fontfit.json)
  const K = 10;                           // text is set at K x size and scaled down (avoids tiny-font metrics)

  const G = {
    p,
    w: 6.314 * p,                         // panel width (5 refs: 6.295 - 6.317 p)
    strip: 0.928 * p,                     // position strip width
    // header, y from the panel top
    sep: 2.313 * p,                       // separator line (panel top -> separator: 2.313 p)
    sepH: 2 / 3,                          // 2 px at 1080p
    band: 1.122 * p,                      // session band: separator -> first row cell top
    logo: { x: 1.485 * p, y: (2.313 - 1.885) * p, w: 3.30 * p, h: 0.837 * p },   // F1 logo slot
    fia: { x: 1.50 * p, y: (2.313 - 0.89) * p, w: 3.30 * p, h: 0.48 * p },       // FIA badge line slot
    sessBase: 0.78 * p,                   // session text baseline below the separator
    sess: {                               // session line pieces: cap (p), weight, sx, tabular digit cell (caps)
      lapWord: { cap: 0.393, wt: 300, sx: 1.12 },
      lapNum: { cap: 0.495, wt: 700, dig: 0.98 },
      slash: { cap: 0.424, wt: 300, sx: 0.70 },
      laps: { cap: 0.375, wt: 300, dig: 0.89 },
      label: { cap: 0.44, wt: 400, sx: 1.02 },        // 'Q2', 'P3'
      clock: { cap: 0.445, wt: 700, dig: 0.89 },      // '1:46', '7:42'
      gap1: 0.22, gap2: 0.22, gap3: 0.146, gapT: 0.235,
    },
    // rows, y from the row cell top
    mid: 0.4965 * p,                      // text middle (P1 box centre + 0.009 p)
    p1: { x: 0.010 * p, y: 0.020 * p, w: 0.906 * p, h: 0.935 * p },
    posX: 0.461 * p, posCap: 0.369 * p,
    arrow: { x: 0.446 * p, w: 0.44 * p, h: 0.33 * p, dyUp: 0.017 * p, dyDown: -0.02 * p },
    badgeX: 1.382 * p, badgeW: 0.843 * p, badgeH: 0.652 * p,     // team badge slot (max logo extent)
    codeX: 1.986 * p, codeCap: 0.389 * p, codeWt: 650, codeSx: 1.142,
    num: {
      race: { r: 5.446 * p, cap: 0.428 * p },
      timed: { r: 5.545 * p, cap: 0.383 * p },
      dig: 0.785, punct: 0.356, sx: 0.95, ink: 0.70,      // tabular cells in caps
    },
    labelCap: { race: 0.39 * p, timed: 0.383 * p }, labelSx: 1.0,         // Interval 0.99, No Time 0.98, Out Lap 1.03
    tyreX: 5.922 * p, tyreCap: 0.352 * p,
    side: { w: 0.481 * p, h: 0.655 * p, dy: -0.0125 * p, cap: 0.36 * p, gap: 0.06 * p },
    stripSepH: 0.5,                       // strip separators: 1-2 px at 1080p
    hatch: { period: 0.072 * p, angle: 49.5 },              // knockout zone, '/' stripes
    status: {
      slots: { yellow: 2, red: 2, sc: 2, vsc: 2, chequered: 1 },
      barCap: 0.497, barWt: 800, barSx: 1.165,              // YELLOW FLAG
      hazCap: 0.429, hazWt: 300, hazSx: 1.0,                // TRACK HAZARD
      redCap: 0.50, redWt: 700, redSx: 1.13,                // RED FLAG
      stopCap: 0.455, stopWt: 400, stopSx: 0.95,            // SESSION STOPPED
      sc: { fx0: 0.265, fx1: 2.355, fy0: 0.336, fy1: 1.756, tx: 2.597, l1: [0.474, 0.989], l2: [1.137, 1.652], wt: 800, sx: 1.2 },
    },
    banner: {                             // FIA RACE CONTROL banner, measured in banner px, k = HUD per px
      hPx: 62.4, k: 1.693 * p / 62.4,     // height 1.693 p ASSUMES the banner crop has the c5/q2 scale
      fia: [25.5, 88.5, 12.52, 55.69], t1x: 123.5, base: 41.3, cap1: 16.45, cap2: 15.03, padR: 19.5,
      gapWord1: 6, gapPhrase: 12, gapWord2: 8, wt1: 700, sx1: 1.045, wt2: 300, sx2: 1.06,
    },
  };

  // Names mode and team-colour bar (design picks 2026-11-09: "Setting, codes default" and "Bar next to the logo").
  // Sizes and evidence: docs/timing-tower/names-and-colour-bar.md. Nothing above changes with them.
  G.names = {
    codeBox: 1.47 * p,                    // the game build's code box (tower_native.py CODE_BOX)
    surnameBox: 4.35 * p,                 // fits HULKENBERG, the widest 2025/2026 surname: 4.24 p in the game's code style
    clear: 0.20 * p,                      // name box -> gap box (tower_native.py GAP_CLEAR)
  };
  // The bar: the replay board's (3.0 x 24.0 px at its 38.39 px row pitch), flush against the position strip's right
  // edge, centred on the text middle. With the bar on, the logo is centred between the bar and the name column.
  G.bar = { x: G.strip, w: 0.08 * p, h: 0.625 * p };
  G.barBadgeX = (G.strip + G.bar.w + G.codeX) / 2;

  // The game's code style (OSD_24_bold) as the game draws it today, measured on in-game tower screenshots
  // (2026-11-09, 39 codes; J K Y Z from his replay-board screenshot of full surnames): cap 0.423 p, and per letter
  // [ink width, left bearing, right bearing] in caps. Word ink width = cap x (inks + the bearings between letters).
  // Surnames are drawn at this width, so the renders show the game's fit, not Saira's.
  const GAME_CODE = {
    cap: 0.423 * p,
    other: [0.86, 0.06, 0.06],            // a letter not measured (F Q X): a typical capital
    space: 0.30,                          // word space in caps (not measured)
    L: {
      A: [1.057, 0.015, 0.033], B: [0.834, 0.082, 0.063], C: [0.782, 0.044, 0.052], D: [0.914, 0.096, 0.060],
      E: [0.761, 0.080, 0.095], G: [0.927, 0.060, 0.081], H: [0.927, 0.060, 0.097], I: [0.218, 0.102, 0.102],
      J: [0.629, 0.043, 0.094], K: [0.840, 0.091, 0.049], L: [0.725, 0.082, 0.048], M: [1.189, 0.085, 0.060],
      N: [1.055, 0.083, 0.099], O: [0.981, 0.058, 0.077], P: [0.827, 0.060, 0.052], R: [0.861, 0.086, 0.044],
      S: [0.808, 0.053, 0.054], T: [0.940, 0.027, 0.031], U: [0.899, 0.085, 0.101], V: [0.954, 0.060, 0.042],
      W: [1.439, 0.034, 0.060], Y: [0.971, 0.015, 0.060], Z: [0.785, 0.043, 0.060],
    },
  };
  // ink width of s in the game's code style, HUD units (accents ignored: Ü is as wide as U)
  function gameWidth(s) {
    const t = s.normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase();
    let w = 0, prev = null;
    for (const ch of t) {
      if (ch === ' ') { w += GAME_CODE.space; prev = null; continue; }
      const m = GAME_CODE.L[ch] || GAME_CODE.other;
      w += m[0] + (prev ? prev[2] + m[1] : 0);
      prev = m;
    }
    return w * GAME_CODE.cap;
  }

  const P = {
    panel: [20, 22, 30], panelAlpha: 0.81, // own colour + opacity of the row panel (INT fit, r 0.96-0.98)
    strip: '#13141D',                     // position strip, opaque
    stripSep: 'rgba(255,255,255,0.075)',  // luma 38 on 20
    red: '#F12116',                       // P1 box (INT); also used for the red flag bar
    code: '#F5F5F9', num: '#E9EAEF', pos: '#EAEBF0', label: '#E9EAEF',
    tyre: { S: '#CD535A', M: '#DAC668', H: '#EDEDED', I: '#6AAC64', W: '#4A80A4' },   // H inferred (no reference)
    pit: ['#EDEDED', '#121315'], pen: ['#B9221E', '#FFFFFF'], inv: ['#BDC936', '#060800'],
    up: '#26DD09', down: '#D51A2E',
    hdrTop: 'rgba(54,56,66,0.82)', hdrMid: 'rgba(44,45,56,0.92)', hdrSep: '#1A1D28',
    separator: '#42414F', band: '#171B26', sess: '#EEEFF3',
    yellow: '#CFC515', yellowText: '#000000', hazard: '#CFC515', darkBand: '#131119',
    sc: '#D2C215', redFlagText: '#FFFFFF', stopped: '#E0282E',
    banner: ['#142237', '#0A1931', '#1F2738'], bannerText: '#F2F4F8',
    hatch: ['#4A242C', '#1F0001'],
    na: 'rgba(233,234,239,0.38)',         // unavailable marker
    me: 'rgba(255,255,255,0.10)',         // player highlight
    slot: 'rgba(255,255,255,0.42)', slotText: 'rgba(255,255,255,0.62)',
  };

  // ---------------------------------------------------------------- text

  function setFont(ctx, wt, cap) { ctx.font = `${wt} ${(cap / CAP_EM * K).toFixed(2)}px ${FONT}`; }

  function inkOf(ctx, s) {
    const m = ctx.measureText(s);
    return { l: m.actualBoundingBoxLeft / K, r: m.actualBoundingBoxRight / K, adv: m.width / K };
  }

  // draw s with its ink box aligned at x: align 'left' (ink left), 'right' (ink right), 'center' (ink centre)
  function text(ctx, s, x, base, cap, o) {
    o = o || {};
    const sx = o.sx || 1;
    ctx.save();
    setFont(ctx, o.wt || 400, cap);
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    const m = inkOf(ctx, s), w = (m.l + m.r) * sx;
    const x0 = o.align === 'right' ? x - w : o.align === 'center' ? x - w / 2 : x;
    ctx.translate(x0, base); ctx.scale(sx / K, 1 / K);
    ctx.fillStyle = o.color || '#fff';
    if (o.alpha !== undefined) ctx.globalAlpha *= o.alpha;
    ctx.fillText(s, m.l * K, 0);
    ctx.restore();
    return w;
  }

  function textWidth(ctx, s, cap, wt, sx) {
    ctx.save(); setFont(ctx, wt, cap); const m = inkOf(ctx, s); ctx.restore();
    return (m.l + m.r) * (sx || 1);
  }

  // tabular figures: digits and '+' in cells of dig caps, '.' ':' in punct caps; returns ink width
  function cells(s, cap, dig, punct) {
    return [...s].map(ch => (/[0-9+\-−]/.test(ch) ? dig : /[.:]/.test(ch) ? punct : 0.6) * cap);
  }
  function tabular(ctx, s, xr, base, cap, o) {
    o = o || {};
    const dig = o.dig || G.num.dig, punct = o.punct || G.num.punct, sx = o.sx || G.num.sx;
    const cw = cells(s, cap, dig, punct);
    let x = xr + 0.5 * (dig - G.num.ink) * cap;        // right edge of the last cell
    for (let i = s.length - 1; i >= 0; i--) {
      text(ctx, s[i], x - cw[i] / 2, base, cap, { wt: o.wt || 400, sx, align: 'center', color: o.color, alpha: o.alpha });
      x -= cw[i];
    }
    return xr - x - 0.5 * (dig - G.num.ink) * cap;
  }
  function tabularWidth(s, cap, dig, punct) {
    return cells(s, cap, dig, punct || G.num.punct).reduce((a, b) => a + b, 0) - (dig - G.num.ink) * cap;
  }

  // ---------------------------------------------------------------- small parts

  function rect(ctx, x, y, w, h, c) { ctx.fillStyle = c; ctx.fillRect(x, y, w, h); }

  function slot(ctx, x, y, w, h, label, cap, o) {
    o = o || {};
    if (o.slots === false) return;
    ctx.save();
    ctx.strokeStyle = P.slot; ctx.lineWidth = 0.35; ctx.setLineDash([1.2, 0.9]);
    ctx.strokeRect(x + 0.2, y + 0.2, w - 0.4, h - 0.4);
    ctx.restore();
    if (label) text(ctx, label, x + w / 2, y + h / 2 + cap / 2, cap, { wt: 600, align: 'center', color: P.slotText, alpha: o.alpha });
  }

  function triangle(ctx, cx, cy, w, h, up, color) {
    ctx.save();
    ctx.beginPath();
    if (up) { ctx.moveTo(cx, cy - h / 2); ctx.lineTo(cx + w / 2, cy + h / 2); ctx.lineTo(cx - w / 2, cy + h / 2); }
    else { ctx.moveTo(cx, cy + h / 2); ctx.lineTo(cx + w / 2, cy - h / 2); ctx.lineTo(cx - w / 2, cy - h / 2); }
    ctx.closePath();
    ctx.fillStyle = color; ctx.fill();
    ctx.strokeStyle = color; ctx.lineJoin = 'round'; ctx.lineWidth = 0.05 * w; ctx.stroke();
    ctx.restore();
  }

  function hatch(ctx, x, y, w, h) {
    ctx.save();
    ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
    rect(ctx, x, y, w, h, P.hatch[1]);
    ctx.translate(x, y + h);
    ctx.rotate(-G.hatch.angle * Math.PI / 180);
    ctx.fillStyle = P.hatch[0];
    const per = G.hatch.period, n = Math.ceil((w + h) / per) + 2;
    for (let i = -n; i <= n; i++) ctx.fillRect(-2 * (w + h), i * per, 4 * (w + h), per / 2);
    ctx.restore();
  }

  function unavailable(ctx, xc, ymid, len) {
    rect(ctx, xc - len / 2, ymid - 0.03 * p, len, 0.06 * p, P.na);
  }

  // position number, centred; '0' gets the slash the broadcast (and the game's OSD font) use
  function position(ctx, s, cx, base, cap, color, alpha) {
    const w = text(ctx, s, cx, base, cap, { wt: 400, align: 'center', color, alpha });
    if (s.includes('0')) {
      // the slash: through the last zero, lower-left to upper-right
      ctx.save();
      setFont(ctx, 400, cap);
      const z = inkOf(ctx, '0');
      const zw = (z.l + z.r), zc = cx + w / 2 - zw / 2;
      ctx.strokeStyle = color; ctx.globalAlpha *= (alpha === undefined ? 1 : alpha);
      ctx.lineWidth = 0.13 * cap; ctx.lineCap = 'butt';
      ctx.beginPath(); ctx.moveTo(zc - 0.24 * zw, base - 0.14 * cap); ctx.lineTo(zc + 0.24 * zw, base - 0.86 * cap); ctx.stroke();
      ctx.restore();
    }
  }

  // ---------------------------------------------------------------- layout

  function window_(count, n, player, mode) {
    if (mode === 'full' || !n || n >= count) return { start: 0, rows: count };
    if (mode === 'top') return { start: 0, rows: Math.min(n, count) };
    const pos0 = Math.max(0, (player || 1) - 1);
    const start = Math.max(0, Math.min(pos0 - Math.floor(n / 2), count - n));   // = the game's 5-pill rule for n = 5
    return { start, rows: n };
  }

  function visibleRows(st) {
    const all = st.rows || [];
    const wdw = st.window || { mode: 'full' };
    const r = window_(all.length, wdw.n, wdw.player, wdw.mode);
    return all.slice(r.start, r.start + r.rows);
  }

  // per-draw geometry from the display options: names mode and bar. Surname mode widens the name column from the
  // build's code box to the surname box; everything right of it (gap, tyre, panel edge, side boxes) moves by dW.
  function geom(opt) {
    opt = opt || {};
    const sur = opt.names === 'surname', bar = !!opt.bar;
    const dW = sur ? G.names.surnameBox - G.names.codeBox : 0;
    return {
      sur, bar, dW, logos: opt.logos !== false,
      w: G.w + dW,
      nameBox: sur ? G.names.surnameBox : G.names.codeBox,
      badgeX: bar ? G.barBadgeX : G.badgeX,
      num: { race: Object.assign({}, G.num.race, { r: G.num.race.r + dW }), timed: Object.assign({}, G.num.timed, { r: G.num.timed.r + dW }) },
      tyreX: G.tyreX + dW,
    };
  }

  function layout(st, opt) {
    const g = geom(opt);
    const L = { w: g.w, g };
    L.hdr = !!st.header;
    L.rowsTop = L.hdr ? G.sep + G.band : 0;
    L.slots = (st.status && G.status.slots[st.status]) || 0;
    if (!L.hdr) L.slots = 0;
    L.firstRow = L.rowsTop + L.slots * p;
    L.rows = visibleRows(st);
    L.h = L.firstRow + L.rows.length * p;
    L.mids = L.rows.map((_, i) => L.firstRow + i * p + G.mid);
    return L;
  }

  // ---------------------------------------------------------------- header

  function drawHeader(ctx, st, L, opt) {
    const W = L.w, dx = L.g.dW / 2;       // a wider panel (surname mode) keeps the logo and badge centred
    // background: dark gradient, lighter and slightly translucent at the top (measured top -> separator)
    const g = ctx.createLinearGradient(0, 0, 0, G.sep);
    g.addColorStop(0, P.hdrTop); g.addColorStop(0.5, P.hdrMid); g.addColorStop(1, P.hdrSep);
    rect(ctx, 0, 0, W, G.sep, g);
    slot(ctx, G.logo.x + dx, G.logo.y, G.logo.w, G.logo.h, 'F1 LOGO · GAME TEXTURE', 0.15 * p, opt);
    slot(ctx, G.fia.x + dx, G.fia.y, G.fia.w, G.fia.h, 'FIA BADGE · GAME TEXTURE', 0.13 * p, opt);
    rect(ctx, 0, G.sep, W, G.band, P.band);
    rect(ctx, 0, G.sep - G.sepH / 2, W, G.sepH, P.separator);
    // session line, centred
    const h = st.header, S = G.sess, base = G.sep + G.sessBase;
    const parts = [];
    if (h.laps !== undefined) {
      parts.push({ s: 'LAP', ...S.lapWord }, { gap: S.gap1 });
      parts.push(h.lap === null ? { s: '–', ...S.lapWord, na: true } : { s: String(h.lap), ...S.lapNum, tab: true }, { gap: S.gap2 });
      parts.push({ s: '/', ...S.slash }, { gap: S.gap3 });
      parts.push(h.laps === null ? { s: '–', ...S.lapWord, na: true } : { s: String(h.laps), ...S.laps, tab: true });
    } else {
      parts.push({ s: h.label, ...S.label }, { gap: S.gapT });
      parts.push(h.clock === null ? { s: '–:––', ...S.label, na: true } : { s: h.clock, ...S.clock, tab: true });
    }
    let total = 0;
    for (const q of parts) {
      if (q.gap !== undefined) { q.w = q.gap * p; } else {
        q.capH = q.cap * p;
        q.w = q.tab ? tabularWidth(q.s, q.capH, q.dig) : textWidth(ctx, q.s, q.capH, q.wt, q.sx);
      }
      total += q.w;
    }
    let x = W / 2 - total / 2;
    for (const q of parts) {
      if (q.gap === undefined) {
        const color = q.na ? P.na : P.sess;
        if (q.tab) tabular(ctx, q.s, x + q.w, base, q.capH, { dig: q.dig, wt: q.wt, sx: 1, color });
        else text(ctx, q.s, x, base, q.capH, { wt: q.wt, sx: q.sx, color });
      }
      x += q.w;
    }
  }

  function drawStatus(ctx, st, L, opt) {
    const W = L.w, y = L.rowsTop, S = G.status, dx = L.g.dW / 2;
    const line2 = (txt, cap, wt, sx, color) => {
      rect(ctx, 0, y + p, W, p, P.darkBand);
      text(ctx, txt, W / 2, y + p + G.mid + cap * p / 2, cap * p, { wt, sx, align: 'center', color });
    };
    if (st.status === 'yellow') {
      rect(ctx, 0, y, W, 1.005 * p, P.yellow);
      text(ctx, 'YELLOW FLAG', W / 2, y + G.mid + S.barCap * p / 2, S.barCap * p, { wt: S.barWt, sx: S.barSx, align: 'center', color: P.yellowText });
      line2(st.statusText || 'TRACK HAZARD', S.hazCap, S.hazWt, S.hazSx, P.hazard);
    } else if (st.status === 'red') {
      rect(ctx, 0, y, W, 1.032 * p, P.red);
      text(ctx, 'RED FLAG', W / 2, y + G.mid + S.redCap * p / 2, S.redCap * p, { wt: S.redWt, sx: S.redSx, align: 'center', color: P.redFlagText });
      line2(st.statusText || 'SESSION STOPPED', S.stopCap, S.stopWt, S.stopSx, P.stopped);
    } else if (st.status === 'sc' || st.status === 'vsc') {
      const c = S.sc;
      rect(ctx, 0, y, W, 1.998 * p, P.sc);
      slot(ctx, c.fx0 * p + dx, y + c.fy0 * p, (c.fx1 - c.fx0) * p, (c.fy1 - c.fy0) * p, 'FIA', 0.3 * p, Object.assign({}, opt, { alpha: 0.9 }));
      if (st.status === 'sc') {
        const cap = (c.l1[1] - c.l1[0]) * p;
        text(ctx, 'SAFETY', c.tx * p + dx, y + c.l1[1] * p, cap, { wt: c.wt, sx: c.sx, color: '#000' });
        text(ctx, 'CAR', c.tx * p + dx, y + c.l2[1] * p, cap, { wt: c.wt, sx: c.sx, color: '#000' });
      } else {
        // VSC: no reference - inferred from the SC box (three lines in the same text block)
        const cap = 0.34 * p, x = c.tx * p + dx;
        text(ctx, 'VIRTUAL', x, y + 0.62 * p, cap, { wt: c.wt, sx: 1.05, color: '#000' });
        text(ctx, 'SAFETY', x, y + 1.15 * p, cap, { wt: c.wt, sx: 1.05, color: '#000' });
        text(ctx, 'CAR', x, y + 1.68 * p, cap, { wt: c.wt, sx: 1.05, color: '#000' });
      }
    } else if (st.status === 'chequered') {
      // no reference - inferred: chequer band behind a dark label box
      const sq = 0.25 * p;
      for (let i = 0; i * sq < W; i++) for (let j = 0; j < 4; j++) rect(ctx, i * sq, y + j * sq, sq, sq, (i + j) % 2 ? '#111' : '#EEE');
      const tw = textWidth(ctx, 'CHEQUERED FLAG', 0.40 * p, 700, 1.0) + 0.5 * p;
      rect(ctx, W / 2 - tw / 2, y + 0.12 * p, tw, 0.76 * p, P.darkBand);
      text(ctx, 'CHEQUERED FLAG', W / 2, y + G.mid + 0.2 * p, 0.40 * p, { wt: 700, align: 'center', color: P.sess });
    }
  }

  // ---------------------------------------------------------------- rows

  // a full surname in the code's place (names mode 'surname'), drawn at the game's width (gameWidth) so the renders
  // show the game's fit. Wider than the box: squeezed to the box, as the game's clampwidth would do (never seen
  // working in game); a row with run: true draws it at full width instead (what happens if clampwidth does nothing).
  function surname(ctx, s, x, base, box, alpha, run) {
    s = s.toUpperCase();
    const want = gameWidth(s), w = run ? want : Math.min(want, box);
    const w1 = textWidth(ctx, s, G.codeCap, G.codeWt, 1);
    text(ctx, s, x, base, G.codeCap, { wt: G.codeWt, sx: w / w1, color: P.code, alpha });
    return { w, want };
  }

  // design check (opt.guides): the name box (cyan), the clearance before the gap box (red), the gap box (magenta);
  // a name wider than its box gets a red mark over the part that doesn't fit
  function guides(ctx, g, num, mid, want) {
    const x0 = G.codeX, x1 = x0 + g.nameBox, x2 = x1 + G.names.clear, h = 0.62 * p, top = mid - h / 2;
    ctx.save();
    ctx.lineWidth = 0.3; ctx.setLineDash([0.9, 0.6]);
    ctx.strokeStyle = 'rgba(80,220,255,0.95)'; ctx.strokeRect(x0, top, x1 - x0, h);
    ctx.fillStyle = 'rgba(255,70,70,0.30)'; ctx.fillRect(x1, top, x2 - x1, h);
    ctx.strokeStyle = 'rgba(255,90,220,0.95)'; ctx.strokeRect(x2, top, num.r - x2, h);
    if (want > g.nameBox) { ctx.setLineDash([]); ctx.lineWidth = 0.5; ctx.strokeStyle = '#FF3030'; ctx.strokeRect(x1, top + 0.4, x0 + want - x1, h - 0.8); }
    ctx.restore();
  }

  function drawRows(ctx, st, L, opt) {
    const n = L.rows.length;
    if (!n) return;
    const g = L.g, W = L.w;
    const y0 = L.firstRow, timed = st.session !== 'race';
    const alpha = opt.panelAlpha !== undefined ? opt.panelAlpha : P.panelAlpha;
    rect(ctx, 0, y0, G.strip, n * p, P.strip);
    rect(ctx, G.strip, y0, W - G.strip, n * p, `rgba(${P.panel.join(',')},${alpha})`);
    const num = timed ? g.num.timed : g.num.race;
    const labelCap = timed ? G.labelCap.timed : G.labelCap.race;
    L.rows.forEach((r, i) => {
      const y = y0 + i * p, mid = y + G.mid;
      const a = r.out ? 0.5 : 1;                                          // retired rows: alpha 0.5
      if (r.ko) hatch(ctx, 0, y, G.strip, p);
      if (r.me && opt.highlight !== false) rect(ctx, 0, y, W, p, P.me);
      if (i > 0) rect(ctx, 0, y - G.stripSepH / 2, G.strip, G.stripSepH, P.stripSep);
      // position strip
      if (r.pos === 1) rect(ctx, G.p1.x, y + G.p1.y, G.p1.w, G.p1.h, P.red);
      if (r.arrow) {
        const up = r.arrow === 'up';
        triangle(ctx, G.arrow.x, mid + (up ? G.arrow.dyUp : G.arrow.dyDown), G.arrow.w, G.arrow.h, up, up ? P.up : P.down);
      } else {
        position(ctx, String(r.pos), G.posX, mid + G.posCap / 2, G.posCap, P.pos, a);
      }
      // team-colour bar (opt.bar): the game's own colour for the car (nub_colour); no colour, no bar
      if (g.bar && r.col) {
        ctx.save(); ctx.globalAlpha *= a;
        rect(ctx, G.bar.x, mid - G.bar.h / 2, G.bar.w, G.bar.h, r.col);
        ctx.restore();
      }
      // team badge slot (game texture); empty while the Team logos setting is off or the car has no logo. With the bar
      // the slot is as wide as the game's logo square (G.badgeH, 8.46 HUD), the most a logo can take in game.
      const bw = g.bar ? G.badgeH : 0.72 * p;
      if (g.logos && r.logo !== false)
        slot(ctx, g.badgeX - bw / 2, mid - 0.25 * p, bw, 0.50 * p, r.team || '', 0.17 * p, Object.assign({}, opt, { alpha: a }));
      // code, or the full surname (names mode 'surname')
      let nameW = null, want = 0;
      if (g.sur) ({ w: nameW, want } = surname(ctx, r.name || r.code, G.codeX, mid + G.codeCap / 2, g.nameBox, a, r.run));
      else text(ctx, r.code, G.codeX, mid + G.codeCap / 2, G.codeCap, { wt: G.codeWt, sx: G.codeSx, color: P.code, alpha: a });
      if (opt.guides) guides(ctx, g, num, mid, g.sur ? want : gameWidth(r.code));
      // gap / interval / lap time / label
      if (r.gap === null || r.gap === undefined) {
        unavailable(ctx, num.r - 0.18 * p, mid, 0.36 * p);
      } else if (/^[+\-−]?[0-9][0-9:.]*$/.test(r.gap)) {
        tabular(ctx, r.gap, num.r, mid + num.cap / 2, num.cap, { color: P.num, alpha: a });
      } else {
        // long labels ('+2 LAPS') squeeze horizontally to keep 0.25 p clear of the code (P1 'Interval' in 'full': ~0.25 p)
        const room = num.r - (G.codeX + (nameW !== null ? nameW : textWidth(ctx, r.code, G.codeCap, G.codeWt, G.codeSx))) - 0.25 * p;
        const w = textWidth(ctx, r.gap, labelCap, 400, G.labelSx);
        const sx = w > room ? G.labelSx * room / w : G.labelSx;
        text(ctx, r.gap, num.r, mid + labelCap / 2, labelCap, { wt: 400, sx, align: 'right', color: P.label, alpha: a });
      }
      // tyre letter
      if (r.tyre === null) unavailable(ctx, g.tyreX, mid, 0.24 * p);
      else if (r.tyre && !r.out) text(ctx, r.tyre, g.tyreX, mid + G.tyreCap / 2, G.tyreCap, { wt: 500, align: 'center', color: P.tyre[r.tyre] || P.num });
      // side boxes, outside the panel: '!' (investigation yellow / penalty red), then 'P' (pit lane)
      let sx = W;
      const box = (fill, glyph, ch) => {
        const s = G.side, top = mid + s.dy - s.h / 2;
        rect(ctx, sx, top, s.w, s.h, fill);
        text(ctx, ch, sx + s.w / 2, mid + s.dy + s.cap / 2, s.cap, { wt: 800, align: 'center', color: glyph });
        sx += s.w + s.gap;
      };
      if (r.pen === 'inv') box(P.inv[0], P.inv[1], '!');
      if (r.pen === 'pen') box(P.pen[0], P.pen[1], '!');
      if (r.pit) box(P.pit[0], P.pit[1], 'P');
    });
  }

  // ---------------------------------------------------------------- public

  function draw(ctx, st, opt) {
    opt = opt || {};
    const L = layout(st, opt);
    if (L.hdr) drawHeader(ctx, st, L, opt);
    if (L.slots) drawStatus(ctx, st, L, opt);
    drawRows(ctx, st, L, opt);
    return L;
  }

  function size(st, opt) {
    const L = layout(st, opt);
    const side = L.rows.some(r => r.pit || r.pen) ? 2 * (G.side.w + G.side.gap) : 0;
    return { w: L.w + side, h: L.h };
  }

  // FIA RACE CONTROL banner (measured on a 577 x 69 crop; its left end is cropped, so x = 0 is the crop edge).
  // opt.height = banner height in HUD units. In game it sits in the game's toast slot (message_system element) and
  // takes that slot's height: 28.8 HUD (TOAST.g_race below). Default = the reference proportions (22.0 HUD).
  function drawBanner(ctx, b, opt) {
    opt = opt || {};
    const B = G.banner, k = opt.height ? opt.height / B.hPx : B.k, H = B.hPx * k;
    const t1 = b.title || 'RACE CONTROL:', t2 = b.message || 'OVERTAKE ENABLED';
    const cap1 = B.cap1 * k, cap2 = B.cap2 * k;
    // text layout first (the banner grows with the message)
    const words1 = t1.split(' '), words2 = t2.split(' ');
    let x = B.t1x * k;
    const runs = [];
    words1.forEach((wd, i) => { const w = textWidth(ctx, wd, cap1, B.wt1, B.sx1); runs.push([wd, x, cap1, B.wt1, B.sx1]); x += w + (i < words1.length - 1 ? B.gapWord1 * k : 0); });
    x += B.gapPhrase * k;
    words2.forEach((wd, i) => { const w = textWidth(ctx, wd, cap2, B.wt2, B.sx2); runs.push([wd, x, cap2, B.wt2, B.sx2]); x += w + (i < words2.length - 1 ? B.gapWord2 * k : 0); });
    const W = x + B.padR * k;
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, P.banner[0]); g.addColorStop(1, P.banner[1]);
    rect(ctx, 0, 0, W, H, g);
    const gl = ctx.createLinearGradient(0, 0, 0.3 * W, H);                  // lighter top-left corner (#1F2738)
    gl.addColorStop(0, 'rgba(31,39,56,0.9)'); gl.addColorStop(1, 'rgba(31,39,56,0)');
    rect(ctx, 0, 0, W, H, gl);
    slot(ctx, B.fia[0] * k, B.fia[2] * k, (B.fia[1] - B.fia[0]) * k, (B.fia[3] - B.fia[2]) * k, 'FIA', 0.25 * p, opt);
    for (const [wd, wx, cap, wt, sx] of runs) text(ctx, wd, wx, B.base * k, cap, { wt, sx, color: P.bannerText });
    return { w: W, h: H };
  }

  // The game's toast slot (element message_system, template hud_notifications_dynamic, anchor_top, position
  // [0, -0.54] in hud_layouts.uidl), measured in HUD units on the reference frames: g_race
  // (FORMATION LAP box) and g_edit (HUD editor, SAFETY CAR box with countdown). y0 = top of the box below its thin
  // light top line (the line starts at 13.1). The top stays put; the height follows the message (28.8 / 32.0).
  // The banner is centred on the screen (the slot's anchor) with its top at y0, and takes the g_race height.
  const TOAST = { g_race: { x0: 239.8, x1: 402.9, y0: 16.0, y1: 44.8 }, g_edit: { x0: 186.4, x1: 453.5, y0: 16.0, y1: 48.0 } };

  root.TOWER = { G, P, TOAST, GAME_CODE, draw, drawBanner, size, layout, geom, gameWidth, window: window_, text, tabular };
})(typeof window !== 'undefined' ? window : globalThis);
