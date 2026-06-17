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
  let _interval        = null;
  let _fullViewOpen    = false;
  let _kaderOpen       = false;   // Kader-Overlay aktiv → Poll überspringt Left+Center
  let _kaderPlayers    = [];      // geladener + sortierter Kader für Back-Navigation
  let _selectedCode    = null;
  let _ligaData        = null;
  let _standingsCache  = {};
  let _tmProfile       = null;   // gecachtes TM-Vereinsprofil (Lieblingsverein links)
  let _tmLoadedFor     = null;   // team_name für den _tmProfile geladen wurde
  let _teamViewOpen    = false;  // Team-Detail-Overlay aktiv → Poll überspringt Center
  let _teamDetailId    = null;   // team_id der aktuell angezeigten Vereinsdetails
  let _teamDetailName  = null;   // Vereinsname für Team-Detail
  let _kaderTeamName   = null;   // null = Lieblingsverein, sonst überschriebener Name
  let _kaderBackAction = 'matchday'; // 'matchday' | 'team' — wohin zurück aus Kader

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

  // TM API liefert englische Positionsnamen — einheitliche Map für Short, Gruppe und deutschen Label
  const _TM_POS = {
    'Goalkeeper':         { short: 'TW',  group: 0, de: 'Torwart' },
    'Sweeper':            { short: 'LIB', group: 1, de: 'Libero' },
    'Centre-Back':        { short: 'IV',  group: 1, de: 'Innenverteidiger' },
    'Left-Back':          { short: 'LV',  group: 1, de: 'Linker Verteidiger' },
    'Right-Back':         { short: 'RV',  group: 1, de: 'Rechter Verteidiger' },
    'Left Wing-Back':     { short: 'LWB', group: 1, de: 'Linker Wingback' },
    'Right Wing-Back':    { short: 'RWB', group: 1, de: 'Rechter Wingback' },
    'Defensive Midfield': { short: 'DM',  group: 2, de: 'Defensives Mittelfeld' },
    'Central Midfield':   { short: 'ZM',  group: 2, de: 'Zentrales Mittelfeld' },
    'Attacking Midfield': { short: 'OM',  group: 2, de: 'Offensives Mittelfeld' },
    'Left Midfield':      { short: 'LM',  group: 2, de: 'Linkes Mittelfeld' },
    'Right Midfield':     { short: 'RM',  group: 2, de: 'Rechtes Mittelfeld' },
    'Left Winger':        { short: 'LA',  group: 3, de: 'Linksaußen' },
    'Right Winger':       { short: 'RA',  group: 3, de: 'Rechtsaußen' },
    'Second Striker':     { short: 'HS',  group: 3, de: 'Hängende Spitze' },
    'Centre-Forward':     { short: 'ST',  group: 3, de: 'Mittelstürmer' },
  };
  const _POS_GROUP_LABEL = ['Tor', 'Abwehr', 'Mittelfeld', 'Sturm'];

  function _posEntry(pos) {
    const key = (typeof pos === 'object' ? (pos.main || '') : (pos || ''));
    return _TM_POS[key] || null;
  }
  function _posShort(pos)  { const e = _posEntry(pos); return e ? e.short : (pos ? String(typeof pos === 'object' ? pos.main || '' : pos).slice(0, 3) : '–') || '–'; }
  function _posGroup(pos)  { const e = _posEntry(pos); return e ? e.group : 99; }
  function _posLabel(pos)  { const e = _posEntry(pos); return e ? e.de   : (pos ? String(typeof pos === 'object' ? pos.main || '' : pos) : '–') || '–'; }

  function _fmtDateISO(s) {
    if (!s) return '–';
    const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? `${m[3]}.${m[2]}.${m[1]}` : String(s);
  }

  function _fmtHeight(h) {
    if (!h) return '–';
    if (typeof h === 'number') {
      const wh = Math.floor(h / 100);
      const cm = h % 100;
      return `${wh},${String(cm).padStart(2, '0')} m`;
    }
    return String(h);
  }

  function _contractYear(contract) {
    if (!contract) return '–';
    const src = typeof contract === 'object' ? (contract.until || '') : String(contract);
    const m = src.match(/\d{4}/);
    return m ? `'${m[0].slice(2)}` : '–';
  }

  function _contractOptionDe(opt) {
    if (!opt) return '';
    return ({ 'Club option': 'Vereinsoption', 'Player option': 'Spieleroption', 'Mutual option': 'Beiderseitige Option', 'Buy option': 'Kaufoption' })[opt] || opt;
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

  // ── TM-Vereinsprofil (Lieblingsverein, linkes Panel) ───────────

  async function _loadTmProfile(teamName) {
    if (_tmLoadedFor === teamName && _tmProfile) {
      _renderTmCard(); // Profil bereits gecacht — in frisch gerenderten DOM-Container eintragen
      return;
    }
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
    const found = p.foundedOn ? `📅 ${_fmtDateISO(p.foundedOn)}` : '';
    const web   = p.website   ? `🌐 ${_esc(p.website).replace(/^https?:\/\//,'').replace(/\/$/,'')}` : '';
    const tel   = p.tel       ? `📞 ${_esc(p.tel)}` : '';
    const rows  = [stad ? `🏟 ${_esc(stad)}` : '', found, web, tel].filter(Boolean);
    el.innerHTML = `
      <div class="liga-tm-label">Vereinsinfo · Transfermarkt</div>
      ${mv && mv !== '–' ? `<div class="liga-tm-mv">💶 Kaderwert: ${_esc(mv)}</div>` : ''}
      ${rows.map(r => `<div class="liga-tm-row">${r}</div>`).join('')}
      <button class="liga-kader-btn" onclick="window._liga._showKader()">👥 Kader anzeigen</button>`;
  }

  // ── Kader-Ansicht ──────────────────────────────────────────────

  function _renderKaderContent() {
    const overlay = document.getElementById('cal-overlay');
    if (!overlay) return;
    const displayName = _kaderTeamName || _ligaData?.favorite_team_name || '';
    const backLabel   = _kaderBackAction === 'team' ? '← Verein' : '← Spieltag';
    const players = _kaderPlayers;
    let rows = '';
    let lastGroup = -1;
    players.forEach((p, idx) => {
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
      const num = p.shirtNumber != null ? String(p.shirtNumber).replace(/^#/, '') : '–';
      rows += `<div class="liga-kader-row" onclick="window._liga._showPlayerProfile(${idx})">
        <span class="liga-kader-pos">${_esc(pos)}</span>
        <span class="liga-kader-num">${num}</span>
        <span class="liga-kader-namecell"><span class="liga-kader-name" title="${_esc(p.name || '')}">${_esc(p.name || '–')}</span></span>
        <span style="color:var(--muted);">${age}</span>
        <span style="color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(nat)}</span>
        <span style="color:var(--muted);">${_esc(bis)}</span>
        <span class="liga-kader-mv">${_esc(mv)}</span>
      </div>`;
    });
    overlay.classList.add('active');
    overlay.innerHTML = `
      <div class="liga-kader-wrap">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
          <div>
            <div style="font-size:0.6rem;font-weight:800;letter-spacing:0.12em;color:var(--accent);text-transform:uppercase;margin-bottom:2px;">Kader</div>
            <div style="font-size:1.05rem;font-weight:800;">${_esc(displayName)}</div>
          </div>
          <button class="liga-kader-back" onclick="window._liga._backFromKader()">${backLabel}</button>
        </div>
        ${players.length ? `
        <div class="liga-kader-hdr">
          <span>Pos</span><span>#</span><span>Name</span><span>Alt</span><span>Nation</span><span>bis</span><span>Marktwert</span>
        </div>
        <div class="liga-kader-grid">${rows}</div>` : '<div class="cal-placeholder">Keine Spieler gefunden.</div>'}
      </div>`;
  }

  async function _showKader(teamNameOverride) {
    const teamName = teamNameOverride || _ligaData?.favorite_team_name;
    if (!teamName) return;
    _kaderOpen       = true;
    _kaderTeamName   = teamName;
    _kaderBackAction = teamNameOverride ? 'team' : 'matchday';
    const overlay = document.getElementById('cal-overlay');
    if (!overlay) return;
    overlay.innerHTML = '<div class="cal-placeholder">Lade Kader…</div>';
    overlay.classList.add('active');
    let players = [];
    try {
      const r = await fetch(`/liga/tm/players?team_name=${encodeURIComponent(teamName)}`, { cache: 'no-store' });
      if (r.ok) players = (await r.json()).players || [];
    } catch {}
    players.sort((a, b) => {
      const ga = _posGroup(a.position), gb = _posGroup(b.position);
      if (ga !== gb) return ga - gb;
      return _mvParse(b.marketValue) - _mvParse(a.marketValue);
    });
    _kaderPlayers = players;
    _renderKaderContent();
  }

  // ── Crest-Helfer ───────────────────────────────────────────────

  function _favCrest() {
    const favId = _favId();
    if (!favId) return '';
    for (const s of Object.values(_standingsCache)) {
      const row = (s?.table || []).find(r => r.team?.id === favId);
      if (row?.team?.crest) return row.team.crest;
    }
    return '';
  }

  function _getTeamCrest(teamId) {
    if (!teamId) return '';
    for (const s of Object.values(_standingsCache)) {
      const row = (s?.table || []).find(r => r.team?.id === teamId);
      if (row?.team?.crest) return row.team.crest;
    }
    return '';
  }

  // ── Spieler-Profil ─────────────────────────────────────────────

  function _drawPlayerCard(p, overlay) {
    const initials    = (p.name || '?').split(' ').slice(0, 2).map(w => w[0] || '').join('').toUpperCase();
    const rawPortrait = p.imageURL || p.image || '';
    const portraitSrc = rawPortrait ? `/liga/tm/img?url=${encodeURIComponent(rawPortrait)}` : '';
    const portrait    = portraitSrc
      ? `<img src="${_esc(portraitSrc)}" class="liga-player-portrait"
           onerror="this.style.display='none';this.nextElementSibling.style.display='flex'" loading="lazy">
         <div class="liga-player-portrait liga-player-portrait-ph" style="display:none">${_esc(initials)}</div>`
      : `<div class="liga-player-portrait liga-player-portrait-ph">${_esc(initials)}</div>`;

    const shirtRaw = p.shirtNumber != null ? String(p.shirtNumber).replace(/^#/, '') : '';
    const shirt    = shirtRaw ? `#${shirtRaw}` : '';

    const crest    = _getTeamCrest(_teamDetailId) || _favCrest() || p.club?.imageURL || p.club?.image || '';
    const clubName = p.club?.name || _kaderTeamName || _ligaData?.favorite_team_name || '';
    const clubHtml = clubName ? `<div class="liga-player-club">
      ${crest ? `<img src="${_esc(crest)}" onerror="this.style.display='none'">` : ''}
      <span>${_esc(clubName)}</span></div>` : '';

    const nats   = Array.isArray(p.nationality) ? p.nationality.join(', ') : (p.nationality || '');
    const pob    = p.placeOfBirth;
    const pobStr = pob ? [pob.city, pob.country].filter(Boolean).join(', ') : '';
    const dob    = _fmtDateISO(p.dateOfBirth);
    const dobStr = (dob !== '–' && p.age) ? `${dob} · ${p.age} J.` : (dob !== '–' ? dob : (p.age ? `${p.age} J.` : ''));
    const ht     = _fmtHeight(p.height);
    const wt     = p.weight ? `${p.weight} kg` : '';
    const joined = _fmtDateISO(p.joinedOn);
    const upd    = _fmtDateISO(p.lastUpdate);
    const mv     = _fmtMv(p.marketValue);

    // Vertragsdaten: nach Profil-Load stehen contractUntil/contractOption/signedFrom direkt am Player
    const rawContract     = typeof p.contract === 'object' ? p.contract : null;
    const contractUntilRaw = p.contractUntil || rawContract?.until || (typeof p.contract === 'string' ? p.contract : null);
    const contractUntilStr = contractUntilRaw ? _fmtDateISO(contractUntilRaw) : '';
    const contractOptDe   = _contractOptionDe(p.contractOption || rawContract?.option || '');
    const signedFrom      = p.signedFrom || '';

    const footDe = p.foot === 'left' ? 'Links' : p.foot === 'right' ? 'Rechts' : p.foot === 'both' ? 'Beidfüßig' : '';
    const detailRows = [
      ['Nationalität',    nats],
      ['Marktwert',       mv !== '–' ? `<span style="color:var(--success);font-weight:700;">${_esc(mv)}</span>` : ''],
      ['Geboren',         dobStr],
      ['Geburtsort',      pobStr],
      ['Größe',           ht !== '–' ? ht : ''],
      ['Fuß',             footDe],
      ['Im Verein seit',  joined !== '–' ? joined : ''],
      ['Kommt von',       signedFrom],
      ['Vertrag bis',     contractUntilStr && contractUntilStr !== '–' ? contractUntilStr : ''],
      ['Vertragsoption',  contractOptDe],
      ['Datenstand',      upd !== '–' ? upd : ''],
    ].filter(([, v]) => v)
     .map(([l, v]) => `<span class="liga-player-detail-label">${l}</span><span class="liga-player-detail-value">${v.includes('<') ? v : _esc(v)}</span>`)
     .join('');

    const backLabel    = _kaderBackAction === 'team' ? '← Verein' : '← Spieltag';
    const loadingHint  = p._profileLoaded ? '' : '<div style="font-size:0.65rem;color:var(--muted);margin-top:8px;opacity:.7;">Lade Profil…</div>';

    overlay.innerHTML = `
      <div class="liga-kader-wrap">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
          <button class="liga-kader-back" onclick="window._liga._backToKaderList()">← Kader</button>
          <button class="liga-kader-back" onclick="window._liga._backFromKader()">${backLabel}</button>
        </div>
        <div class="liga-player-card">
          <div class="liga-player-portrait-wrap">
            ${portrait}
            ${shirt ? `<div class="liga-player-shirt">${_esc(shirt)}</div>` : ''}
          </div>
          <div class="liga-player-info">
            <div class="liga-player-name">${_esc(p.name || '–')}</div>
            <div class="liga-player-pos-badge">${_esc(_posLabel(p.position))}</div>
            ${clubHtml}
            <div class="liga-player-detail-grid">${detailRows}</div>
            ${loadingHint}
          </div>
        </div>
      </div>`;
  }

  async function _showPlayerProfile(idx) {
    const p = _kaderPlayers[idx];
    if (!p) return;
    const overlay = document.getElementById('cal-overlay');
    if (!overlay) return;

    _drawPlayerCard(p, overlay);

    if (!p._profileLoaded && p.id) {
      try {
        const r = await fetch(`/liga/tm/player/${encodeURIComponent(String(p.id))}`, { cache: 'no-store' });
        if (r.ok) {
          const prof = await r.json();
          Object.assign(p, {
            _profileLoaded: true,
            imageURL:       prof.imageUrl || prof.imageURL || prof.image || prof.profileImage || p.imageURL || null,
            dateOfBirth:    prof.dateOfBirth    || p.dateOfBirth,
            age:            prof.age            ?? p.age,
            nationality:    prof.citizenship    || prof.nationality || p.nationality,
            height:         prof.height         || p.height,
            weight:         prof.weight         || p.weight,
            foot:           prof.foot           || p.foot           || null,
            placeOfBirth:   prof.placeOfBirth   || p.placeOfBirth,
            joinedOn:       prof.joinedOn       || prof.club?.joined           || p.joinedOn,
            signedFrom:     prof.signedFrom     || prof.club?.lastClubName    || p.signedFrom     || null,
            contractUntil:  prof.contractUntil  || prof.club?.contractExpires || p.contractUntil  || null,
            contractOption: prof.contractOption || prof.club?.contractOption  || p.contractOption || null,
            lastUpdate:     prof.lastUpdate     || p.lastUpdate,
            marketValue:    prof.marketValue    || p.marketValue,
            shirtNumber:    prof.shirtNumber    || p.shirtNumber,
            position:       prof.position       || p.position,
            club:           prof.club           || p.club,
          });
          if (_kaderPlayers[idx] === p && document.querySelector('.liga-player-card')) {
            _drawPlayerCard(p, overlay);
          }
        }
      } catch {}
    }
  }

  function _backToKaderList() {
    _renderKaderContent();
  }

  // ── Team-Detail-Ansicht ────────────────────────────────────────

  function _showTeamById(teamId) {
    let teamName = '', crest = '';
    for (const s of Object.values(_standingsCache)) {
      const row = (s?.table || []).find(r => r.team?.id === teamId);
      if (row) { teamName = row.team?.name || ''; crest = row.team?.crest || ''; break; }
    }
    if (!teamName) return;
    _showTeamDetail(teamId, teamName, crest);
  }

  async function _showTeamDetail(teamId, teamName, crest) {
    _teamViewOpen   = true;
    _teamDetailId   = teamId;
    _teamDetailName = teamName;
    const overlay = document.getElementById('cal-overlay');
    if (!overlay) return;
    overlay.classList.add('active');
    overlay.innerHTML = '<div class="cal-placeholder">Lade Vereinsinfos…</div>';

    const [focusRes, tmRes] = await Promise.allSettled([
      fetch(`/liga/team-detail?team_id=${teamId}`, { cache: 'no-store' }).then(r => r.ok ? r.json() : null),
      fetch(`/liga/tm/profile?team_name=${encodeURIComponent(teamName)}`, { cache: 'no-store' }).then(r => r.ok ? r.json() : null),
    ]);
    const focus     = focusRes.status === 'fulfilled' ? focusRes.value : null;
    const tmProfile = tmRes.status   === 'fulfilled' ? tmRes.value   : null;

    _renderTeamDetail(teamId, teamName, crest, focus, tmProfile);
  }

  function _renderTeamDetail(teamId, teamName, crest, focus, tmProfile) {
    const overlay = document.getElementById('cal-overlay');
    if (!overlay || !_teamViewOpen) return;

    let standRow = null;
    for (const s of Object.values(_standingsCache)) {
      const row = (s?.table || []).find(r => r.team?.id === teamId);
      if (row) { standRow = row; break; }
    }

    const crestHtml = crest
      ? `<img src="${_esc(crest)}" class="liga-td-crest" onerror="this.style.display='none'">`
      : '';

    const statsHtml = standRow ? `<div class="liga-td-stats">
      <span>Pl. <strong>${standRow.position}</strong></span>
      <span>${standRow.playedGames} Sp</span>
      <span>${standRow.points} Pkt</span>
      <span>${standRow.goalsFor}:${standRow.goalsAgainst} Tore</span>
      <span>${standRow.goalDifference >= 0 ? '+' : ''}${standRow.goalDifference} TD</span>
    </div>` : '';

    const last5Html = (focus?.last5 || []).map(r => {
      const cls = r.result === 'S' ? 'form-w' : r.result === 'N' ? 'form-l' : 'form-d';
      return `<div class="liga-td-past-match">
        <span class="liga-form ${cls}">${r.result}</span>
        <span class="liga-td-pm-teams">${_esc(r.home)} – ${_esc(r.away)}</span>
        <span class="liga-td-pm-score">${_esc(r.score || '')}</span>
        <span class="liga-td-pm-date">${r.utcDate ? _fmtDate(r.utcDate) : ''}</span>
      </div>`;
    }).join('');

    const next = focus?.next_match;
    const nextHtml = next ? `<div class="liga-td-next">
      <div class="liga-td-section-label">Nächstes Spiel</div>
      <div style="font-weight:600;">${_esc(next.home)} – ${_esc(next.away)}</div>
      <div style="color:var(--muted);font-size:0.72rem;">${_fmtDate(next.utcDate)} · ${_fmtTime(next.utcDate)}${next.competition ? ' · ' + _esc(next.competition) : ''}</div>
    </div>` : '';

    let tmHtml = '';
    if (tmProfile) {
      const mv    = _fmtMv(tmProfile.currentMarketValue);
      const stad  = [tmProfile.stadiumName, tmProfile.stadiumSeats ? `${Number(tmProfile.stadiumSeats).toLocaleString('de-DE')} Plätze` : ''].filter(Boolean).join(' · ');
      const found = tmProfile.foundedOn ? `📅 ${_fmtDateISO(tmProfile.foundedOn)}` : '';
      const web   = tmProfile.website ? `🌐 ${_esc(tmProfile.website).replace(/^https?:\/\//,'').replace(/\/$/,'')}` : '';
      const tel   = tmProfile.tel ? `📞 ${_esc(tmProfile.tel)}` : '';
      const tmRows = [
        mv && mv !== '–' ? `💶 Kaderwert: ${_esc(mv)}` : '',
        stad ? `🏟 ${_esc(stad)}` : '',
        found,
        web,
        tel,
      ].filter(Boolean);
      if (tmRows.length) tmHtml = `<div class="liga-td-divider"></div>${tmRows.map(r => `<div class="liga-tm-row">${r}</div>`).join('')}`;
    }

    overlay.classList.add('active');
    overlay.innerHTML = `
      <div class="liga-kader-wrap">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
          <button class="liga-kader-back" onclick="window._liga._backFromTeamDetail()">← Spieltag</button>
        </div>
        <div class="liga-td-header">
          ${crestHtml}
          <div style="flex:1;min-width:0;">
            <div class="liga-td-name">${_esc(teamName)}</div>
            ${statsHtml}
          </div>
        </div>
        ${last5Html ? `<div class="liga-td-section-label" style="margin:14px 0 6px;">Letzte Spiele</div><div>${last5Html}</div>` : ''}
        ${nextHtml}
        ${tmHtml}
        <div class="liga-td-divider"></div>
        <button class="liga-kader-btn" onclick="window._liga._showKaderForTeam()">👥 Kader anzeigen</button>
      </div>`;
  }

  function _backFromTeamDetail() {
    _teamViewOpen   = false;
    _teamDetailId   = null;
    _teamDetailName = null;
    _renderCenter();
  }

  function _showKaderForTeam() {
    if (!_teamDetailName) return;
    _showKader(_teamDetailName);
  }

  // ── Kader-Rücknavigation ───────────────────────────────────────

  function _backFromKader() {
    _kaderOpen = false;
    if (_kaderBackAction === 'team' && _teamViewOpen && _teamDetailId) {
      const crest = _getTeamCrest(_teamDetailId);
      _showTeamDetail(_teamDetailId, _teamDetailName, crest);
    } else {
      _teamViewOpen = false;
      _renderCenter();
    }
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

  function _scoreHtml(hg, ag, suffix, isDone, isLive, compact) {
    if (isLive || isDone) {
      if (isDone && hg != null && ag != null && hg !== ag) {
        const hCol = hg > ag ? ' style="color:var(--success)"' : '';
        const aCol = ag > hg ? ' style="color:var(--success)"' : '';
        return `<span${hCol}>${hg}</span>${suffix}:<span${aCol}>${ag}</span>`;
      }
      return hg != null ? `${hg}${suffix}:${ag}` : '–:–';
    }
    return compact ? '–' : 'vs';
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
    const suffix   = _suffix(score);
    const sc       = _scoreHtml(hg, ag, suffix, isDone, isLive, compact);
    const min      = _minute(score);
    const time     = _fmtTime(m.utcDate);
    const cd       = _isToday(m.utcDate) && !isLive && !isDone ? _countdown(m.utcDate) : '';
    const favCls   = isFav ? ' liga-card-fav' : '';

    if (compact) {
      return `<div class="liga-card liga-card-compact${favCls}${isLive ? ' liga-card-live' : ''}">
        <span class="lcc-time">${isLive ? (min || 'LIVE') : (isDone ? 'FT' : time)}</span>
        <span class="lcc-home">${hCrest}${home}</span>
        <span class="lcc-score${isLive ? ' lcc-live' : ''}">${sc}</span>
        <span class="lcc-away">${aCrest}${away}</span>
        ${isFav ? '<span class="lcc-fav">★</span>' : ''}
      </div>`;
    }

    // Nur in der Vollansicht: Klick auf Vereinsname öffnet Team-Detail
    const homeId    = m.homeTeam?.id;
    const awayId    = m.awayTeam?.id;
    const homeClick = homeId ? ` onclick="window._liga._showTeamById(${homeId})" style="cursor:pointer"` : '';
    const awayClick = awayId ? ` onclick="window._liga._showTeamById(${awayId})" style="cursor:pointer"` : '';
    const htStr     = ht.home != null && isLive ? `<span class="liga-ht">(${ht.home}:${ht.away} HZ)</span>` : '';
    return `<div class="liga-card${favCls}${isLive ? ' liga-card-live' : ''}${isDone ? ' liga-card-done' : ''}">
      <div class="liga-card-header">
        ${isLive
          ? `<span class="liga-badge-live">LIVE ${min}</span>`
          : isDone
            ? '<span class="liga-badge-done">Abpfiff</span>'
            : `<span class="liga-badge-time">${cd ? `${cd} · ` : ''}${time}</span>`}
      </div>
      <div class="liga-card-teams">
        <span class="liga-team${hg != null && ag != null && hg > ag ? ' liga-team-winner' : ''}"${homeClick}>${hCrest}${home}</span>
        <span class="liga-score${isLive ? ' liga-score-live' : ''}">${sc}</span>
        <span class="liga-team${hg != null && ag != null && ag > hg ? ' liga-team-winner' : ''}"${awayClick}>${aCrest}${away}</span>
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
    const cur       = _curLeague();
    const standings = _standingsCache[cur?.code];
    const title     = cur ? `Tabelle ${cur.name}` : 'Tabelle';

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
        const isFavRow    = row.team?.id === Number(_ligaData?.favorite_team_id);
        const teamClick   = row.team?.id ? ` onclick="window._liga._showTeamById(${row.team.id})" style="cursor:pointer"` : '';
        const crest       = row.team?.crest
          ? `<img src="${_esc(row.team.crest)}" class="lt-crest-img" onerror="this.style.display='none'">`
          : '<span class="lt-crest"></span>';
        html += `<div class="liga-table-row${isFavRow ? ' liga-table-fav' : ''}"${teamClick}>
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
        if (!_kaderOpen && !_teamViewOpen) {
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
    if (_selectedCode) {
      _fetchStandings(_selectedCode).then(_renderRight);
    }
  }

  function closeFullView() {
    _fullViewOpen    = false;
    _kaderOpen       = false;
    _teamViewOpen    = false;
    _teamDetailId    = null;
    _teamDetailName  = null;
    _kaderTeamName   = null;
    _kaderBackAction = 'matchday';
    _tmProfile       = null;
    _tmLoadedFor     = null;
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

  window._liga = {
    start, stop, openFullView, closeFullView,
    _selectLeague,
    _showKader,
    _backFromKader,
    _backToMatchday: _backFromKader, // Alias für alte onclick-Referenzen
    _showPlayerProfile, _backToKaderList,
    _showTeamById, _backFromTeamDetail, _showKaderForTeam,
  };
})();
