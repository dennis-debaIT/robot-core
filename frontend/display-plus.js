/* ─────────────────────────────────────────────────────────────
   Erika Plus — kostenpflichtige Display-Module
   ─────────────────────────────────────────────────────────────
   Diese Datei wird im Community-Build NICHT ausgeliefert (siehe
   backend/Dockerfile, EDITION=community). Fehlt sie, ist window._pvPlus
   undefiniert und openPvStats() in display.html zeigt die Upgrade-Box.

   Enthält: PV-Statistik-Overlay (Fluss, Tag/Woche/Monat/Jahr),
   Energiefluss-Diagramm und die SVG-Chart-Helfer.
   ───────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  let _pvStatsView = 'flow';
  let _pvStatsRefreshInterval = null;

  function _svgBar(labels, values, unit, w, h, color = '#00c8ff') {
    const valid = values.map(v => v ?? 0);
    const maxV  = Math.max(...valid, 0.01);
    const pad   = { t: 10, r: 8, b: 32, l: 38 };
    const cw    = w - pad.l - pad.r;
    const ch    = h - pad.t - pad.b;
    const bw    = Math.max(4, cw / Math.max(labels.length, 1) * 0.7);
    const gap   = cw / Math.max(labels.length, 1);
    let bars = '', lbls = '';
    const dimColor = color.startsWith('#') ? color + '59' : color.replace(')', ',0.35)').replace('rgb(', 'rgba(');
    valid.forEach((v, i) => {
      const bh = ch * (v / maxV);
      const x  = pad.l + gap * i + (gap - bw) / 2;
      const y  = pad.t + ch - bh;
      const isToday = (i === valid.length - 1);
      bars += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1,bh).toFixed(1)}"
        fill="${isToday ? color : dimColor}" rx="3"
        title="${labels[i]}: ${v} ${unit}"/>`;
      if (i % Math.max(1, Math.floor(labels.length / 8)) === 0 || i === labels.length - 1)
        lbls += `<text x="${(x + bw/2).toFixed(1)}" y="${(h - 6).toFixed(1)}" text-anchor="middle"
          font-size="9" style="fill:var(--muted);">${labels[i]}</text>`;
    });
    const ySteps = [0, 0.25, 0.5, 0.75, 1].map(f => ({
      y: pad.t + ch * (1 - f), v: (maxV * f).toFixed(maxV < 10 ? 1 : 0),
    }));
    const yLines = ySteps.map(s =>
      `<line x1="${pad.l}" x2="${w - pad.r}" y1="${s.y.toFixed(1)}" y2="${s.y.toFixed(1)}" style="stroke:var(--border);opacity:0.7;" stroke-width="1"/>
       <text x="${(pad.l - 3).toFixed(1)}" y="${(s.y + 3.5).toFixed(1)}" text-anchor="end" font-size="9" style="fill:var(--muted);">${s.v}</text>`
    ).join('');
    return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;max-width:${w}px;display:block;">
      ${yLines}${bars}${lbls}
    </svg>`;
  }

  function _svgLine(labels, values, unit, w, h) {
    const valid = values.map(v => v ?? 0);
    const maxV  = Math.max(...valid, 0.01);
    const pad   = { t: 10, r: 8, b: 32, l: 46 };
    const cw    = w - pad.l - pad.r;
    const ch    = h - pad.t - pad.b;
    const pts   = valid.map((v, i) => [
      pad.l + (cw / Math.max(valid.length - 1, 1)) * i,
      pad.t + ch - ch * (v / maxV),
    ]);
    const poly  = pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
    const area  = `${pts[0][0].toFixed(1)},${(pad.t+ch).toFixed(1)} ` + poly
                + ` ${pts[pts.length-1][0].toFixed(1)},${(pad.t+ch).toFixed(1)}`;
    let lbls = '';
    const _maxLbls = 7;
    const _step = Math.max(1, Math.floor(labels.length / _maxLbls));
    labels.forEach((l, i) => {
      if (i % _step === 0 || i === labels.length - 1) {
        const anchor = i === labels.length - 1 ? 'end' : i === 0 ? 'start' : 'middle';
        lbls += `<text x="${pts[i][0].toFixed(1)}" y="${(h-6).toFixed(1)}" text-anchor="${anchor}" font-size="9" style="fill:var(--muted);">${l}</text>`;
      }
    });
    const ySteps = [0, 0.25, 0.5, 0.75, 1].map(f => ({
      y: pad.t + ch * (1 - f), v: (maxV * f).toFixed(maxV < 1000 ? 0 : 0),
    }));
    const yLines = ySteps.map(s =>
      `<line x1="${pad.l}" x2="${w - pad.r}" y1="${s.y.toFixed(1)}" y2="${s.y.toFixed(1)}" style="stroke:var(--border);opacity:0.7;" stroke-width="1"/>
       <text x="${(pad.l - 3).toFixed(1)}" y="${(s.y + 3.5).toFixed(1)}" text-anchor="end" font-size="9" style="fill:var(--muted);">${s.v}</text>`
    ).join('');
    const lastPt = pts[pts.length - 1];
    const liveDot = lastPt
      ? `<circle cx="${lastPt[0].toFixed(1)}" cy="${lastPt[1].toFixed(1)}" r="4" style="fill:var(--accent);stroke:var(--bg);" stroke-width="2"/>`
      : '';
    return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;max-width:${w}px;display:block;">
      ${yLines}
      <defs><linearGradient id="pvg" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#00c8ff" stop-opacity="0.35"/>
        <stop offset="100%" stop-color="#00c8ff" stop-opacity="0.03"/>
      </linearGradient></defs>
      <polygon points="${area}" fill="url(#pvg)"/>
      <polyline points="${poly}" fill="none" stroke="#00c8ff" stroke-width="2" stroke-linejoin="round"/>
      ${liveDot}
      ${lbls}
    </svg>`;
  }

  function _renderPvFlowDiagram(pv) {
    if (!pv) return '<div class="cal-placeholder">PV-Daten nicht verf&uuml;gbar</div>';
    const pvW    = parseFloat(pv.power?.value)            || 0;
    const houseW = parseFloat(pv.house_consumption?.value) || 0;
    const gridW  = parseFloat(pv.grid?.value)             || 0;
    const battPct = pv.battery?.value != null ? parseFloat(pv.battery.value) : null;
    const hasBatt = battPct !== null && !isNaN(battPct);
    const battW   = pvW - houseW - gridW;

    const fmtW = w => {
      const a = Math.abs(w);
      return a >= 1000 ? (a/1000).toFixed(2).replace('.',',') + ' kW' : Math.round(a) + ' W';
    };
    const spd = w => Math.max(1.5, 6 / (Math.abs(w) / 400 + 1)).toFixed(2);

    // Farben
    const C_PV   = '#f59e0b';  // amber — Solar
    const C_BATT = '#10b981';  // grün — Batterie
    const C_FEED = '#10b981';  // grün — Einspeisung
    const C_DRAW = '#f59e0b';  // amber — Netzbezug
    const C_HOUSE = '#6366f1'; // indigo — Verbrauch
    const gColor  = gridW >= 0 ? C_FEED : C_DRAW;

    // Knotenpositionen (cx, cy, r)
    const VW = 370, VH = hasBatt ? 330 : 300;
    const cx = VW / 2;
    const nPV    = { x: cx,  y: 56,  r: 40 };
    const nHouse = { x: cx,  y: hasBatt ? 268 : 240, r: 40 };
    const nBatt  = hasBatt ? { x: 62,  y: 168, r: 34 } : null;
    const nGrid  = { x: hasBatt ? 308 : cx+70, y: 168, r: 34 };

    // Kantenpunkt: vom Kreis-Rand in Richtung Ziel
    const ep = (ax, ay, bx, by, r) => {
      const dx = bx-ax, dy = by-ay, d = Math.sqrt(dx*dx+dy*dy);
      return [+(ax+dx/d*r).toFixed(1), +(ay+dy/d*r).toFixed(1)];
    };

    // Linie mit animierten Strichen
    const flowLine = (n1, n2, color, power, fwd) => {
      const [x1,y1] = ep(n1.x, n1.y, n2.x, n2.y, n1.r+2);
      const [x2,y2] = ep(n2.x, n2.y, n1.x, n1.y, n2.r+2);
      const base = `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" style="stroke:var(--border);stroke-width:5;stroke-linecap:round;"/>`;
      if (Math.abs(power) < 5) return base;
      const s = spd(power), dir = fwd ? 'pv-flow-fwd' : 'pv-flow-rev';
      return base + `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke-dasharray="8 10"
        style="stroke:${color};stroke-width:3.5;stroke-linecap:round;animation:${dir} ${s}s linear infinite;"/>`;
    };

    // Kreisknoten mit Glow, Ikone, Wert, Label
    const circleNode = (n, icon, val, lbl, color, sub) => {
      const glow = `drop-shadow(0 0 8px ${color}99)`;
      return `
        <circle cx="${n.x}" cy="${n.y}" r="${n.r+10}" style="fill:${color};opacity:0.10;"/>
        <circle cx="${n.x}" cy="${n.y}" r="${n.r+5}"  style="fill:${color};opacity:0.15;"/>
        <circle cx="${n.x}" cy="${n.y}" r="${n.r}"     style="fill:var(--surface);stroke:${color};stroke-width:2.5;filter:${glow};"/>
        <g transform="translate(${n.x},${n.y-10})" style="fill:${color};">${icon}</g>
        <text x="${n.x}" y="${n.y+13}" text-anchor="middle" font-size="11" font-weight="800" font-family="monospace"
          style="fill:${color};">${val}</text>
        <text x="${n.x}" y="${n.y+n.r+14}" text-anchor="middle" font-size="9" style="fill:var(--muted);">${lbl}</text>
        ${sub ? `<text x="${n.x}" y="${n.y+n.r+24}" text-anchor="middle" font-size="8" style="fill:var(--muted);">${sub}</text>` : ''}`;
    };

    // SVG-Ikonen (zentriert bei 0,0)
    const iconSun = `<circle cx="0" cy="0" r="5" fill="inherit"/>
      ${[0,45,90,135,180,225,270,315].map(a => {
        const rad=a*Math.PI/180, x1=Math.cos(rad)*7, y1=Math.sin(rad)*7, x2=Math.cos(rad)*9.5, y2=Math.sin(rad)*9.5;
        return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" style="fill:none;"/>`;
      }).join('')}`;

    const iconHouse = `<polyline points="0,-13 13,0 10,0 10,12 -10,12 -10,0 -13,0 0,-13"
        style="fill:none;stroke:currentColor;stroke-width:1.5;stroke-linejoin:round;"/>
      <rect x="-4" y="3" width="8" height="9" style="fill:currentColor;"/>`;

    const battFill = Math.max(0, Math.min(100, battPct||0));
    const iconBatt = `<rect x="-10" y="-7" width="18" height="13" rx="2" style="fill:none;stroke:currentColor;stroke-width:1.5;"/>
      <rect x="8" y="-4.5" width="3.5" height="7" rx="1" style="fill:currentColor;"/>
      <rect x="-8.5" y="-5.5" width="${(battFill*0.155).toFixed(1)}" height="10" rx="1" style="fill:currentColor;opacity:0.8;"/>`;

    const iconGrid = `<line x1="0" y1="-13" x2="-9" y2="13" style="stroke:currentColor;stroke-width:1.5;stroke-linecap:round;fill:none;"/>
      <line x1="0" y1="-13" x2="9"  y2="13" style="stroke:currentColor;stroke-width:1.5;stroke-linecap:round;fill:none;"/>
      <line x1="-7" y1="-2" x2="7"  y2="-2" style="stroke:currentColor;stroke-width:1.5;stroke-linecap:round;fill:none;"/>
      <line x1="-5" y1="6"  x2="5"  y2="6"  style="stroke:currentColor;stroke-width:1.5;stroke-linecap:round;fill:none;"/>`;

    const gridLabel = gridW >  5 ? fmtW(gridW)+' ↑' : gridW < -5 ? fmtW(Math.abs(gridW))+' ↓' : '~0';
    const gridSub   = gridW >= 0 ? 'Einspeisung' : 'Netzbezug';
    const battSub   = Math.abs(battW) > 5
      ? (battW > 0 ? '+'+fmtW(battW)+' lädt' : fmtW(Math.abs(battW))+' entlädt')
      : 'Standby';

    // Richtungslogik: immer fwd=true, bei Gegenrichtung power=0 → nur Basislinie
    const linePvHouse = flowLine(nPV,   nHouse, C_PV,   Math.max(0, pvW),    true);
    const linePvBatt  = nBatt ? flowLine(nPV,   nBatt,  C_BATT, Math.max(0,  battW), true) : '';
    const lineBattH   = nBatt ? flowLine(nBatt, nHouse, C_BATT, Math.max(0, -battW), true) : '';
    const linePvGrid  = flowLine(nPV,   nGrid,  gColor, Math.max(0,  gridW), true);
    const lineGridH   = flowLine(nGrid, nHouse, gColor, Math.max(0, -gridW), true);

    return `<div style="display:flex;justify-content:center;padding:8px 0 0;">
      <svg viewBox="0 0 ${VW} ${VH}" style="width:100%;max-width:480px;display:block;">
        <defs><style>
          @keyframes pv-flow-fwd { from{stroke-dashoffset:36;} to{stroke-dashoffset:0;} }
          @keyframes pv-flow-rev { from{stroke-dashoffset:0;} to{stroke-dashoffset:36;} }
        </style></defs>
        ${linePvHouse}${linePvBatt}${linePvGrid}${lineBattH}${lineGridH}
        ${circleNode(nPV,    iconSun,  fmtW(pvW),    'PV-Anlage',  C_PV,    pvW > 5 ? 'produziert' : 'inaktiv')}
        ${circleNode(nHouse, iconHouse,fmtW(houseW), 'Verbrauch',  C_HOUSE, '')}
        ${circleNode(nGrid,  iconGrid, gridLabel,    'Netz',       gColor,  gridSub)}
        ${nBatt ? circleNode(nBatt, iconBatt, (battPct||0)+'%', 'Batterie', C_BATT, battSub) : ''}
      </svg>
    </div>`;
  }

  async function loadPvStatsView(view) {
    _pvStatsView = view;
    // Refresh-Intervall anpassen wenn Tab wechselt
    clearInterval(_pvStatsRefreshInterval);
    _pvStatsRefreshInterval = setInterval(() => loadPvStatsView(_pvStatsView),
      view === 'flow' ? 5000 : 60000);

    ['flow','today','7days','month','year'].forEach(v => {
      const btn = document.getElementById(`pvtab-${v}`);
      if (!btn) return;
      btn.style.background   = v === view ? 'rgba(0,200,255,0.12)' : 'transparent';
      btn.style.color        = v === view ? 'var(--accent)' : 'var(--muted)';
      btn.style.borderColor  = v === view ? 'rgba(0,200,255,0.3)' : 'var(--border)';
    });
    const content = document.getElementById('pv-stats-content');
    if (!content) return;
    content.innerHTML = '<div style="color:var(--muted);font-size:0.85rem;text-align:center;padding:40px 0;">Lade…</div>';
    try {
      if (view === 'flow') {
        const r = await fetch('/ha/pv/state', { cache: 'no-store' });
        if (!r.ok) throw new Error(await r.text());
        const d = await r.json();
        content.innerHTML = _renderPvFlowDiagram(d.state);
        return;
      }
      const [pvResp, energyResp] = await Promise.all([
        fetch(`/ha/pv/history?view=${view}`, { cache: 'no-store' }),
        fetch(`/ha/energy/history?view=${view}`, { cache: 'no-store' }),
      ]);
      if (!pvResp.ok) throw new Error(await pvResp.text());
      const d = await pvResp.json();
      const ed = energyResp.ok ? await energyResp.json() : null;
      const gd = _hasFeature('energy_costs') ? (ed?.sensors || []).find(s => s.role === 'grid') : null;

      const labels = d.labels || [];
      const values = d.values || [];
      const unit   = d.unit || '';
      const total  = d.total != null ? d.total : null;
      const title  = view==='today'?'Heutige Leistung (W)':view==='7days'?'Ertrag letzte 7 Tage':view==='month'?'Ertrag diesen Monat':'Jahresertrag';
      const chart  = labels.length
        ? (view === 'today' ? _svgLine(labels, values, unit, 680, 220) : _svgBar(labels, values, unit, 680, 220))
        : '<div style="color:var(--muted);text-align:center;padding:40px 0;font-size:0.85rem;">Keine Daten verfügbar</div>';
      const totalHtml = total != null
        ? `<div style="display:flex;justify-content:space-between;align-items:center;margin-top:16px;padding-top:12px;border-top:1px solid var(--border);">
             <span style="font-size:0.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.1em;">Gesamt</span>
             <span style="font-size:1.2rem;font-weight:800;color:var(--accent);">${typeof total==='number'?total.toLocaleString('de-DE',{maximumFractionDigits:1}):total} ${d.total_unit||unit}</span>
           </div>` : '';

      // ── PV-Ersparnis (wenn Backend Netz-Sensor + Tarife konfiguriert hat) ──
      let savingsHtml = '';
      if (d.savings) {
        // Wenn gd.einspeisung vorhanden (direkter HA-Energiezähler), nutzen wir
        // diesen genaueren Wert statt der approximierten Power-Integration.
        let s = { ...d.savings };
        if (view === 'today' && gd && typeof gd.einspeisung === 'number') {
          const corrFeedIn = gd.einspeisung;
          const corrSelfC = Math.max(0, (total || 0) - corrFeedIn - (s.battery_charge_kwh || 0));
          const corrSavings = Math.round(
            ((corrSelfC + (s.battery_charge_kwh || 0)) * s.grid_price_ct / 100 + corrFeedIn * s.feed_in_ct / 100) * 100
          ) / 100;
          s = { ...s, feed_in_kwh: corrFeedIn, self_consumption_kwh: corrSelfC, savings_eur: corrSavings };
        }
        const fmtKwh = v => typeof v === 'number' ? v.toLocaleString('de-DE', {maximumFractionDigits: 1}) + ' kWh' : '–';
        const fmtEur = v => typeof v === 'number' ? v.toLocaleString('de-DE', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' €' : '–';
        const fmtCt  = v => typeof v === 'number' ? v.toLocaleString('de-DE', {minimumFractionDigits: 1, maximumFractionDigits: 2}) + ' ct/kWh' : '–';
        const battCol = s.battery_charge_kwh > 0 ? `
              <div style="flex:1;text-align:center;">
                <div style="font-size:0.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:3px;">Batterie geladen</div>
                <div style="font-size:1rem;font-weight:800;color:#10b981;">${fmtKwh(s.battery_charge_kwh)}</div>
                <div style="font-size:0.6rem;color:var(--muted);">&agrave; ${fmtCt(s.grid_price_ct)}</div>
              </div>` : '';
        savingsHtml = `
          <div style="margin-top:16px;padding:14px 16px;background:rgba(0,200,100,0.08);border:1px solid rgba(0,200,100,0.22);border-radius:10px;">
            <div style="font-size:0.68rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:10px;">&#9889; Durch PV eingespart</div>
            <div style="display:flex;gap:10px;">
              <div style="flex:1;text-align:center;">
                <div style="font-size:0.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:3px;">Eigenverbrauch</div>
                <div style="font-size:1rem;font-weight:800;color:var(--success);">${fmtKwh(s.self_consumption_kwh)}</div>
                <div style="font-size:0.6rem;color:var(--muted);">&agrave; ${fmtCt(s.grid_price_ct)}</div>
              </div>
              ${battCol}
              <div style="flex:1;text-align:center;">
                <div style="font-size:0.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:3px;">Netz-Einspeisung</div>
                <div style="font-size:1rem;font-weight:800;color:var(--accent);">${fmtKwh(s.feed_in_kwh)}</div>
                <div style="font-size:0.6rem;color:var(--muted);">&agrave; ${fmtCt(s.feed_in_ct)}</div>
              </div>
              <div style="flex:1;text-align:center;">
                <div style="font-size:0.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:3px;">Ersparnis</div>
                <div style="font-size:1.2rem;font-weight:900;color:var(--success);">+${fmtEur(s.savings_eur)}</div>
              </div>
            </div>
          </div>`;
      }

      // ── Autarkie-Anzeige ──
      // Wenn der Energie-Sensor (gd) verlässliche Netz-Daten liefert, überschreiben
      // wir die Backend-Autarkie-Berechnung — analog zur Savings-Korrektur über
      // gd.einspeisung. Nötig wenn grid_id-Sensor falsche Vorzeichenkonvention hat
      // (häufig bei Balkonkraftwerken ohne bidirektionalen Netzzähler).
      let _autarkie = d.autarkie;
      if (
        view === 'today' && d.autarkie &&
        typeof gd?.einspeisung === 'number' && typeof gd?.netzbezug === 'number'
      ) {
        const corrFeedIn   = gd.einspeisung;
        const corrBattC    = (d.savings?.battery_charge_kwh) || 0;
        const corrSelfC    = Math.max(0, (total || 0) - corrFeedIn - corrBattC);
        const corrImport   = gd.netzbezug;
        const corrTotalC   = corrSelfC + corrImport;
        _autarkie = {
          ...d.autarkie,
          autarkie_pct: corrTotalC > 0 ? Math.round(corrSelfC / corrTotalC * 1000) / 10 : 0,
          self_use_pct: (total || 0) > 0 ? Math.round(corrSelfC / total * 1000) / 10 : 0,
          import_kwh: corrImport,
        };
      }
      let autarkieHtml = '';
      if (_autarkie) {
        const a = _autarkie;
        const fmtPct = v => typeof v === 'number' ? v.toLocaleString('de-DE', {maximumFractionDigits: 1}) + ' %' : '–';
        const bar = (pct, color) => {
          const w = Math.min(100, Math.max(0, pct || 0));
          return `<div style="height:5px;background:rgba(255,255,255,0.08);border-radius:3px;margin-top:5px;overflow:hidden;">
            <div style="width:${w}%;height:100%;background:${color};border-radius:3px;transition:width 0.4s;"></div>
          </div>`;
        };
        autarkieHtml = `
          <div style="margin-top:10px;padding:14px 16px;background:rgba(0,180,255,0.07);border:1px solid rgba(0,180,255,0.2);border-radius:10px;">
            <div style="font-size:0.68rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:10px;">&#9728; Autarkie</div>
            <div style="display:flex;gap:16px;">
              <div style="flex:1;">
                <div style="font-size:0.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">Autarkie</div>
                <div style="font-size:1.1rem;font-weight:800;color:var(--accent);">${fmtPct(a.autarkie_pct)}</div>
                <div style="font-size:0.6rem;color:var(--muted);margin-top:1px;">selbst versorgt</div>
                ${bar(a.autarkie_pct, 'var(--accent)')}
              </div>
              <div style="flex:1;">
                <div style="font-size:0.6rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px;">Eigenverbrauch</div>
                <div style="font-size:1.1rem;font-weight:800;color:var(--success);">${fmtPct(a.self_use_pct)}</div>
                <div style="font-size:0.6rem;color:var(--muted);margin-top:1px;">der PV genutzt</div>
                ${bar(a.self_use_pct, 'var(--success)')}
              </div>
            </div>
          </div>`;
      }

      // ── Netz-Sektion (nur wenn Gesamt-Netzbezug-Sensor konfiguriert, Erika Plus) ──
      let gridHtml = '';
      if (gd) {
        const fmtKwh = v => typeof v === 'number' ? v.toLocaleString('de-DE', {maximumFractionDigits:1}) + ' kWh' : '–';
        const fmtEur = v => typeof v === 'number' ? v.toLocaleString('de-DE', {minimumFractionDigits:2, maximumFractionDigits:2}) + ' €' : '–';
        const costs = gd.costs || null;
        const fixedCostsHtml = costs && costs.fixed_costs
          ? `<div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">
               <span style="font-size:0.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.1em;">Grundpreis &amp; Geb&uuml;hren</span>
               <span style="font-size:0.85rem;font-weight:700;color:var(--warning);">−${fmtEur(costs.fixed_costs)}</span>
             </div>`
          : '';
        const saldoHtml = costs
          ? `<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border);">
               ${fixedCostsHtml}
               <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">
                 <span style="font-size:0.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.1em;">Saldo (Erlös − Kosten)</span>
                 <span style="font-size:1.1rem;font-weight:800;color:${costs.saldo >= 0 ? 'var(--success)' : 'var(--warning)'};">${costs.saldo >= 0 ? '+' : ''}${fmtEur(costs.saldo)}</span>
               </div>
             </div>`
          : '';
        if (view === 'today') {
          gridHtml = `
            <div style="margin-top:24px;padding-top:16px;border-top:1px solid var(--border);">
              <div style="font-size:0.72rem;font-weight:700;color:var(--muted);letter-spacing:0.08em;text-transform:uppercase;margin-bottom:12px;">Netz heute</div>
              <div style="display:flex;gap:16px;">
                <div style="flex:1;background:rgba(0,255,120,0.07);border:1px solid rgba(0,255,120,0.2);border-radius:10px;padding:12px 16px;text-align:center;">
                  <div style="font-size:0.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">↑ Einspeisung</div>
                  <div style="font-size:1.2rem;font-weight:800;color:var(--success);">${fmtKwh(gd.einspeisung)}</div>
                  ${costs ? `<div style="font-size:0.7rem;color:var(--success);margin-top:4px;">≈ ${fmtEur(costs.einspeisung_value)}</div>` : ''}
                </div>
                <div style="flex:1;background:rgba(255,160,50,0.07);border:1px solid rgba(255,160,50,0.2);border-radius:10px;padding:12px 16px;text-align:center;">
                  <div style="font-size:0.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px;">↓ Netzbezug</div>
                  <div style="font-size:1.2rem;font-weight:800;color:var(--warning);">${fmtKwh(gd.netzbezug)}</div>
                  ${costs ? `<div style="font-size:0.7rem;color:var(--warning);margin-top:4px;">≈ ${fmtEur(costs.netzbezug_cost)}</div>` : ''}
                </div>
              </div>
              ${saldoHtml}
            </div>`;
        } else {
          const glabels = gd.labels || [];
          const einChart = glabels.length ? _svgBar(glabels, gd.einspeisung || [], 'kWh', 680, 160, '#00ff78') : '';
          const bezChart = glabels.length ? _svgBar(glabels, gd.netzbezug  || [], 'kWh', 680, 160, '#ffa032') : '';
          gridHtml = `
            <div style="margin-top:24px;padding-top:16px;border-top:1px solid var(--border);">
              <div style="font-size:0.72rem;font-weight:700;color:var(--success);letter-spacing:0.08em;text-transform:uppercase;margin-bottom:8px;">↑ Einspeisung</div>
              ${einChart}
              <div style="display:flex;justify-content:space-between;margin-top:6px;margin-bottom:16px;">
                <span style="font-size:0.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.1em;">Gesamt</span>
                <span style="text-align:right;">
                  <span style="font-size:1rem;font-weight:800;color:var(--success);">${fmtKwh(gd.einspeisung_total)}</span>
                  ${costs ? `<span style="display:block;font-size:0.7rem;color:var(--success);">≈ ${fmtEur(costs.einspeisung_value)}</span>` : ''}
                </span>
              </div>
              <div style="font-size:0.72rem;font-weight:700;color:var(--warning);letter-spacing:0.08em;text-transform:uppercase;margin-bottom:8px;">↓ Netzbezug</div>
              ${bezChart}
              <div style="display:flex;justify-content:space-between;margin-top:6px;">
                <span style="font-size:0.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.1em;">Gesamt</span>
                <span style="text-align:right;">
                  <span style="font-size:1rem;font-weight:800;color:var(--warning);">${fmtKwh(gd.netzbezug_total)}</span>
                  ${costs ? `<span style="display:block;font-size:0.7rem;color:var(--warning);">≈ ${fmtEur(costs.netzbezug_cost)}</span>` : ''}
                </span>
              </div>
              ${saldoHtml}
            </div>`;
        }
      }

      content.innerHTML = `
        <div style="font-size:0.72rem;font-weight:700;color:var(--muted);letter-spacing:0.08em;text-transform:uppercase;margin-bottom:12px;">${title}</div>
        ${chart}${totalHtml}${savingsHtml}${autarkieHtml}${gridHtml}`;
    } catch(e) {
      content.innerHTML = `<div style="color:var(--danger);font-size:0.85rem;text-align:center;padding:40px 0;">Fehler: ${e.message}</div>`;
    }
  }

  function openPvStats() {
    const cp = document.getElementById('center-panel');
    if (!cp) return;
    let box = document.getElementById('pv-stats-box');
    if (!box) {
      box = document.createElement('div');
      box.id = 'pv-stats-box';
      box.style.cssText = 'position:absolute;inset:0;z-index:200;background:var(--bg);display:flex;flex-direction:column;border-radius:inherit;overflow:hidden;';
      cp.style.position = 'relative';
      cp.appendChild(box);
    }
    box.style.display = 'flex';
    box.innerHTML = `<div style="width:100%;height:100%;display:flex;flex-direction:column;padding:0;">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:20px 24px 12px;">
        <div style="font-size:0.65rem;font-weight:800;letter-spacing:0.14em;color:var(--accent);text-transform:uppercase;">PV-Statistik</div>
        <button onclick="closePvStats()" style="background:none;border:1px solid var(--border);border-radius:8px;color:var(--muted);font-size:0.78rem;font-weight:700;cursor:pointer;padding:6px 14px;letter-spacing:0.05em;">SCHLIESSEN</button>
      </div>
      <div style="display:flex;gap:8px;padding:0 24px 16px;">
        ${['flow','today','7days','month','year'].map(v =>
          `<button onclick="loadPvStatsView('${v}')" id="pvtab-${v}"
            style="flex:1;padding:10px 6px;border-radius:10px;border:1px solid var(--border);background:${v===_pvStatsView?'rgba(0,200,255,0.12)':'transparent'};
            color:${v===_pvStatsView?'var(--accent)':'var(--muted)'};font-size:0.78rem;font-weight:700;cursor:pointer;transition:all 0.2s;">
            ${v==='flow'?'Live':v==='today'?'Heute':v==='7days'?'7 Tage':v==='month'?'Monat':'Jahr'}
          </button>`
        ).join('')}
      </div>
      <div id="pv-stats-content" style="flex:1;overflow-y:auto;padding:0 24px 24px;min-height:260px;">
        <div style="color:var(--muted);font-size:0.85rem;text-align:center;padding:40px 0;">Lade…</div>
      </div>
    </div>`;
    loadPvStatsView(_pvStatsView);
    clearInterval(_pvStatsRefreshInterval);
    _pvStatsRefreshInterval = setInterval(() => loadPvStatsView(_pvStatsView),
      _pvStatsView === 'flow' ? 5000 : 60000);
  }

  function closePvStats() {
    const box = document.getElementById('pv-stats-box');
    if (box) box.style.display = 'none';
    clearInterval(_pvStatsRefreshInterval);
    _pvStatsRefreshInterval = null;
  }

  // ── Registrierung ────────────────────────────────────────────
  // onclick-Handler im generierten Overlay-HTML brauchen globale Namen:
  window.loadPvStatsView = loadPvStatsView;
  window.closePvStats    = closePvStats;
  // Einstieg aus display.html (Gate prüft window._pvPlus):
  window._pvPlus = { open: openPvStats };
})();
