/**
 * display-liga.js — Fußball-Liga-Modul
 *
 * Auto-Overlay (wie Turnier) + Vollansicht über das Panel-System:
 *   Links  = Liga-Auswahl + Team-Fokus  (left-content)
 *   Mitte  = Spieltag-Karten            (cal-overlay)
 *   Rechts = Tabelle mit Logos          (setPanel)
 */
(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────
  let _interval       = null;
  let _fullViewOpen   = false;
  let _kaderOpen      = false;   // Kader-Overlay aktiv → Poll überspringt Left+Center
  let _selectedCode   = null;
  let _ligaData       = null;
  let _standingsCache = {};
  let _tmProfile      = null;   // gecachtes TM-Vereinsprofil
  let _tmLoadedFor    = null;   // team_name für den _tmProfile geladen wurde

  const POLL_MS = 10_000;

  // ── Hilfsfunktionen ────────────────────────────────────────────

  function _esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function _fmtTime(utcDate) {
    if (!utcDate) return '';
    try { return new Date(utcDate).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Berlin' }); }
    catch { return ''; }
  }

  function _fmtDate(utcDate) {
    if (!utcDate) return '';
    try { return new Date(utcDate).toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit', timeZone: 'Europe/Berlin' }); }
    catch { return ''; }
  }

  function _isToday(utcDate) {
    if (!utcDate) return false;
    return new Date(utcDate).toDateString() === new Date().toDateString();
  }

  function _countdown(utcDate) {
    if (!utcDate) return '';
    const diff = new Date(utcDate) - Date.now();
    if (diff <= 0) return '';
    const h = Math.floor(diff / 3_600_000);
    const m = Math.floor((diff % 3_600_000) / 60_000);
    return h > 0 ? `in ${h}h ${m}min` : `in ${m}min`;
  }

  function _minute(score) {
    const min = score?.minute;
    if (min == null) return '';
    return score?.injuryTime ? `${min}+${score.injuryTime}'` : `${min}'`;
  }

  function _suffix(score) {
    if (score?.penalties?.home != null) return ' n.E.';
    if (score?.extraTime?.home  != null) return ' n.V.';
    return '';
  }

  function _favId() {
    return _ligaData?.favorite_team_id ? Number(_ligaData.favorite_team_id) : null;
  }

  function _isFav(match) {
    const fav = _favId();
    return fav ? (match?.homeTeam?.id === fav || match?.awayTeam?.id === fav) : false;
  }

  // ── Transfermarkt ──────────────────────────────────────────────

  const _POS_SHORT = {
    'Torwart': 'TW', 'Torhüter': 'TW',
    'Innenverteidiger': 'IV', 'Linker Verteidiger': 'LV', 'Rechter Verteidiger': 'RV',
    'Defensives Mittelfeld': 'DM', 'Zentrales Mittelfeld': 'ZM',
    'Offensives Mittelfeld': 'OM', 'Linkes Mittelfeld': 'LM', 'Rechtes Mittelfeld': 'RM',
    'Linksaußen': 'LA', 'Rechtsaußen': 'RA', 'Hängende Spitze': 'HS', 'Mittelstürmer': 'ST',
  };

  const _POS_GROUP = {
    'Torwart': 0, 'Torhüter': 0,
    'Innenverteidiger': 1, 'Linker Verteidiger': 1, 'Rechter Verteidiger': 1,
    'Defensives Mittelfeld': 2, 'Zentrales Mittelfeld': 2,
    'Offensives Mittelfeld': 2, 'Linkes Mittelfeld': 2, 'Rechtes Mittelfeld': 2,
    'Linksaußen': 3, 'Rechtsaußen': 3, 'Hängende Spitze': 3, 'Mittelstürmer': 3,
  };
  const _POS_GROUP_LABEL = ['Tor', 'Abwehr', 'Mittelfeld', 'Sturm'];

  function _posShort(pos) {
    if (!pos) return '–';
    const main = (typeof pos === 'object' ? pos.main : pos) || '';
    return _POS_SHORT[main] || main.slice(0, 3) || '–';
  }

  function _posGroup(pos) {
    if (!pos) return 99;
    const key = (typeof pos === 'object' ? pos.main : pos) || '';
    return _POS_GROUP[key] ?? 2;
  }

  function _contractYear(contract) {
    if (!contract) return '–';
    const m = String(contract).match(/\d{4}/);
    return m ? `'${m[0].slice(2)}` : '–';
  }

  function _mvParse(v) {
    if (typeof v === 'number') return v;
    if (!v) return 0;
    const m = String(v).match(/([\d,.]+)\s*(Mio\.|Tsd\.)/);
    if (!m) return 0;
    const n = parseFloat(m[1].replace(',', '.'));
    return m[2].includes('Mio') ? n * 1_000_000 : n * 1_000;
  }

  function _fmtMv(v) {
    const n = typeof v === 'number' ? v : _mvParse(v);
    if (!n) return '–';
    if (n >= 1_000_000) {
      const s = (n / 1_000_000).toFixed(1).replace('.', ',');
      return `${s.endsWith(',0') ? s.slice(0, -2) : s} Mio. €`;
    }
    if (n >= 1_000) return `${Math.round(n / 1_000)} Tsd. €`;
    return `${n} €`;
  }

  async function _loadTmProfile(teamName) {
    if (_tmLoadedFor === teamName && _tmProfile) return;
    _tmLoadedFor = teamName;
    _tmProfile = null;
    const el = document.getElementById('liga-tm-card');
    if (el) el.innerHTML = '<div style="font-size:0.72rem;color:var(--muted);">Lade Vereinsinfos…</div>';
    try {
      const r = await fetch(`/liga/tm/profile?team_name=${encodeURIComponent(teamName)}`, { cache: 'no-store' });
      if (r.ok) _tmProfile = await r.json();
    } catch {}
    _renderTmCard();
  }

  function _renderTmCard() {
    const el = document.getElementById('liga-tm-card');
    if (!el) return;
    if (!_tmProfile) {
      el.innerHTML = '';
      return;
    }
    const p = _tmProfile;
    const mv    = _fmtMv(p.currentMarketValue);
    const stad  = [p.stadiumName, p.stadiumSeats ? `${Number(p.stadiumSeats).toLocaleString('de-DE')} Plätze` : ''].filter(Boolean).join(' · ');
    const found = p.foundedOn ? `📅 ${p.foundedOn}` : '';
    const web   = p.website   ? `🌐 ${_esc(p.website).replace(/^https?:\/\//,'').replace(/\/$/,'')}` : '';
    const tel   = p.tel       ? `📞 ${_esc(p.tel)}` : '';
    const rows  = [stad ? `🏟 ${_esc(stad)}` : '', found, web, tel].filter(Boolean);
    const favName = _ligaData?.favorite_team_name || '';
    el.innerHTML = `
      <div class="liga-tm-label">Vereinsinfo · Transfermarkt</div>
      ${mv && mv !== '–' ? `<div class="liga-tm-mv">💶 Kaderwert: ${_esc(mv)}</div>` : ''}
      ${rows.map(r => `<div class="liga-tm-row">${r}</div>`).join('')}
      <button class="liga-kader-btn" onclick="window._liga._showKader()">👥 Kader anzeigen</button>`;
  }

  async function _showKader() {
    const overlay = document.getElementById('cal-overlay');
    if (!overlay) return;
    const favName = _ligaData?.favorite_team_name;
    if (!favName) return;
    _kaderOpen = true;
    overlay.innerHTML = '<div class="cal-placeholder">Lade Kader…</div>';
    overlay.classList.add('active');
    let players = [];
    try {
      const r = await fetch(`/liga/tm/players?team_name=${encodeURIComponent(favName)}`, { cache: 'no-store' });
      if (r.ok) players = (await r.json()).players || [];
    } catch {}

    // Primär: Positionsgruppe (Tor→Abwehr→Mittelfeld→Sturm), sekundär: Marktwert
    players.sort((a, b) => {
      const ga = _posGroup(a.position), gb = _posGroup(b.position);
      if (ga !== gb) return ga - gb;
      return _mvParse(b.marketValue) - _mvParse(a.marketValue);
    });

    let rows = '';
    let lastGroup = -1;
    for (const p of players) {
      const grp = _posGroup(p.position);
      if (grp !== lastGroup) {
        lastGroup = grp;
        rows += `<div class="liga-kader-section">${_POS_GROUP_LABEL[grp] ?? 'Sonstige'}</div>`;
      }
      const nat = Array.isArray(p.nationality) ? (p.nationality[0] || '–') : (p.nationality || '–');
      const pos = _posShort(p.position);
      const mv  = _fmtMv(p.marketValue);
      const bis = _contractYear(p.contract);
      const age = p.age ?? '–';
      const num = p.shirtNumber ?? '–';
      const img = p.image
        ? `<img src="${_esc(p.image)}" class="liga-kader-img" onerror="this.style.display='none'" loading="lazy">`
        : '<span class="liga-kader-img-ph"></span>';
      rows += `<div class="liga-kader-row">
        <span class="liga-kader-pos">${_esc(pos)}</span>
        <span class="liga-kader-num">${num}</span>
        <span class="liga-kader-namecell">${img}<span class="liga-kader-name" title="${_esc(p.name || '')}">${_esc(p.name || '–')}</span></span>
        <span style="color:var(--muted);">${age}</span>
        <span style="color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(nat)}</span>
        <span style="color:var(--muted);">${_esc(bis)}</span>
        <span class="liga-kader-mv">${_esc(mv)}</span>
      </div>`;
    }

    overlay.innerHTML = `
      <div class="liga-kader-wrap">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
          <div>
            <div style="font-size:0.6rem;font-weight:800;letter-spacing:0.12em;color:var(--accent);text-transform:uppercase;margin-bottom:2px;">Kader</div>
            <div style="font-size:1.05rem;font-weight:800;">${_esc(favName)}</div>
          </div>
          <button class="liga-kader-back" onclick="window._liga._backToMatchday()">← Spieltag</button>
        </div>
        ${players.length ? `
        <div class="liga-kader-hdr">
          <span>Pos</span><span>#</span><span>Name</span><span>Alt</span><span>Nation</span><span>bis</span><span>Marktwert</span>
        </div>
        <div class="liga-kader-grid">${rows}</div>` : '<div class="cal-placeholder">Keine Spieler gefunden.</div>'}
      </div>`;
  }

  // ── Event-Ticker ───────────────────────────────────────────────

  function _renderMatchEvents(goals, bookings) {
    const evs = [];
    for (const g of goals || []) {
      const min  = g.minute ? `${g.minute}'` : '';
      const name = _esc(g.scorer?.name || '');
      const team = _esc(g.team?.shortName || g.team?.name || '');
      const extra = g.type === 'OWN_GOAL' ? ' (ET)' : g.type === 'PENALTY' ? ' (FE)' : '';
      evs.push({ sort: g.minute || 0, html: `<span class="liga-ev liga-ev-goal">⚽ ${min} ${name}${extra} <span class="liga-ev-team">${team}</span></span>` });
    }
    for (const b of bookings || []) {
      const min  = b.minute ? `${b.minute}'` : '';
      const name = _esc(b.player?.name || '');
      const team = _esc(b.team?.shortName || b.team?.name || '');
      const icon = b.card === 'RED_CARD' ? '🟥' : b.card === 'YELLOW_RED_CARD' ? '🟨🟥' : '🟨';
      evs.push({ sort: b.minute || 0, html: `<span class="liga-ev liga-ev-card">${icon} ${min} ${name} <span class="liga-ev-team">${team}</span></span>` });
    }
    evs.sort((a, b) => b.sort - a.sort);
    return evs.length ? `<div class="liga-events">${evs.map(e => e.html).join('')}</div>` : '';
  }
  window._renderMatchEvents = _renderMatchEvents;

  // ── Einzel-Spielkarte ──────────────────────────────────────────

  function _crestImg(team, cls) {
    if (!team?.crest) return '';
    return `<img src="${_esc(team.crest)}" class="${cls}" onerror="this.style.display='none'" loading="lazy">`;
  }

  function _matchCard(m, compact) {
    const status   = m.status || '';
    const score    = m.score  || {};
    const ft       = score.fullTime || {};
    const ht       = score.halfTime || {};
    const isLive   = ['IN_PLAY','PAUSED'].includes(status);
    const isDone   = status === 'FINISHED';
    const isFav    = _isFav(m);
    const home     = _esc(m.homeTeam?.shortName || m.homeTeam?.name || '?');
    const away     = _esc(m.awayTeam?.shortName || m.awayTeam?.name || '?');
    const hCrest   = _crestImg(m.homeTeam, compact ? 'lcc-crest' : 'liga-match-crest');
    const aCrest   = _crestImg(m.awayTeam, compact ? 'lcc-crest' : 'liga-match-crest');
    const hg       = ft.home ?? (isDone ? 0 : null);
    const ag       = ft.away ?? (isDone ? 0 : null);
    const scoreStr = hg != null ? `${hg}${_suffix(score)}:${ag}` : '–:–';
    const min      = _minute(score);
    const time     = _fmtTime(m.utcDate);
    const cd       = _isToday(m.utcDate) && !isLive && !isDone ? _countdown(m.utcDate) : '';
    const favCls   = isFav ? ' liga-card-fav' : '';

    if (compact) {
      return `<div class="liga-card liga-card-compact${favCls}${isLive ? ' liga-card-live' : ''}">
        <span class="lcc-time">${isLive ? (min || 'LIVE') : (isDone ? 'FT' : time)}</span>
        <span class="lcc-home">${hCrest}${home}</span>
        <span class="lcc-score${isLive ? ' lcc-live' : ''}">${isLive || isDone ? scoreStr : '–'}</span>
        <span class="lcc-away">${aCrest}${away}</span>
        ${isFav ? '<span class="lcc-fav">★</span>' : ''}
      </div>`;
    }

    const htStr = ht.home != null && isLive ? `<span class="liga-ht">(${ht.home}:${ht.away} HZ)</span>` : '';
    return `<div class="liga-card${favCls}${isLive ? ' liga-card-live' : ''}${isDone ? ' liga-card-done' : ''}">
      <div class="liga-card-header">
        ${isLive
          ? `<span class="liga-badge-live">LIVE ${min}</span>`
          : isDone
            ? '<span class="liga-badge-done">Abpfiff</span>'
            : `<span class="liga-badge-time">${cd ? `${cd} · ` : ''}${time}</span>`}
      </div>
      <div class="liga-card-teams">
        <span class="liga-team${hg != null && ag != null && hg > ag ? ' liga-team-winner' : ''}">${hCrest}${home}</span>
        <span class="liga-score${isLive ? ' liga-score-live' : ''}">${isLive || isDone ? scoreStr : 'vs'}</span>
        <span class="liga-team${hg != null && ag != null && ag > hg ? ' liga-team-winner' : ''}">${aCrest}${away}</span>
      </div>
      ${htStr}
      ${isLive ? _renderMatchEvents(m.goals, m.bookings) : ''}
    </div>`;
  }

  // ── Auto-Overlay (wie Turnier) ─────────────────────────────────

  function _renderOverlay(data) {
    const overlay = document.getElementById('liga-overlay');
    if (!overlay) return;
    if (!data?.leagues?.length) { overlay.innerHTML = ''; return; }

    const allLive = data.leagues.flatMap(l => (l.live || []).map(m => ({ ...m, _league: l })));

    if (document.getElementById('tournament-overlay')?.children.length) {
      overlay.innerHTML = '';
      return;
    }

    if (!allLive.length) {
      const nextMatch = data.leagues
        .flatMap(l => (l.matches || []).filter(m => ['SCHEDULED','TIMED'].includes(m.status)).map(m => ({ ...m, _league: l })))
        .sort((a, b) => (a.utcDate || '') < (b.utcDate || '') ? -1 : 1)[0];
      if (!nextMatch) { overlay.innerHTML = ''; return; }
      const cd = _countdown(nextMatch.utcDate);
      overlay.innerHTML = `<div class="liga-overlay-next">
        <span class="liga-overlay-league">${_esc(nextMatch._league?.name || '')}</span>
        <span class="liga-overlay-teams">${_esc(nextMatch.homeTeam?.shortName || '?')} vs ${_esc(nextMatch.awayTeam?.shortName || '?')}${_isFav(nextMatch) ? ' ★' : ''}</span>
        <span class="liga-overlay-time">${cd ? `${cd} · ` : ''}${_fmtTime(nextMatch.utcDate)}</span>
      </div>`;
      return;
    }

    allLive.sort((a, b) => (_isFav(b) ? 1 : 0) - (_isFav(a) ? 1 : 0));
    const cols = allLive.length === 1 ? 1 : allLive.length <= 3 ? 2 : 3;

    if (allLive.length === 1) {
      const m = allLive[0];
      const ft = (m.score || {}).fullTime || {};
      overlay.innerHTML = `<div class="liga-overlay-single">
        <div class="liga-overlay-league-name">${_esc(m._league?.name || '')}</div>
        <div class="liga-live-badge">&#128308; LIVE ${_minute(m.score)}</div>
        <div class="liga-big-match">
          <span class="liga-big-team">${_esc(m.homeTeam?.shortName || '?')}</span>
          <span class="liga-big-score">${ft.home ?? '–'}${_suffix(m.score)} : ${ft.away ?? '–'}</span>
          <span class="liga-big-team">${_esc(m.awayTeam?.shortName || '?')}</span>
        </div>
        ${_renderMatchEvents(m.goals, m.bookings)}
      </div>`;
    } else {
      const byLeague = {};
      for (const m of allLive) {
        const key = m._league?.code || '';
        (byLeague[key] = byLeague[key] || { league: m._league, matches: [] }).matches.push(m);
      }
      let inner = `<div class="liga-overlay-multi">`;
      for (const { league, matches } of Object.values(byLeague)) {
        inner += `<div class="liga-section">
          <div class="liga-section-title">${_esc(league?.name || '')}</div>
          <div class="liga-col-grid" style="--cols:${cols}">${matches.map(m => _matchCard(m, true)).join('')}</div>
        </div>`;
      }
      overlay.innerHTML = inner + '</div>';
    }
  }

  // ── Panel-Rendering (Links / Mitte / Rechts) ───────────────────

  function _curLeague() {
    const leagues = _ligaData?.leagues || [];
    return leagues.find(l => l.code === _selectedCode) || leagues[0] || null;
  }

  function _renderLeft() {
    const leagues = _ligaData?.leagues || [];
    const lc = document.getElementById('left-content');
    const ll = document.getElementById('left-label');
    if (!lc) return;
    if (ll) ll.textContent = 'Fußball-Liga';
    lc.style.overflowY = 'auto';

    const leagueBtns = leagues.length
      ? leagues.map(l =>
          `<button class="liga-sel-btn${l.code === _selectedCode ? ' active' : ''}" onclick="window._liga._selectLeague('${l.code}')">${_esc(l.name)}</button>`
        ).join('')
      : '<div style="color:var(--muted);font-size:0.8rem;padding:8px 0;">Keine Ligen konfiguriert</div>';

    const focus   = _ligaData?.team_focus;
    const favName = _ligaData?.favorite_team_name;
    let focusHtml = '';
    if (focus && favName) {
      const form = (focus.last5 || []).map(r => {
        const cls = r.result === 'S' ? 'form-w' : r.result === 'N' ? 'form-l' : 'form-d';
        return `<span class="liga-form ${cls}">${r.result}</span>`;
      }).join('');
      const next    = focus.next_match;
      const nextStr = next
        ? `${_esc(next.home)} – ${_esc(next.away)}<br><small>${_fmtDate(next.utcDate)} ${_fmtTime(next.utcDate)}</small>`
        : 'Kein Spiel geplant';
      const table   = (_standingsCache[_selectedCode]?.table || []);
      const teamRow = table.find(r => r.team?.id === Number(_ligaData.favorite_team_id));
      const posStr  = teamRow ? `Pl. ${teamRow.position} · ${teamRow.points} Pkt` : '';
      focusHtml = `<div class="liga-focus" style="margin-top:12px;">
        <div class="liga-focus-name">${_esc(favName)}</div>
        ${posStr ? `<div class="liga-focus-pos">${posStr}</div>` : ''}
        ${form   ? `<div class="liga-focus-form">${form}</div>` : ''}
        <div class="liga-focus-next-label">Nächstes Spiel</div>
        <div class="liga-focus-next">${nextStr}</div>
      </div>`;
    }

    const tmHtml = (focus && favName)
      ? `<div id="liga-tm-card" class="liga-tm-card"></div>`
      : '';
    lc.innerHTML = `<div class="liga-sel">${leagueBtns}</div>${focusHtml}${tmHtml}`;
    if (focus && favName) _loadTmProfile(favName);
  }

  function _renderCenter() {
    const overlay = document.getElementById('cal-overlay');
    if (!overlay) return;
    const cur = _curLeague();
    if (!cur) {
      overlay.innerHTML = '<div style="color:var(--muted);text-align:center;padding:60px 0;">Keine Liga-Daten verfügbar</div>';
      overlay.classList.add('active');
      return;
    }

    const matches  = cur.matches || [];
    const matchday = cur.matchday_nr ? `${cur.matchday_nr}. Spieltag` : 'Spieltag';
    let html = `<div class="liga-matchday-title">${_esc(cur.name)} · ${matchday}</div>`;

    const groups = {};
    for (const m of matches) {
      const key = m.utcDate ? m.utcDate.slice(0, 16) : 'x';
      (groups[key] = groups[key] || []).push(m);
    }
    for (const key of Object.keys(groups).sort()) {
      const ms = groups[key];
      const isLiveGroup = ms.some(m => ['IN_PLAY','PAUSED'].includes(m.status));
      const timeLabel   = key !== 'x' ? `${_fmtDate(key + ':00Z')} · ${_fmtTime(key + ':00Z')}` : '';
      html += `<div class="liga-group${isLiveGroup ? ' liga-group-live' : ''}">
        <div class="liga-group-time">${timeLabel}</div>
        ${ms.map(m => _matchCard(m, false)).join('')}
      </div>`;
    }

    overlay.innerHTML = html;
    overlay.classList.add('active');
  }

  function _renderRight() {
    if (typeof setPanel !== 'function') return;
    const cur      = _curLeague();
    const standings = _standingsCache[cur?.code];
    const title    = cur ? `Tabelle ${cur.name}` : 'Tabelle';

    let html = '';
    if (standings?.table?.length) {
      html += `<div class="liga-table">
        <div class="liga-table-header">
          <span class="lt-pos">#</span>
          <span class="lt-crest"></span>
          <span class="lt-team">Verein</span>
          <span class="lt-num">Sp</span>
          <span class="lt-num">+/-</span>
          <span class="lt-pts">Pkt</span>
        </div>`;
      for (const row of standings.table) {
        const isFavRow = row.team?.id === Number(_ligaData?.favorite_team_id);
        const crest    = row.team?.crest
          ? `<img src="${_esc(row.team.crest)}" class="lt-crest-img" onerror="this.style.display='none'">`
          : '<span class="lt-crest"></span>';
        html += `<div class="liga-table-row${isFavRow ? ' liga-table-fav' : ''}">
          <span class="lt-pos">${row.position}</span>
          ${crest}
          <span class="lt-team">${_esc(row.team?.shortName || row.team?.name || '')}</span>
          <span class="lt-num">${row.playedGames ?? ''}</span>
          <span class="lt-num">${row.goalDifference ?? ''}</span>
          <span class="lt-pts">${row.points ?? ''}</span>
        </div>`;
      }
      html += '</div>';
    } else {
      html = '<div style="color:var(--muted);font-size:0.8rem;padding:12px 0;">Tabelle wird geladen…</div>';
    }
    setPanel('right', title, html);
  }

  // ── Standings nachladen ────────────────────────────────────────

  async function _fetchStandings(code) {
    if (_standingsCache[code]) return;
    try {
      const r = await fetch(`/liga/standings?code=${encodeURIComponent(code)}`, { cache: 'no-store' });
      if (r.ok) _standingsCache[code] = await r.json();
    } catch {}
  }

  // ── Polling ────────────────────────────────────────────────────

  async function _poll() {
    try {
      const r = await fetch('/liga/state', { cache: 'no-store' });
      if (!r.ok) return;
      _ligaData = await r.json();
      if (!_ligaData.enabled) { _clearOverlay(); return; }

      if (!_selectedCode && _ligaData.leagues?.length) {
        _selectedCode = _ligaData.leagues[0].code;
      }

      for (const l of _ligaData.leagues || []) _fetchStandings(l.code);

      _renderOverlay(_ligaData);
      if (_fullViewOpen) {
        if (!_kaderOpen) {
          _renderLeft();
          _renderCenter();
        }
        _renderRight();
      }
    } catch {}
  }

  function _clearOverlay() {
    const el = document.getElementById('liga-overlay');
    if (el) el.innerHTML = '';
  }

  // ── Öffentliche API ────────────────────────────────────────────

  function start() {
    if (_interval) return;
    _poll();
    _interval = setInterval(_poll, POLL_MS);
  }

  function stop() {
    clearInterval(_interval);
    _interval = null;
    _clearOverlay();
  }

  function openFullView() {
    _fullViewOpen = true;
    if (!_selectedCode && _ligaData?.leagues?.length) {
      _selectedCode = _ligaData.leagues[0].code;
    }
    _renderLeft();
    _renderCenter();
    _renderRight();
    // Standings für gewählte Liga nachladen und rechtes Panel neu rendern
    if (_selectedCode) {
      _fetchStandings(_selectedCode).then(_renderRight);
    }
  }

  function _backToMatchday() {
    _kaderOpen = false;
    _renderCenter();
  }

  function closeFullView() {
    _fullViewOpen = false;
    _kaderOpen   = false;
    _tmProfile   = null;
    _tmLoadedFor = null;
    const overlay = document.getElementById('cal-overlay');
    if (overlay) { overlay.classList.remove('active'); overlay.innerHTML = ''; }
    const lc = document.getElementById('left-content');
    if (lc) { lc.style.overflowY = ''; lc.innerHTML = ''; }
    const ll = document.getElementById('left-label');
    if (ll) ll.textContent = '';
    if (typeof setPanel === 'function') setPanel('right', '', '');
  }

  function _selectLeague(code) {
    _selectedCode = code;
    _standingsCache[code] = null;
    _renderLeft();
    _renderCenter();
    _fetchStandings(code).then(_renderRight);
  }

  // ── Liga-Overlay-Container ─────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    if (!document.getElementById('liga-overlay')) {
      const el = document.createElement('div');
      el.id = 'liga-overlay';
      el.className = 'liga-overlay';
      const tov = document.getElementById('tournament-overlay');
      if (tov) tov.after(el);
      else document.body.prepend(el);
    }
  });

  window._liga = { start, stop, openFullView, closeFullView, _selectLeague, _showKader, _backToMatchday };
})();
