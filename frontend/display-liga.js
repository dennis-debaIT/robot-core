/**
 * display-liga.js — Fußball-Liga-Modul
 *
 * Verhält sich wie das Turnier-Overlay: wenn ein Spieltag aktiv ist, zeigt
 * das Liga-Overlay den Spieltag automatisch an. Zusätzlich gibt es eine
 * Vollansicht (3 Panels) über den Nav-Button.
 *
 * window._liga wird von display.html als API genutzt:
 *   _liga.start()        — Polling starten (auto-Overlay)
 *   _liga.stop()         — Polling stoppen
 *   _liga.openFullView() — Vollansicht öffnen (nav-Button)
 *   _liga.closeFullView()— Vollansicht schließen
 */
(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────
  let _interval       = null;
  let _fullViewOpen   = false;
  let _selectedCode   = null;   // aktuell gewählte Liga im Full-View
  let _ligaData       = null;   // letzter /liga/state Response
  let _standingsCache = {};     // code → standings-Daten

  const POLL_MS = 10_000;

  // ── Hilfsfunktionen (geteilt mit Turnier-Overlay) ─────────────

  function _esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function _fmtTime(utcDate) {
    if (!utcDate) return '';
    try {
      const d = new Date(utcDate);
      return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Berlin' });
    } catch { return ''; }
  }

  function _fmtDate(utcDate) {
    if (!utcDate) return '';
    try {
      const d = new Date(utcDate);
      return d.toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit', timeZone: 'Europe/Berlin' });
    } catch { return ''; }
  }

  function _isToday(utcDate) {
    if (!utcDate) return false;
    const d   = new Date(utcDate);
    const now = new Date();
    return d.toDateString() === now.toDateString();
  }

  function _countdown(utcDate) {
    if (!utcDate) return '';
    const diff = new Date(utcDate) - Date.now();
    if (diff <= 0) return '';
    const h = Math.floor(diff / 3_600_000);
    const m = Math.floor((diff % 3_600_000) / 60_000);
    return h > 0 ? `in ${h}h ${m}min` : `in ${m}min`;
  }

  /** Spielminute — gleiche Logik wie Turnier-Overlay */
  function _minute(score) {
    const min = score?.minute;
    if (min == null) return '';
    const add = score?.injuryTime;
    return add ? `${min}+${add}'` : `${min}'`;
  }

  /** Ergebnis-Suffix: n.E. / n.V. */
  function _suffix(score) {
    if (score?.penalties?.home != null) return ' n.E.';
    if (score?.extraTime?.home  != null) return ' n.V.';
    return '';
  }

  /** Lieblingsverein-ID aus letztem State */
  function _favId() {
    return _ligaData?.favorite_team_id ? Number(_ligaData.favorite_team_id) : null;
  }

  function _isFav(match) {
    const fav = _favId();
    if (!fav) return false;
    return match?.homeTeam?.id === fav || match?.awayTeam?.id === fav;
  }

  // ── Event-Ticker (Tore + Karten) — geteilte Logik ─────────────
  // Wird auch vom Turnier-Overlay genutzt (window._renderMatchEvents).

  function _renderMatchEvents(goals, bookings) {
    const evs = [];
    for (const g of goals || []) {
      const min   = g.minute ? `${g.minute}'` : '';
      const name  = _esc(g.scorer?.name || '');
      const team  = _esc(g.team?.shortName || g.team?.name || '');
      const extra = g.type === 'OWN_GOAL' ? ' (ET)' : g.type === 'PENALTY' ? ' (FE)' : '';
      evs.push({ sort: g.minute || 0, html: `<span class="liga-ev liga-ev-goal">⚽ ${min} ${name}${extra} <span class="liga-ev-team">${team}</span></span>` });
    }
    for (const b of bookings || []) {
      const min   = b.minute ? `${b.minute}'` : '';
      const name  = _esc(b.player?.name || '');
      const team  = _esc(b.team?.shortName || b.team?.name || '');
      const icon  = b.card === 'RED_CARD' ? '🟥' : b.card === 'YELLOW_RED_CARD' ? '🟨🟥' : '🟨';
      evs.push({ sort: b.minute || 0, html: `<span class="liga-ev liga-ev-card">${icon} ${min} ${name} <span class="liga-ev-team">${team}</span></span>` });
    }
    evs.sort((a, b) => b.sort - a.sort);
    if (!evs.length) return '';
    return `<div class="liga-events">${evs.map(e => e.html).join('')}</div>`;
  }
  window._renderMatchEvents = _renderMatchEvents;

  // ── Einzel-Spielkarte ──────────────────────────────────────────

  function _matchCard(m, opts = {}) {
    const status  = m.status || '';
    const score   = m.score  || {};
    const ft      = score.fullTime  || {};
    const ht      = score.halfTime  || {};
    const isLive  = ['IN_PLAY', 'PAUSED'].includes(status);
    const isDone  = status === 'FINISHED';
    const isFav   = _isFav(m);
    const home    = _esc(m.homeTeam?.shortName || m.homeTeam?.name || '?');
    const away    = _esc(m.awayTeam?.shortName || m.awayTeam?.name || '?');
    const hg      = ft.home ?? (isDone ? 0 : null);
    const ag      = ft.away ?? (isDone ? 0 : null);
    const scoreStr = hg != null ? `${hg}${_suffix(score)}:${ag}` : '–:–';
    const min     = _minute(score);
    const time    = _fmtTime(m.utcDate);
    const cd      = _isToday(m.utcDate) && !isLive && !isDone ? _countdown(m.utcDate) : '';
    const favCls  = isFav ? ' liga-card-fav' : '';

    if (opts.compact) {
      // Kompakte Darstellung für Spalten-Modus
      return `<div class="liga-card liga-card-compact${favCls}${isLive ? ' liga-card-live' : ''}">
        <span class="lcc-time">${isLive ? (min || 'LIVE') : (isDone ? 'FT' : time)}</span>
        <span class="lcc-home">${home}</span>
        <span class="lcc-score${isLive ? ' lcc-live' : ''}">${isLive || isDone ? scoreStr : '–'}</span>
        <span class="lcc-away">${away}</span>
        ${isFav ? '<span class="lcc-fav">★</span>' : ''}
      </div>`;
    }

    // Normale Darstellung
    const htStr = ht.home != null && isLive ? `<span class="liga-ht">(${ht.home}:${ht.away} HZ)</span>` : '';
    return `<div class="liga-card${favCls}${isLive ? ' liga-card-live' : ''}${isDone ? ' liga-card-done' : ''}">
      <div class="liga-card-header">
        ${isLive ? `<span class="liga-badge-live">LIVE ${min}</span>` : isDone ? '<span class="liga-badge-done">Abpfiff</span>' : `<span class="liga-badge-time">${cd ? `${cd} · ` : ''}${time}</span>`}
      </div>
      <div class="liga-card-teams">
        <span class="liga-team${hg != null && ag != null && hg > ag ? ' liga-team-winner' : ''}">${home}</span>
        <span class="liga-score${isLive ? ' liga-score-live' : ''}">${isLive || isDone ? scoreStr : 'vs'}</span>
        <span class="liga-team${hg != null && ag != null && ag > hg ? ' liga-team-winner' : ''}">${away}</span>
      </div>
      ${htStr}
    </div>`;
  }

  // ── Auto-Overlay (wie Turnier) ─────────────────────────────────

  function _renderOverlay(data) {
    const overlay = document.getElementById('liga-overlay');
    if (!overlay) return;
    if (!data?.leagues?.length) { overlay.innerHTML = ''; return; }

    // Alle Live-Spiele über alle Ligen
    const allLive = data.leagues.flatMap(l => (l.live || []).map(m => ({ ...m, _league: l })));

    // Turnier hat Vorrang — wenn Turnier-Overlay aktiv, Liga-Overlay ausblenden
    if (document.getElementById('tournament-overlay')?.children.length) {
      overlay.innerHTML = '';
      return;
    }

    if (!allLive.length) {
      // Kein Live-Spiel — nächstes Spiel anzeigen (aus erster Liga mit Spielen)
      const nextMatch = data.leagues
        .flatMap(l => (l.matches || []).filter(m => ['SCHEDULED','TIMED'].includes(m.status)).map(m => ({ ...m, _league: l })))
        .sort((a, b) => (a.utcDate || '') < (b.utcDate || '') ? -1 : 1)[0];
      if (!nextMatch) { overlay.innerHTML = ''; return; }
      const cd = _countdown(nextMatch.utcDate);
      const time = _fmtTime(nextMatch.utcDate);
      const favLbl = _isFav(nextMatch) ? ' ★' : '';
      overlay.innerHTML = `<div class="liga-overlay-next">
        <span class="liga-overlay-league">${_esc(nextMatch._league?.name || '')}</span>
        <span class="liga-overlay-teams">${_esc(nextMatch.homeTeam?.shortName || '?')} vs ${_esc(nextMatch.awayTeam?.shortName || '?')}${favLbl}</span>
        <span class="liga-overlay-time">${cd ? `${cd} · ` : ''}${time}</span>
      </div>`;
      return;
    }

    // Live-Spiele — Spalten-Layout je nach Anzahl
    const cols = allLive.length === 1 ? 1 : allLive.length <= 3 ? 2 : 3;
    const isSingle = allLive.length === 1;

    // Favoritenspiel immer vorne
    allLive.sort((a, b) => (_isFav(b) ? 1 : 0) - (_isFav(a) ? 1 : 0));

    let inner = '';
    if (isSingle) {
      const m = allLive[0];
      const score = m.score || {};
      const ft = score.fullTime || {};
      const hg = ft.home ?? '–', ag = ft.away ?? '–';
      const min = _minute(score);
      const home = _esc(m.homeTeam?.shortName || m.homeTeam?.name || '?');
      const away = _esc(m.awayTeam?.shortName || m.awayTeam?.name || '?');
      inner = `<div class="liga-overlay-single">
        <div class="liga-overlay-league-name">${_esc(m._league?.name || '')}</div>
        <div class="liga-live-badge">&#128308; LIVE ${min}</div>
        <div class="liga-big-match">
          <span class="liga-big-team">${home}</span>
          <span class="liga-big-score">${hg}${_suffix(score)} : ${ag}</span>
          <span class="liga-big-team">${away}</span>
        </div>
        ${_renderMatchEvents(m.goals, m.bookings)}
      </div>`;
    } else {
      // Mehrere Live-Spiele — nach Ligen gruppieren
      const byLeague = {};
      for (const m of allLive) {
        const key = m._league?.code || '';
        (byLeague[key] = byLeague[key] || { league: m._league, matches: [] }).matches.push(m);
      }
      inner = `<div class="liga-overlay-multi" style="--liga-cols:${cols}">`;
      for (const { league, matches } of Object.values(byLeague)) {
        inner += `<div class="liga-section">
          <div class="liga-section-title">${_esc(league?.name || '')}</div>
          <div class="liga-col-grid" style="--cols:${cols}">${matches.map(m => _matchCard(m, { compact: true })).join('')}</div>
        </div>`;
      }
      inner += '</div>';
    }
    overlay.innerHTML = inner;
  }

  // ── Vollansicht ────────────────────────────────────────────────

  function _buildFullView() {
    const cp = document.getElementById('center-panel');
    if (!cp) return;
    let box = document.getElementById('liga-fullview');
    if (!box) {
      box = document.createElement('div');
      box.id = 'liga-fullview';
      box.className = 'liga-fullview';
      cp.appendChild(box);
    }
    _renderFullView(box);
    box.classList.add('active');
    _fullViewOpen = true;
  }

  function _renderFullView(box) {
    if (!_ligaData?.leagues?.length) {
      box.innerHTML = '<div style="color:var(--muted);text-align:center;padding:60px 0;">Keine Liga-Daten verfügbar</div>';
      return;
    }
    const leagues = _ligaData.leagues;
    if (!_selectedCode || !leagues.find(l => l.code === _selectedCode)) {
      _selectedCode = leagues[0].code;
    }
    const curLeague = leagues.find(l => l.code === _selectedCode) || leagues[0];

    // Linkes Panel: Liga-Selektor + Team-Fokus
    const leagueBtns = leagues.map(l =>
      `<button class="liga-sel-btn${l.code === _selectedCode ? ' active' : ''}" onclick="window._liga._selectLeague('${l.code}')">${_esc(l.name)}</button>`
    ).join('');

    const focus = _ligaData.team_focus;
    const favName = _ligaData.favorite_team_name ? _esc(_ligaData.favorite_team_name) : '';
    let focusHtml = '';
    if (focus && favName) {
      const form = (focus.last5 || []).map(r => {
        const cls = r.result === 'S' ? 'form-w' : r.result === 'N' ? 'form-l' : 'form-d';
        return `<span class="liga-form ${cls}">${r.result}</span>`;
      }).join('');
      const next = focus.next_match;
      const nextStr = next ? `${_esc(next.home)} – ${_esc(next.away)}<br><small>${_fmtDate(next.utcDate)} ${_fmtTime(next.utcDate)}</small>` : 'Kein Spiel geplant';
      // Tabellenposition aus Standings-Cache
      const table = (_standingsCache[_selectedCode]?.table || []);
      const teamRow = table.find(r => r.team?.id === Number(_ligaData.favorite_team_id));
      const posStr = teamRow ? `Pl. ${teamRow.position} · ${teamRow.points} Pkt` : '';
      focusHtml = `<div class="liga-focus">
        <div class="liga-focus-name">${favName}</div>
        ${posStr ? `<div class="liga-focus-pos">${posStr}</div>` : ''}
        ${form ? `<div class="liga-focus-form">${form}</div>` : ''}
        <div class="liga-focus-next-label">Nächstes Spiel</div>
        <div class="liga-focus-next">${nextStr}</div>
      </div>`;
    }

    // Mittleres Panel: Spieltag
    const matches = curLeague.matches || [];
    const matchday = curLeague.matchday_nr ? `${curLeague.matchday_nr}. Spieltag` : 'Spieltag';
    let centerHtml = `<div class="liga-matchday-title">${_esc(curLeague.name)} · ${matchday}</div>`;

    // Spiele nach Datum/Zeit gruppieren
    const groups = {};
    for (const m of matches) {
      const key = m.utcDate ? m.utcDate.slice(0, 16) : 'unbekannt';
      (groups[key] = groups[key] || []).push(m);
    }
    for (const key of Object.keys(groups).sort()) {
      const ms = groups[key];
      const isLiveGroup = ms.some(m => ['IN_PLAY','PAUSED'].includes(m.status));
      const timeLabel = key !== 'unbekannt' ? `${_fmtDate(key + ':00Z')} · ${_fmtTime(key + ':00Z')}` : '';
      centerHtml += `<div class="liga-group${isLiveGroup ? ' liga-group-live' : ''}">
        <div class="liga-group-time">${timeLabel}</div>
        ${ms.map(m => _matchCard(m)).join('')}
      </div>`;
    }

    // Rechtes Panel: Tabelle
    const standings = _standingsCache[_selectedCode];
    let rightHtml = `<div class="liga-table-title">Tabelle ${_esc(curLeague.name)}</div>`;
    if (standings?.table?.length) {
      rightHtml += `<div class="liga-table">
        <div class="liga-table-header">
          <span class="lt-pos">#</span>
          <span class="lt-team">Verein</span>
          <span class="lt-num">Sp</span>
          <span class="lt-num">+/-</span>
          <span class="lt-pts">Pkt</span>
        </div>`;
      for (const row of standings.table) {
        const isFavRow = row.team?.id === Number(_ligaData?.favorite_team_id);
        rightHtml += `<div class="liga-table-row${isFavRow ? ' liga-table-fav' : ''}">
          <span class="lt-pos">${row.position}</span>
          <span class="lt-team">${_esc(row.team?.shortName || row.team?.name || '')}</span>
          <span class="lt-num">${row.playedGames ?? ''}</span>
          <span class="lt-num">${row.goalDifference ?? ''}</span>
          <span class="lt-pts">${row.points ?? ''}</span>
        </div>`;
      }
      rightHtml += '</div>';
    } else {
      rightHtml += '<div style="color:var(--muted);font-size:0.8rem;padding:12px 0;">Tabelle nicht verfügbar</div>';
    }

    box.innerHTML = `
      <div class="liga-fv-left">
        <div class="liga-sel">${leagueBtns}</div>
        ${focusHtml}
      </div>
      <div class="liga-fv-center">${centerHtml}</div>
      <div class="liga-fv-right">${rightHtml}</div>`;
  }

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

      // Standings für alle Ligen im Hintergrund nachladen
      for (const l of _ligaData.leagues || []) {
        _fetchStandings(l.code);
      }

      _renderOverlay(_ligaData);
      if (_fullViewOpen) {
        const box = document.getElementById('liga-fullview');
        if (box) _renderFullView(box);
      }
    } catch {}
  }

  function _clearOverlay() {
    const overlay = document.getElementById('liga-overlay');
    if (overlay) overlay.innerHTML = '';
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
    _buildFullView();
    // Standings für aktuell gewählte Liga nachladen
    if (_selectedCode) _fetchStandings(_selectedCode);
  }

  function closeFullView() {
    const box = document.getElementById('liga-fullview');
    if (box) { box.classList.remove('active'); }
    _fullViewOpen = false;
  }

  function _selectLeague(code) {
    _selectedCode = code;
    _standingsCache[code] = null; // frisch laden
    _fetchStandings(code).then(() => {
      const box = document.getElementById('liga-fullview');
      if (box) _renderFullView(box);
    });
  }

  // ── Liga-Overlay-Container in DOM einfügen ─────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    if (!document.getElementById('liga-overlay')) {
      const el = document.createElement('div');
      el.id = 'liga-overlay';
      el.className = 'liga-overlay';
      // Direkt nach tournament-overlay einfügen
      const tov = document.getElementById('tournament-overlay');
      if (tov) tov.after(el);
      else document.body.prepend(el);
    }
  });

  window._liga = { start, stop, openFullView, closeFullView, _selectLeague };
})();
