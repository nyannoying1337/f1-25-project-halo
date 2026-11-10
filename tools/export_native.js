// export_native.js — renders the textures of the game-native halo HUD from halo.js (the approved mock-up).
// Output: JSON in #out: { G, P, R, names, sprites: [{name, w, h, x0, y0, x1, y1, rgba(base64)}] }.
// Bounds are HUD units (origin = dial centre, 1 unit = 1 px of a 640x360 frame, y down).
// "centre" sprites are drawn with the centre cluster's scale (G.centreScale), so their bounds are HUD units too.
// ?only=a,b renders just those sprites (names lists them all). Since 2026-11-09 headless Chrome on the build PC hangs
// on pages that draw many canvases, so tools/native/export_sprites.py renders one sprite per page.
(async () => {
  const out = document.getElementById('out');
  try {
    const I = HALO.internals, G = HALO.G, P = HALO.P, CS = G.centreScale;
    const q = new URLSearchParams(location.search);
    const R = +(q.get('r') || 3);
    const only = q.has('only') ? q.get('only').split(',').filter(Boolean) : null;   // ?only= (empty): just the names
    await Promise.all([700, 740, 760, 780].map(w => document.fonts.load(`${w} 32px HaloSaira`, 'BOOSTN012345678.')));
    const HUD_BOX = [-235, -50, 240, 130];

    function b64(u8) {
      let s = '';
      for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
      return btoa(s);
    }
    function sprite(name, draw, opts = {}) {
      const box = opts.box || HUD_BOX;
      const [x0, y0, x1, y1] = box, W = Math.round((x1 - x0) * R), H = Math.round((y1 - y0) * R);
      const c = document.createElement('canvas'); c.width = W; c.height = H;
      const g = c.getContext('2d', { willReadFrequently: true });
      g.setTransform(R, 0, 0, R, -x0 * R, -y0 * R); g.lineJoin = 'round';
      if (opts.centre) g.scale(CS, CS);
      draw(g);
      const d = g.getImageData(0, 0, W, H).data;
      let mx0 = W, my0 = H, mx1 = -1, my1 = -1;
      for (let y = 0; y < H; y++) { const row = y * W * 4; for (let x = 0; x < W; x++) if (d[row + x * 4 + 3]) { if (x < mx0) mx0 = x; if (x > mx1) mx1 = x; if (y < my0) my0 = y; my1 = y; } }
      if (mx1 < 0) throw new Error('empty sprite ' + name);
      const pad = 4;
      if (mx0 - pad < 0 || my0 - pad < 0 || mx1 + 1 + pad > W || my1 + 1 + pad > H) throw new Error('sprite touches its render box: ' + name);
      // crop to the drawn pixels plus a pad, rounded up to whole 4x4 blocks
      let cx0 = mx0 - pad, cy0 = my0 - pad, cw = mx1 + 1 + pad - cx0, ch = my1 + 1 + pad - cy0;
      cw = (cw + 3) & ~3; ch = (ch + 3) & ~3;
      const img = g.getImageData(cx0, cy0, cw, ch).data;
      return { name, w: cw, h: ch, x0: x0 + cx0 / R, y0: y0 + cy0 / R, x1: x0 + (cx0 + cw) / R, y1: y0 + (cy0 + ch) / R,
               rgba: b64(new Uint8Array(img.buffer)) };
    }

    // one lit sprite per slat (the slats are tilted, so a horizontal window per level would cut through them)
    const litSlat = (g, left, i, on, onTop) => I.drawSlat(g, left, i, I.slatColour(i, on, onTop), true);
    const centreBase = g => {
      g.beginPath(); g.arc(0, 0, G.disc.r, 0, 7); g.fillStyle = P.discOuter; g.fill();
      I.drawCapsule(g, true, 0, 'RECHARGE'); I.drawCapsule(g, false, 0, 'DEPLOY');
      I.drawStripes(g, true, 0, P.brake, P.brakeTop);
      I.drawStripes(g, false, 0, P.throttle, P.throttleTop);
      I.drawCentreLabels(g);
      I.drawDisc(g);
      I.text(g, 'KM/H', 0, G.kmh.y, G.kmh.fs, P.label, { tr: G.kmh.tr });
      I.text(g, 'MPH', 0, G.mphLbl.y, G.mphLbl.fs, P.label, { tr: G.mphLbl.tr });
    };
    // the G-force meter's centre (docs/gmeter/design.md): no capsules, speed labels, Boost, Overtake or battery;
    // the three rings on the disc. The label, value and indicator are sprites of their own.
    const centreBaseG = g => {
      g.beginPath(); g.arc(0, 0, G.disc.r, 0, 7); g.fillStyle = P.discOuter; g.fill();
      I.drawStripes(g, true, 0, P.brake, P.brakeTop);
      I.drawStripes(g, false, 0, P.throttle, P.throttleTop);
      I.drawCentreLabels(g);
      I.drawDisc(g);
      I.drawGRings(g);
    };
    // the F2 halo's centre (docs/halo-car-classes.md 5.1): the standard centre without the Recharge / Deploy capsules
    const centreBaseF2 = g => {
      g.beginPath(); g.arc(0, 0, G.disc.r, 0, 7); g.fillStyle = P.discOuter; g.fill();
      I.drawStripes(g, true, 0, P.brake, P.brakeTop);
      I.drawStripes(g, false, 0, P.throttle, P.throttleTop);
      I.drawCentreLabels(g);
      I.drawDisc(g);
      I.text(g, 'KM/H', 0, G.kmh.y, G.kmh.fs, P.label, { tr: G.kmh.tr });
      I.text(g, 'MPH', 0, G.mphLbl.y, G.mphLbl.fs, P.label, { tr: G.mphLbl.tr });
    };
    const outer = g => {
      I.drawBand(g); I.drawWing(g, G.wings.L, -1); I.drawWing(g, G.wings.R, 1);
      I.drawGearTrack(g); I.drawGearMarker(g);
      I.drawGearLabels(g);
      I.drawTurnLabel(g);
    };
    const rpmPath = (g, a, b) => {
      g.beginPath();
      for (let i = 0; i <= 200; i++) { const p = I.gearPt(I.lerp(a, b, i / 200), G.gears.track); i ? g.lineTo(...p) : g.moveTo(...p); }
    };
    const gq = G.gears, GM = G.gm, V = GM.val;
    // neighbouring segments overlap by 1 degree each way so no seam shows where two lit ones meet; the lit arc's
    // ends move out by 1 degree (0.3 units at the outer edge)
    const SEG_OVERLAP = 1.0;
    // the value "d.d" in halo.js's fixed slots (gSlots: each digit centred in the widest digit's advance), so a
    // digit's place does not depend on the other digit and the game's value matches halo.js gText
    let digitInfo = null;
    const digitLayout = g => {
      const L = I.gSlots(g);
      digitInfo = { adv: L.adv, A: L.A, w: L.w, tabular: [...'0123456789'].every(ch => Math.abs(L.adv[ch] - L.A) < 1e-6) };
      return L;
    };
    const gDigit = (g, slot, d, red) => {
      const L = digitLayout(g), ch = String(d);
      I.gChar(g, ch, (slot ? L.tenths : L.units) + (L.A - L.adv[ch]) / 2, red);
    };
    const gDot = (g, red) => { const L = digitLayout(g); I.gChar(g, '.', L.dot, red); };

    // [name, draw, options]: drawn only when asked for (?only=), one canvas each
    const specs = [
      ['base', g => { outer(g); g.save(); g.scale(CS, CS); centreBase(g); g.restore(); }],
      ['rails', g => I.drawRails(g, '#FFFFFF')],
      ['arrow_l', g => I.drawTurnArrow(g, false)],
      ['arrow_r', g => I.drawTurnArrow(g, true)],
      ['aero_lbl_w', g => I.drawAeroLabel(g, P.white)],
      ['aero_eq_w', g => I.drawAeroBars(g, true, P.aeroBar)],
      ['aero_sl', g => I.drawAeroBars(g, false, P.aeroBar)],
      ['cap_l_on', g => I.drawCapsule(g, true, 1, 'RECHARGE'), { centre: true }],
      ['cap_r_on', g => I.drawCapsule(g, false, 1, 'DEPLOY'), { centre: true }],
      ...[...Array(G.stripes.n).keys()].flatMap(i => [
        ['str_l_' + i, g => litSlat(g, true, i, P.brake, P.brakeTop), { centre: true }],
        ['str_r_' + i, g => litSlat(g, false, i, P.throttle, P.throttleTop), { centre: true }]]),
      ['boost_off', g => I.drawBoost(g, false), { centre: true }],
      ['boost_on', g => I.drawBoost(g, true), { centre: true }],
      ['ot_off', g => I.drawOT(g, false), { centre: true }],
      ['ot_on', g => I.drawOT(g, true), { centre: true }],
      ['batt_idle', g => { I.battInterior(g, false); I.battOutline(g); }, { centre: true }],
      ['bolt', g => I.battBolt(g), { centre: true }],
      ['batt_fill', g => I.battFill(g, 1), { centre: true }],
      ['rpm_team', g => {
        rpmPath(g, I.RPM_T0, I.RPM_T1); g.lineCap = 'round'; g.strokeStyle = '#FFFFFF';
        g.globalAlpha = 0.22; g.lineWidth = gq.trackW * 2.3; g.stroke(); g.globalAlpha = 1; g.lineWidth = gq.trackW; g.stroke();
      }],
      ['rpm_core', g => {
        rpmPath(g, I.RPM_T0, I.RPM_T1); g.lineCap = 'round';
        g.strokeStyle = 'rgba(225,255,250,0.55)'; g.lineWidth = gq.trackW * 0.35; g.stroke();
      }],
      // unlit digits are separate so the engaged one can be hidden under its lit sprite (the lit digit is bolder and a different size)
      ...[0, 1, 2, 3, 4, 5, 6, 7, 8].map(i => ['gear_off_' + i, g => I.drawGearDigit(g, i, false)]),
      ...[0, 1, 2, 3, 4, 5, 6, 7, 8].map(i => ['gear_' + i, g => I.drawGearDigit(g, i, true)]),
      // G-force meter (optional): its base, the label lit or dimmed, 8 segments, 4 white and 4 red bars, and the
      // value's digits per place (units u, tenths t) and the point, in white and red
      ['base_g', g => { outer(g); g.save(); g.scale(CS, CS); centreBaseG(g); g.restore(); }],
      ['g_lbl', g => I.drawGLabel(g, false), { centre: true }],
      ['g_lbl_dim', g => I.drawGLabel(g, true), { centre: true }],
      ...[...Array(8).keys()].map(k => ['g_seg_' + k, g => I.gSector(g, GM.arc.r0, GM.arc.r1, k * GM.arc.seg, GM.arc.seg / 2 + SEG_OVERLAP, P.gCyan), { centre: true }]),
      ...[0, 1, 2, 3].flatMap(a => [
        ['g_w_' + a, g => I.drawGBlock(g, a * 90, 'white'), { centre: true }],
        ['g_r_' + a, g => I.drawGBlock(g, a * 90, 'red'), { centre: true }]]),
      ...[false, true].flatMap(red => [
        ...[...Array(10).keys()].flatMap(d => [
          [`g_u${red ? 'r' : ''}_${d}`, g => gDigit(g, 0, d, red), { centre: true }],
          [`g_t${red ? 'r' : ''}_${d}`, g => gDigit(g, 1, d, red), { centre: true }]]),
        [`g_dot${red ? '_r' : ''}`, g => gDot(g, red), { centre: true }]]),
      // car classes (docs/halo-car-classes.md): the DRS pill in its three looks (2025 and F2 cars), the ERS MODE
      // caption and the NONE / MEDIUM / HOTLAP pills (2025 cars; OVERTAKE is ot_on), the F2 base (no capsules)
      ['drs_off', g => I.drawDRS(g, 'off')],
      ['drs_avail', g => I.drawDRS(g, 'avail')],
      ['drs_open', g => I.drawDRS(g, 'open')],
      ['ers_cap', g => I.drawErsCaption(g), { centre: true }],
      ['ers_none', g => I.drawErsMode(g, 0), { centre: true }],
      ['ers_medium', g => I.drawErsMode(g, 1), { centre: true }],
      ['ers_hotlap', g => I.drawErsMode(g, 2), { centre: true }],
      ['base_f2', g => { outer(g); g.save(); g.scale(CS, CS); centreBaseF2(g); g.restore(); }],
    ];

    const names = specs.map(s => s[0]);
    const unknown = (only || []).filter(n => !names.includes(n));
    if (unknown.length) throw new Error('unknown sprite ' + unknown.join(','));
    const sprites = specs.filter(s => !only || only.includes(s[0])).map(([n, d, o]) => sprite(n, d, o));
    out.textContent = JSON.stringify({ G, P, R, CAP: I.CAP, RPM_T0: I.RPM_T0, RPM_T1: I.RPM_T1, names, digits: digitInfo, sprites });
    document.title = 'done';
  } catch (e) { out.textContent = 'ERROR ' + e.stack; document.title = 'error'; }
})();
