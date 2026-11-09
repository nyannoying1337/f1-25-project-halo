// export_native.js — renders the textures of the game-native halo HUD from halo.js (the reference drawing).
// Output: JSON in #out: { G, P, R, sprites: [{name, w, h, x0, y0, x1, y1, rgba(base64)}] }.
// Bounds are HUD units (origin = dial centre, 1 unit = 1 px of a 640x360 frame, y down).
// "centre" sprites are drawn with the centre cluster's scale (G.centreScale), so their bounds are HUD units too.
(async () => {
  const out = document.getElementById('out');
  try {
    const I = HALO.internals, G = HALO.G, P = HALO.P, CS = G.centreScale;
    const R = +(new URLSearchParams(location.search).get('r') || 3);
    await Promise.all([700, 740, 760, 780].map(w => document.fonts.load(`${w} 32px HaloSaira`, 'BOOSTN012345678')));
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
    const rpmPath = (g, a, b) => {
      g.beginPath();
      for (let i = 0; i <= 200; i++) { const p = I.gearPt(I.lerp(a, b, i / 200), G.gears.track); i ? g.lineTo(...p) : g.moveTo(...p); }
    };
    const q = G.gears;

    const sprites = [
      sprite('base', g => {
        I.drawBand(g); I.drawWing(g, G.wings.L, -1); I.drawWing(g, G.wings.R, 1);
        I.drawGearTrack(g); I.drawGearMarker(g);
        I.drawGearLabels(g);
        I.drawTurnLabel(g);
        g.save(); g.scale(CS, CS); centreBase(g); g.restore();
      }),
      sprite('rails', g => I.drawRails(g, '#FFFFFF')),
      sprite('arrow_l', g => I.drawTurnArrow(g, false)),
      sprite('arrow_r', g => I.drawTurnArrow(g, true)),
      sprite('aero_lbl_w', g => I.drawAeroLabel(g, P.white)),
      sprite('aero_eq_w', g => I.drawAeroBars(g, true, P.aeroBar)),
      sprite('aero_sl', g => I.drawAeroBars(g, false, P.aeroBar)),
      sprite('cap_l_on', g => I.drawCapsule(g, true, 1, 'RECHARGE'), { centre: true }),
      sprite('cap_r_on', g => I.drawCapsule(g, false, 1, 'DEPLOY'), { centre: true }),
      ...[...Array(G.stripes.n).keys()].flatMap(i => [
        sprite('str_l_' + i, g => litSlat(g, true, i, P.brake, P.brakeTop), { centre: true }),
        sprite('str_r_' + i, g => litSlat(g, false, i, P.throttle, P.throttleTop), { centre: true })]),
      sprite('boost_off', g => I.drawBoost(g, false), { centre: true }),
      sprite('boost_on', g => I.drawBoost(g, true), { centre: true }),
      sprite('ot_off', g => I.drawOT(g, false), { centre: true }),
      sprite('ot_on', g => I.drawOT(g, true), { centre: true }),
      sprite('batt_idle', g => { I.battInterior(g, false); I.battOutline(g); }, { centre: true }),
      sprite('bolt', g => I.battBolt(g), { centre: true }),
      sprite('batt_fill', g => I.battFill(g, 1), { centre: true }),
      sprite('rpm_team', g => {
        rpmPath(g, I.RPM_T0, I.RPM_T1); g.lineCap = 'round'; g.strokeStyle = '#FFFFFF';
        g.globalAlpha = 0.22; g.lineWidth = q.trackW * 2.3; g.stroke(); g.globalAlpha = 1; g.lineWidth = q.trackW; g.stroke();
      }),
      sprite('rpm_core', g => {
        rpmPath(g, I.RPM_T0, I.RPM_T1); g.lineCap = 'round';
        g.strokeStyle = 'rgba(225,255,250,0.55)'; g.lineWidth = q.trackW * 0.35; g.stroke();
      }),
      // unlit digits are separate so the engaged one can be hidden under its lit sprite (the lit digit is bolder and a different size)
      ...[0, 1, 2, 3, 4, 5, 6, 7, 8].map(i => sprite('gear_off_' + i, g => I.drawGearDigit(g, i, false))),
      ...[0, 1, 2, 3, 4, 5, 6, 7, 8].map(i => sprite('gear_' + i, g => I.drawGearDigit(g, i, true))),
    ];

    out.textContent = JSON.stringify({ G, P, R, CAP: I.CAP, RPM_T0: I.RPM_T0, RPM_T1: I.RPM_T1, sprites });
    document.title = 'done';
  } catch (e) { out.textContent = 'ERROR ' + e.stack; document.title = 'error'; }
})();
