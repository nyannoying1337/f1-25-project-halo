// export_tower.js - renders the timing tower's baked textures from tools/tower/tower.js (the approved drawing).
// Output: JSON in #out: { G, P, R, BANNER, names, sprites: [{name, w, h, x0, y0, x1, y1, exact?, rgba(base64)}] }.
// URL: ?r=<px per HUD unit> (default 4), ?only=<sprite name> (draw just that one), ?list=1 (names only, no drawing).
// Since 2026-11-09 headless Chrome on this PC hangs on pages that draw more than a couple of canvases, so
// export_sprites.py renders one sprite per Chrome run (?only=) and merges the results.
//
// Only static art is baked: backgrounds, the header band, status blocks, arrows, tyre letters, side boxes and the
// banner background. Live text (positions, codes, gaps, the session line, banner texts) is drawn by the game's own
// text styles; the F1 logo and the FIA badge are the game's own textures (never drawn or shipped here). Baked letters
// use Saira (SIL OFL), never the F1 font.
//
// FRAMES (bounds are HUD units, 1 unit = 3 px at 1080p, y down):
//   tower  origin = top-left of the panel: hdr
//   row    origin = top-left of a row cell: up, dn, ty_*
//   box    origin = top-left of a side box: pen, pit
//   block  origin = top-left of a status block: sc, vsc, chq, yel, red
//   banner origin = top-left of the banner: bn_l, bn_m, bn_r
// "exact" sprites fill their box edge to edge (no padding): they set the bounds the game's stackers lay out with.
(async () => {
  const out = document.getElementById('out');
  try {
    const T = TOWER, G = T.G, P = T.P, p = G.p;
    // Fix round 1 (2026-11-09, docs/timing-tower/ui-build.md "Fix round 1"): the game's own number font is about 40 %
    // wider than the drawing's, so a two-digit gap ("+33.7") filled its whole box and sat 0.08 p from the widest code
    // (HAM). The build's panel is 0.2 p wider than the drawing's (81.96 -> 84.56 HUD); the gap and tyre columns move
    // right with the panel's right edge, the gap column 1.0 HUD more (closer to the tyre letter, as F1 TV); the F1
    // logo and the FIA badge stay centred. Everything left of the gap column (strip, badge slot, code) is unchanged.
    // Applied here so the baked sprites (header, SC / VSC / chequered blocks, tyre letters) and sprites.json's G (read
    // by tower_native.py) carry the same geometry. tools/tower/tower.js (the approved drawing) is not changed.
    const FIX1 = { dW: 0.2 * p, dGap: 1.0 };
    G.w += FIX1.dW; G.tyreX += FIX1.dW;
    G.num.race.r += FIX1.dW + FIX1.dGap; G.num.timed.r += FIX1.dW + FIX1.dGap;
    G.logo.x += FIX1.dW / 2; G.fia.x += FIX1.dW / 2;
    G.fix1 = FIX1;
    const q = new URLSearchParams(location.search);
    const R = +(q.get('r') || 4);                       // texture px per HUD unit (4 = 1:1 at 1440p)
    const only = q.get('only'), listOnly = q.get('list') === '1';
    if (!listOnly)
      await Promise.all([300, 400, 500, 600, 700, 800].map(w => document.fonts.load(`${w} 32px TowerSaira`, 'SAFETYCARVIRTULHQEDFLGP!MWONS0123456789')));

    function b64(u8) {
      let s = '';
      for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
      return btoa(s);
    }
    // exact: the canvas is the box (sizes rounded up to whole 4x4 blocks; the drawing is stretched onto it, < 0.5 %)
    function exact(name, box, draw) {
      const [x0, y0, x1, y1] = box;
      const W = Math.ceil((x1 - x0) * R / 4) * 4, H = Math.ceil((y1 - y0) * R / 4) * 4;
      const c = document.createElement('canvas'); c.width = W; c.height = H;
      const g = c.getContext('2d', { willReadFrequently: true });
      g.setTransform(W / (x1 - x0), 0, 0, H / (y1 - y0), -x0 * W / (x1 - x0), -y0 * H / (y1 - y0));
      draw(g);
      const img = g.getImageData(0, 0, W, H).data;
      return { name, w: W, h: H, x0, y0, x1, y1, exact: true, rgba: b64(new Uint8Array(img.buffer)) };
    }
    // padded: drawn in a generous box, cropped to the ink plus 2 px, rounded up to whole 4x4 blocks
    function padded(name, box, draw) {
      const [x0, y0, x1, y1] = box, W = Math.round((x1 - x0) * R), H = Math.round((y1 - y0) * R);
      const c = document.createElement('canvas'); c.width = W; c.height = H;
      const g = c.getContext('2d', { willReadFrequently: true });
      g.setTransform(R, 0, 0, R, -x0 * R, -y0 * R);
      draw(g);
      const d = g.getImageData(0, 0, W, H).data;
      let mx0 = W, my0 = H, mx1 = -1, my1 = -1;
      for (let y = 0; y < H; y++) { const row = y * W * 4; for (let x = 0; x < W; x++) if (d[row + x * 4 + 3]) { if (x < mx0) mx0 = x; if (x > mx1) mx1 = x; if (y < my0) my0 = y; my1 = y; } }
      if (mx1 < 0) throw new Error('empty sprite ' + name);
      const pad = 2;
      if (mx0 - pad < 0 || my0 - pad < 0 || mx1 + 1 + pad > W || my1 + 1 + pad > H) throw new Error('sprite touches its render box: ' + name);
      let cx0 = mx0 - pad, cy0 = my0 - pad, cw = mx1 + 1 + pad - cx0, ch = my1 + 1 + pad - cy0;
      cw = (cw + 3) & ~3; ch = (ch + 3) & ~3;
      const img = g.getImageData(cx0, cy0, cw, ch).data;
      return { name, w: cw, h: ch, x0: x0 + cx0 / R, y0: y0 + cy0 / R, x1: x0 + (cx0 + cw) / R, y1: y0 + (cy0 + ch) / R,
               rgba: b64(new Uint8Array(img.buffer)) };
    }
    const rect = (g, x, y, w, h, col) => { g.fillStyle = col; g.fillRect(x, y, w, h); };
    // tower.js triangle(): the arrow glyph
    function triangle(g, cx, cy, w, h, up, color) {
      g.save(); g.beginPath();
      if (up) { g.moveTo(cx, cy - h / 2); g.lineTo(cx + w / 2, cy + h / 2); g.lineTo(cx - w / 2, cy + h / 2); }
      else { g.moveTo(cx, cy + h / 2); g.lineTo(cx + w / 2, cy - h / 2); g.lineTo(cx - w / 2, cy - h / 2); }
      g.closePath(); g.fillStyle = color; g.fill();
      g.strokeStyle = color; g.lineJoin = 'round'; g.lineWidth = 0.05 * w; g.stroke(); g.restore();
    }

    const W = G.w, S = G.status, B = G.banner, side = G.side, SC = S.sc;
    const jobs = [];                                     // [name, () => sprite]
    const job = (name, make) => jobs.push([name, make]);

    // ---- header band (tower frame): gradient, separator line, session band. The F1 logo and the FIA badge are
    // game textures on their own quads; the session line is live game text.
    job('hdr', () => exact('hdr', [0, 0, W, G.sep + G.band], g => {
      const gr = g.createLinearGradient(0, 0, 0, G.sep);
      gr.addColorStop(0, P.hdrTop); gr.addColorStop(0.5, P.hdrMid); gr.addColorStop(1, P.hdrSep);
      rect(g, 0, 0, W, G.sep, gr);
      rect(g, 0, G.sep, W, G.band, P.band);
      rect(g, 0, G.sep - G.sepH / 2, W, G.sepH, P.separator);
    }));

    // ---- row parts (row frame)
    const row = [-0.5, -0.5, W + 0.5, p + 0.5];
    job('up', () => padded('up', row, g => triangle(g, G.arrow.x, G.mid + G.arrow.dyUp, G.arrow.w, G.arrow.h, true, P.up)));
    job('dn', () => padded('dn', row, g => triangle(g, G.arrow.x, G.mid + G.arrow.dyDown, G.arrow.w, G.arrow.h, false, P.down)));
    for (const L of ['S', 'M', 'H', 'I', 'W'])
      job('ty_' + L, () => padded('ty_' + L, row, g => T.text(g, L, G.tyreX, G.mid + G.tyreCap / 2, G.tyreCap, { wt: 500, align: 'center', color: P.tyre[L] })));

    // ---- side boxes (box frame): '!' penalty (red), 'P' pit lane (white)
    const sideBox = (name, fill, glyph, ch) => exact(name, [0, 0, side.w, side.h], g => {
      rect(g, 0, 0, side.w, side.h, fill);
      T.text(g, ch, side.w / 2, side.h / 2 + side.cap / 2, side.cap, { wt: 800, align: 'center', color: glyph });
    });
    job('pen', () => sideBox('pen', P.pen[0], P.pen[1], '!'));
    job('pit', () => sideBox('pit', P.pit[0], P.pit[1], 'P'));

    // ---- status blocks (block frame). Two row slots for SC / VSC, one for the chequered flag. The FIA badge in the
    // SC box is the game's texture on its own quad (S.sc.fx0..fx1, fy0..fy1).
    job('sc', () => exact('sc', [0, 0, W, 2 * p], g => {
      rect(g, 0, 0, W, 1.998 * p, P.sc);
      const cap = (SC.l1[1] - SC.l1[0]) * p;
      T.text(g, 'SAFETY', SC.tx * p, SC.l1[1] * p, cap, { wt: SC.wt, sx: SC.sx, color: '#000' });
      T.text(g, 'CAR', SC.tx * p, SC.l2[1] * p, cap, { wt: SC.wt, sx: SC.sx, color: '#000' });
    }));
    job('vsc', () => exact('vsc', [0, 0, W, 2 * p], g => {
      rect(g, 0, 0, W, 1.998 * p, P.sc);
      const cap = 0.34 * p, x = SC.tx * p;
      T.text(g, 'VIRTUAL', x, 0.62 * p, cap, { wt: SC.wt, sx: 1.05, color: '#000' });
      T.text(g, 'SAFETY', x, 1.15 * p, cap, { wt: SC.wt, sx: 1.05, color: '#000' });
      T.text(g, 'CAR', x, 1.68 * p, cap, { wt: SC.wt, sx: 1.05, color: '#000' });
    }));
    job('chq', () => exact('chq', [0, 0, W, p], g => {
      const sq = 0.25 * p;
      for (let i = 0; i * sq < W; i++) for (let j = 0; j < 4; j++) rect(g, i * sq, j * sq, sq, sq, (i + j) % 2 ? '#111' : '#EEE');
      g.save(); g.font = `700 ${(0.40 * p / 0.69 * 10).toFixed(2)}px TowerSaira`;
      const m = g.measureText('CHEQUERED FLAG'); g.restore();
      const tw = (m.actualBoundingBoxLeft + m.actualBoundingBoxRight) / 10 + 0.5 * p;
      rect(g, W / 2 - tw / 2, 0.12 * p, tw, 0.76 * p, P.darkBand);
      T.text(g, 'CHEQUERED FLAG', W / 2, G.mid + 0.2 * p, 0.40 * p, { wt: 700, align: 'center', color: P.sess });
    }));

    // ---- flag blocks (block frame, round 2, leaves v3), two row slots each, as tower.js drawStatus: the bar, then
    // the dark band over its last fraction. Yellow: the band's line is live game text (lng_sector + hud_tt_ysec, never
    // TRACK HAZARD). Red: SESSION STOPPED is baked with the bar, as the drawing.
    job('yel', () => exact('yel', [0, 0, W, 2 * p], g => {
      rect(g, 0, 0, W, 1.005 * p, P.yellow);
      T.text(g, 'YELLOW FLAG', W / 2, G.mid + S.barCap * p / 2, S.barCap * p, { wt: S.barWt, sx: S.barSx, align: 'center', color: P.yellowText });
      rect(g, 0, p, W, p, P.darkBand);
    }));
    job('red', () => exact('red', [0, 0, W, 2 * p], g => {
      rect(g, 0, 0, W, 1.032 * p, P.red);
      T.text(g, 'RED FLAG', W / 2, G.mid + S.redCap * p / 2, S.redCap * p, { wt: S.redWt, sx: S.redSx, align: 'center', color: P.redFlagText });
      rect(g, 0, p, W, p, P.darkBand);
      T.text(g, 'SESSION STOPPED', W / 2, p + G.mid + S.stopCap * p / 2, S.stopCap * p, { wt: S.stopWt, sx: S.stopSx, align: 'center', color: P.stopped });
    }));

    // ---- Race Control banner background (banner frame, Decision 6): the game's own toast restyled in place; its
    // texts stay the game's. The width follows the message, so the background is three pieces: the left end (FIA
    // badge area, fixed width), a narrow middle the game's scaler stretches, and the right end.
    // BH = the banner height in HUD units (Decision 6: about 24 % below the toast's full 28.8 HUD).
    const BH = 22.0, k = BH / B.hPx, leftW = B.t1x * k - 2.0, rightW = B.padR * k;
    const bnGrad = (g, x0, x1) => {
      const gr = g.createLinearGradient(0, 0, 0, BH);
      gr.addColorStop(0, P.banner[0]); gr.addColorStop(1, P.banner[1]);
      rect(g, x0, 0, x1 - x0, BH, gr);
    };
    job('bn_l', () => exact('bn_l', [0, 0, leftW, BH], g => {
      bnGrad(g, 0, leftW);
      const gl = g.createLinearGradient(0, 0, leftW, BH);           // lighter top-left corner, gone at the piece's edge
      gl.addColorStop(0, 'rgba(31,39,56,0.9)'); gl.addColorStop(1, 'rgba(31,39,56,0)');
      rect(g, 0, 0, leftW, BH, gl);
    }));
    job('bn_m', () => exact('bn_m', [0, 0, 1, BH], g => bnGrad(g, 0, 1)));
    job('bn_r', () => exact('bn_r', [0, 0, rightW, BH], g => bnGrad(g, 0, rightW)));

    const names = jobs.map(j => j[0]);
    const sprites = listOnly ? [] : jobs.filter(j => !only || j[0] === only).map(j => j[1]());
    if (only && !sprites.length) throw new Error('no sprite ' + only);
    out.textContent = JSON.stringify({ G, P, R, BANNER: { H: BH, k, leftW, rightW }, names, sprites });
    document.title = 'done';
  } catch (e) { out.textContent = 'ERROR ' + e.stack; document.title = 'error'; }
})();
