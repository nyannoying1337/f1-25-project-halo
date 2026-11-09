// sim.js — draws the built native scene (halo subtree of dial_om_xm.idf) the way the game composes it:
// quads (mesh 4.48 x 1.92, texture row 0 at the top), eWindow clips, eMaskTexture alpha masks, anim clips driven by
// fractions, template visibility and text bindings. Text uses Saira as a stand-in for the game's F1 font.
(async () => {
  const D = window.SIM, PX = D.px, out = document.getElementById('status');
  const imgs = {};
  await Promise.all(D.sprites.map(n => new Promise((ok, bad) => { const i = new Image(); i.onload = () => { imgs[n] = i; ok(); }; i.onerror = () => bad(new Error('img ' + n)); i.src = D.png + n + '.png'; })));
  await document.fonts.load('700 40px SimSaira');
  const info = D.scene.info;

  function tinted(name, col) {
    const key = name + col; if (imgs[key]) return imgs[key];
    const s = imgs[name], c = document.createElement('canvas'); c.width = s.width; c.height = s.height;
    const g = c.getContext('2d'); g.drawImage(s, 0, 0); g.globalCompositeOperation = 'source-in'; g.fillStyle = col; g.fillRect(0, 0, c.width, c.height);
    return (imgs[key] = c);
  }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function rpmAngle(f) {
    const k = info.rpm_keys; f = Math.max(0, Math.min(1, f));
    for (let i = 1; i < k.length; i++) if (f <= k[i][0]) { const t = (f - k[i - 1][0]) / (k[i][0] - k[i - 1][0]); return lerp(k[i - 1][1], k[i][1], t); }
    return k[k.length - 1][1];
  }

  function render(canvas, st) {
    const g = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    g.fillStyle = '#2a3440'; g.fillRect(0, 0, W, H);
    // faint track-ish backdrop so the translucent band reads like it does in game
    const bg = g.createLinearGradient(0, 0, 0, H); bg.addColorStop(0, '#5d7183'); bg.addColorStop(0.55, '#3a4752'); bg.addColorStop(1, '#22292f');
    g.fillStyle = bg; g.fillRect(0, 0, W, H);
    const base = [PX, 0, 0, -PX, W / 2, H - D.bottomPad];   // scene units, y up; boundless_customisation origin
    // leaves the DLL would write, plus the native VM values
    const leaf = st.leaves || {};
    const short = b => (b.includes('hud_halo_') ? b.split('hud_halo_')[1] : b);   // our VM leaves by short name; game bindings stay unresolved
    const visOf = {}; for (const [, el, lf, neg] of info.vis) { const v = leaf[short(lf)]; visOf[el] = v === undefined ? neg : (neg ? !v : !!v); }
    const textOf = {};
    for (const [, el, tdb, vdb, vdef, neg] of info.texts) {
      const ours = tdb.includes('hud_halo_'), key = ours ? tdb.split('hud_halo_')[1] : tdb;
      const txt = ours ? leaf[key] : (st.native[key] ?? leaf[key]);   // game values: native dial values or #session.* strings
      let vis = true;
      if (vdb) { const lv = leaf[vdb.split('hud_halo_')[1]]; vis = lv === undefined ? vdef : (neg ? !lv : !!lv); }
      textOf[el] = vis && txt !== undefined ? String(txt) : null;
    }
    const team = st.team;
    const layers = new Set(); (function scan(n) { if (n.layer !== undefined && n.layer !== null) layers.add(n.layer); n.kids.forEach(scan); })(D.scene.halo);

    function local(g2, n) {
      if (n.type === 'quad') { g2.translate(n.pos[0], n.pos[1]); g2.scale(n.scale[0], n.scale[2]); return; }
      let ang = n.zrot || 0, p = n.pos;
      if (n.name === 'zh_batt_win_anim' || n.name === 'zh_batt_ctr_anim') {
        const k = n.name === 'zh_batt_win_anim' ? info.batt_keys : info.batt_keys.map(q => [-q[0], -q[1], 0.12]);
        p = [lerp(k[0][0], k[1][0], st.native.ers_stored), lerp(k[0][1], k[1][1], st.native.ers_stored)];
      }
      if (n.name === 'zh_rpm_anim' || n.name === 'zh_rpm_core_anim') ang = rpmAngle(st.native.revs) * 180 / Math.PI;
      g2.translate(p[0], p[1]); if (ang) g2.rotate(ang * Math.PI / 180);
      if (n.type !== 'quad') g2.scale(n.scale[0], n.scale[1]);
    }
    function draw(g2, n, L) {
      if (visOf[n.name] === false) return;
      g2.save(); local(g2, n);
      if (n.type === 'eWindow') { g2.beginPath(); g2.rect(-n.w / 2, -n.h / 2, n.w, n.h); g2.clip(); }
      if (n.type === 'quad' && n.layer === L) {
        let im = imgs[n.sprite];
        if (n.name === 'halo_rails') im = tinted('rails', team);
        if (n.name === 'halo_rpm_fill') im = tinted('solid_white', team);
        g2.save(); g2.scale(1, -1); g2.drawImage(im, -2.24, -0.96, 4.48, 1.92); g2.restore();
      }
      if (n.type === 'eText' && n.layer === L && textOf[n.name]) {
        const em = n.style.match(/(\d+)_/)[1] / 100, u = em / 100;   // draw at 100 px and scale down
        g2.save(); g2.scale(u, -u);
        g2.font = '700 100px SimSaira'; g2.fillStyle = '#F4F7F8';
        g2.textAlign = n.halign === 'centre' ? 'center' : n.halign;
        // the game's text model (measured in game): the origin is the alignment anchor (left edge, right
        // edge or centre) and the baseline, and the cap height is 0.672 em. Saira's cap is 0.688 em: scale to match.
        g2.scale(0.672 / 0.688, 0.672 / 0.688);
        g2.fillText(textOf[n.name].toUpperCase(), 0, 0);
        g2.restore();
      }
      if (n.type === 'eMaskTexture') {
        const off = document.createElement('canvas'); off.width = W; off.height = H;
        const o = off.getContext('2d'); o.setTransform(g2.getTransform());
        n.kids.forEach(k => draw(o, k, L));
        o.globalCompositeOperation = 'destination-in';
        o.save(); o.scale(1, -1); o.drawImage(imgs[n.sprite], -n.w / 2, -n.h / 2, n.w, n.h); o.restore();
        g2.save(); g2.setTransform(1, 0, 0, 1, 0, 0); g2.drawImage(off, 0, 0); g2.restore();
      } else n.kids.forEach(k => draw(g2, k, L));
      g2.restore();
    }
    for (const L of [...layers].sort((a, b) => a - b)) { g.save(); g.setTransform(...base); draw(g, D.scene.halo, L); g.restore(); }
    // stock customisation box (dashed) = what the OSD editor moves/resizes
    g.save(); g.setTransform(...base); const tl = D.scene.box.tl_customisation, br = D.scene.box.br_customisation;
    g.strokeStyle = 'rgba(255,220,120,0.55)'; g.lineWidth = 1.2 / PX; g.setLineDash([6 / PX, 5 / PX]); g.strokeRect(tl[0], br[1], br[0] - tl[0], tl[1] - br[1]); g.restore();
  }

  document.querySelectorAll('canvas[data-state]').forEach(c => render(c, D.states[+c.dataset.state]));
  out.textContent = 'done'; document.title = 'done';
})().catch(e => { document.getElementById('status').textContent = 'ERROR ' + e.stack; document.title = 'error'; });
