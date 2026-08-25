// Hausaufgaben — Erika Plus (kostenpflichtig)
//
// Linkes Panel: Aufgabenliste (admin-verwaltet). Klick → Verlauf/Statistik
// im Center-Overlay (Woche/Monat/Jahr, Personen-Totals + eigenes
// Balkendiagramm mit Personen-Farben). Rechtes Panel: Personenliste aus dem
// bestehenden Personenprofile-System (/profiles) — Klick loggt eine
// Erledigung für die gerade ausgewählte Aufgabe. Klick auf eine Person in
// den Totals/im Chart zeigt deren Erledigungen (mit Lösch-Option für
// Verklicker).

(function () {
  const state = {
    tasks: [],
    persons: [],
    selectedTaskId: null,
    selectedPersonId: null,
    period: 'week',
    overallWinnerEnabled: true,
    showingOverall: false,
    hallOfFameCache: null,
  };

  // Wird true zwischen open()/close() — verhindert, dass eine spät auflösende
  // Anfrage nach dem Wegnavigieren noch die (jetzt fremde) Ansicht überschreibt.
  let _isOpen = false;

  const PERIOD_LABEL = { week: 'Woche', month: 'Monat', year: 'Jahr' };
  const PERSON_COLORS = ['#00c8ff', '#ff6b6b', '#ffd166', '#06d6a0', '#a78bfa', '#f472b6', '#fb923c', '#94a3b8'];
  const POINTS_COLORS = ['', '#94a3b8', '#00c8ff', '#06d6a0', '#f59e0b', '#ef4444'];
  // 1=grau, 2=cyan, 3=grün, 4=amber, 5=rot — zeigt Schwierigkeitsgrad an

  function _personColor(personId) {
    return PERSON_COLORS[Math.abs(personId) % PERSON_COLORS.length];
  }

  function _pointsColor(pts) {
    return POINTS_COLORS[Math.min(Math.max(1, pts || 1), 5)] || '#94a3b8';
  }

  function _ptsBadge(pts) {
    if (!pts || pts <= 1) return '';
    const color = _pointsColor(pts);
    return `<span style="font-size:0.6rem;background:${color}22;color:${color};border:1px solid ${color}66;border-radius:999px;padding:1px 7px;margin-left:6px;font-weight:700;">${pts} Pkt</span>`;
  }

  async function _loadTasks() {
    try {
      const r = await fetch('/chores/tasks', { cache: 'no-store' });
      if (!r.ok) return;
      const d = await r.json();
      state.tasks = d.tasks || [];
      state.overallWinnerEnabled = d.overall_winner_enabled !== false;
    } catch {}
  }

  async function _loadPersons() {
    try {
      const r = await fetch('/profiles', { cache: 'no-store' });
      if (!r.ok) return;
      const d = await r.json();
      state.persons = (d.items || []).map(p => ({ id: p.id, name: p.name, gender: p.gender || null }));
    } catch {}
  }

  async function _fetchStats(taskId, period) {
    try {
      const r = await fetch(`/chores/tasks/${taskId}/stats?period=${encodeURIComponent(period)}`, { cache: 'no-store' });
      if (!r.ok) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

  async function _fetchCompletions(taskId, period, personId) {
    try {
      let url = `/chores/tasks/${taskId}/completions?period=${encodeURIComponent(period)}`;
      if (personId != null) url += `&person_id=${encodeURIComponent(personId)}`;
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) return [];
      const d = await r.json();
      return d.completions || [];
    } catch {
      return [];
    }
  }

  async function _fetchOverallStats() {
    try {
      const r = await fetch('/chores/overall-stats', { cache: 'no-store' });
      if (!r.ok) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

  async function _fetchHallOfFame() {
    try {
      const r = await fetch('/chores/hall-of-fame', { cache: 'no-store' });
      if (!r.ok) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

  function _renderTaskList() {
    if (!state.tasks.length) return '<div class="cal-placeholder">Keine Hausaufgaben angelegt.</div>';
    return state.tasks.map(t => {
      const selected = t.id === state.selectedTaskId ? ' selected' : '';
      const pts = t.points || 1;
      const pColor = _pointsColor(pts);
      const ptsDot = `<span style="width:8px;height:8px;border-radius:50%;background:${pColor};flex-shrink:0;opacity:0.85;"></span>`;
      return `
        <div class="vehicle-list-item${selected}" onclick="window._choresPlus.selectTask(${t.id})" style="border-left:3px solid ${pColor}40;">
          <span style="font-size:1.15rem;flex-shrink:0;">${escapeHTML(t.icon || '🧹')}</span>
          <div style="flex:1;min-width:0;">
            <div class="vehicle-list-name">${escapeHTML(t.name)}</div>
          </div>
          ${ptsDot}
        </div>`;
    }).join('');
  }

  function _renderPersonList() {
    if (!state.selectedTaskId) return '<div class="cal-placeholder">Erst Aufgabe auswählen.</div>';
    if (!state.persons.length) return '<div class="cal-placeholder">Keine Personen angelegt.</div>';
    return state.persons.map(p => {
      const icon = p.gender === 'm' ? '🙋‍♂️' : p.gender === 'w' ? '🙋‍♀️' : '🙋';
      return `
      <div class="vehicle-list-item" id="chore-person-${p.id}" onclick="window._choresPlus.logCompletion(${p.id})">
        <span style="font-size:1.15rem;flex-shrink:0;">${icon}</span>
        <div style="flex:1;min-width:0;">
          <div class="vehicle-list-name">${escapeHTML(p.name)}</div>
        </div>
      </div>`;
    }).join('');
  }

  async function _renderOverallBanner() {
    if (!state.overallWinnerEnabled) return '';
    const overall = await _fetchOverallStats();
    if (!overall || !overall.leader) {
      return '<div class="chore-banner">🏆 Wochensieger: noch keine Erledigungen diese Woche.</div>';
    }
    const l = overall.leader;
    const pts = l.total_points ?? l.count ?? 0;
    const unit = pts === 1 ? 'Punkt' : 'Punkte';
    return `<div class="chore-banner">🏆 Wochensieger: ${escapeHTML(l.name)} (${pts} ${unit})</div>`;
  }

  // Eigenes Balkendiagramm statt window._svgEnergyBar: Erledigungen sind
  // immer ganze Zahlen (keine Nachkommastellen auf der Achse), und jede
  // Person bekommt eine eigene Farbe (Klick → Verlauf der Person).
  function _renderChoreChart(persons) {
    if (!persons.length) {
      return '<div style="color:var(--muted);text-align:center;padding:20px 0;font-size:0.85rem;">Keine Erledigungen in diesem Zeitraum</div>';
    }
    const w = 680, h = 160;
    const pad = { t: 10, r: 8, b: 32, l: 26 };
    const cw = w - pad.l - pad.r;
    const ch = h - pad.t - pad.b;
    const maxV = Math.max(...persons.map(p => p.count), 1);
    const step = Math.max(1, Math.ceil(maxV / 4));
    const topTick = step * Math.ceil(maxV / step);
    const bw = Math.max(4, cw / persons.length * 0.5);
    const gap = cw / persons.length;

    let bars = '', lbls = '';
    persons.forEach((p, i) => {
      const bh = ch * (p.count / topTick);
      const x = pad.l + gap * i + (gap - bw) / 2;
      const y = pad.t + ch - bh;
      const color = _personColor(p.person_id);
      const selected = state.selectedPersonId === p.person_id;
      const stroke = selected ? ` stroke="var(--text)" stroke-width="2"` : '';
      bars += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, bh).toFixed(1)}"
        fill="${color}" rx="3"${stroke} style="cursor:pointer;" onclick="window._choresPlus.selectPerson(${p.person_id})"
        title="${escapeHTML(p.name)}: ${p.count}"/>`;
      lbls += `<text x="${(x + bw / 2).toFixed(1)}" y="${(h - 6).toFixed(1)}" text-anchor="middle"
        font-size="9" style="fill:var(--muted);cursor:pointer;" onclick="window._choresPlus.selectPerson(${p.person_id})">${escapeHTML(p.name)}</text>`;
    });

    let yLines = '';
    for (let v = 0; v <= topTick; v += step) {
      const y = pad.t + ch * (1 - v / topTick);
      yLines += `<line x1="${pad.l}" x2="${w - pad.r}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" style="stroke:var(--border);opacity:0.7;" stroke-width="1"/>
        <text x="${(pad.l - 3).toFixed(1)}" y="${(y + 3.5).toFixed(1)}" text-anchor="end" font-size="9" style="fill:var(--muted);">${v}</text>`;
    }

    return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;max-width:${w}px;display:block;">
      ${yLines}${bars}${lbls}
    </svg>`;
  }

  function _renderCompletionsList(completions, persons) {
    const selectedPerson = state.selectedPersonId != null
      ? persons.find(p => p.person_id === state.selectedPersonId)
      : null;
    const title = selectedPerson ? `Verlauf · ${escapeHTML(selectedPerson.name)}` : 'Letzte Erledigungen';
    const resetLink = selectedPerson
      ? `<span style="font-size:0.68rem;color:var(--accent);cursor:pointer;font-weight:700;" onclick="window._choresPlus.selectPerson(null)">Alle anzeigen</span>`
      : '';
    const header = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-top:14px;margin-bottom:8px;">
        <div style="font-size:0.62rem;color:var(--muted);letter-spacing:0.1em;">${title.toUpperCase()}</div>
        ${resetLink}
      </div>`;
    if (!completions.length) {
      return `${header}<div class="cal-placeholder">Keine Erledigungen in diesem Zeitraum.</div>`;
    }
    const rows = completions.map(c => `
      <div class="chore-recent-row">
        <span class="chore-color-dot" style="background:${_personColor(c.person_id)}"></span>
        <span style="flex:1;min-width:0;">${escapeHTML(c.name)}</span>
        <span style="color:var(--muted);font-size:0.78rem;">${escapeHTML(c.completed_at_local)}</span>
        <button class="chore-recent-del" onclick="window._choresPlus.deleteCompletion(${c.id})" title="Eintrag löschen">×</button>
      </div>`).join('');
    return `${header}<div class="chore-recent-list">${rows}</div>`;
  }

  function _renderTaskStats(stats, completions) {
    if (!stats) return '<div class="cal-placeholder">Aufgabe nicht gefunden.</div>';
    const persons = stats.persons || [];
    const taskPts = stats.task_points ?? 1;
    const ptsLabel = taskPts === 1 ? '1 Punkt' : `${taskPts} Punkte`;
    const pColor = _pointsColor(taskPts);
    const ptsBadge = `<span style="font-size:0.65rem;background:${pColor}22;color:${pColor};border:1px solid ${pColor}66;border-radius:999px;padding:1px 8px;margin-left:8px;">${ptsLabel} pro Erledigung</span>`;
    const leaderHtml = stats.leader
      ? `<div class="chore-leader">🏆 ${PERIOD_LABEL[stats.period]}: ${escapeHTML(stats.leader.name)} (${stats.leader.points_total ?? stats.leader.count} ${(stats.leader.points_total ?? stats.leader.count) === 1 ? 'Punkt' : 'Punkte'})</div>`
      : '<div class="chore-leader" style="color:var(--muted);">Noch keine Erledigungen in diesem Zeitraum.</div>';
    const totalsHtml = persons.length
      ? persons.map(p => {
          const selected = state.selectedPersonId === p.person_id;
          const pts = p.points_total ?? p.count;
          const countLabel = p.count !== pts ? ` <span style="color:var(--muted);font-size:0.72rem;">(${p.count}×)</span>` : '';
          return `<div class="chore-total-row${selected ? ' selected' : ''}" onclick="window._choresPlus.selectPerson(${p.person_id})">
            <span><span class="chore-color-dot" style="background:${_personColor(p.person_id)}"></span>${escapeHTML(p.name)}</span>
            <span>${pts} ${pts === 1 ? 'Pkt' : 'Pkt'}${countLabel}</span>
          </div>`;
        }).join('')
      : '';
    const chart = _renderChoreChart(persons);
    const completionsHtml = _renderCompletionsList(completions, persons);

    const tabs = ['week', 'month', 'year'].map(period => {
      const active = stats.period === period;
      return `<span id="chore-tab-${period}" style="font-size:0.72rem;cursor:pointer;font-weight:${active ? 800 : 400};color:${active ? 'var(--accent)' : 'var(--muted)'};"
        onclick="window._choresPlus.showStatsTab('${period}')">${PERIOD_LABEL[period]}</span>`;
    }).join('');

    return `
      <div class="vehicle-detail-wrap">
        <div class="vehicle-detail-header">
          <div>
            <div class="vehicle-detail-kicker">Hausaufgaben · Verlauf</div>
            <div class="vehicle-detail-title">${escapeHTML(stats.task_name)}${ptsBadge}</div>
          </div>
        </div>
        ${leaderHtml}
        ${totalsHtml ? `<div class="chore-totals">${totalsHtml}</div>` : ''}
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:8px;margin-bottom:10px;">
          <div style="font-size:0.62rem;color:var(--muted);letter-spacing:0.1em;">ERLEDIGUNGEN</div>
          <div style="display:flex;gap:10px;">${tabs}</div>
        </div>
        <div id="chore-chart-inner">${chart}</div>
        ${completionsHtml}
      </div>`;
  }

  async function _renderCenter() {
    const overlay = document.getElementById('cal-overlay');
    if (!overlay) return;
    const banner = await _renderOverallBanner();
    if (!_isOpen) return; // während des Ladens geschlossen/wegnavigiert
    if (!state.selectedTaskId) {
      overlay.innerHTML = `${banner}<div class="cal-placeholder">Aufgabe auswählen, um den Verlauf zu sehen.</div>`;
      overlay.classList.add('active');
      return;
    }
    const [stats, completions] = await Promise.all([
      _fetchStats(state.selectedTaskId, state.period),
      _fetchCompletions(state.selectedTaskId, state.period, state.selectedPersonId),
    ]);
    if (!_isOpen) return; // während des Ladens geschlossen/wegnavigiert
    overlay.innerHTML = banner + _renderTaskStats(stats, completions);
    overlay.classList.add('active');
  }

  async function open() {
    _isOpen = true;
    await Promise.all([_loadTasks(), _loadPersons()]);
    if (!_isOpen) return; // während des Ladens wieder geschlossen
    document.getElementById('left-label').textContent = 'Hausaufgaben';
    const lc = document.getElementById('left-content');
    lc.style.overflowY = 'auto';
    lc.innerHTML = _renderTaskList();
    const lf = document.getElementById('left-footer');
    if (lf) {
      lf.innerHTML = `
        <button class="chore-overview-btn" onclick="window._choresPlus.showOverall()">📊 Diese Woche</button>
        <button class="chore-overview-btn" onclick="window._choresPlus.showHallOfFame()">🏆 Hall of Fame</button>`;
    }
    setPanel('right', 'Personen', _renderPersonList());
    await _renderCenter();
  }

  async function selectTask(taskId) {
    state.selectedTaskId = taskId;
    state.showingOverall = false;
    state.period = 'week';
    state.selectedPersonId = null;
    document.getElementById('left-content').innerHTML = _renderTaskList();
    setPanel('right', 'Personen', _renderPersonList());
    await _renderCenter();
  }

  async function showOverall() {
    state.showingOverall = true;
    state.selectedTaskId = null;
    state.selectedPersonId = null;
    document.getElementById('left-content').innerHTML = _renderTaskList();
    setPanel('right', '', '');

    const overlay = document.getElementById('cal-overlay');
    if (!overlay) return;
    overlay.innerHTML = '<div class="cal-placeholder">Lade…</div>';
    overlay.classList.add('active');

    const overall = await _fetchOverallStats();
    if (!_isOpen) return; // während des Ladens geschlossen/wegnavigiert
    const persons = overall?.persons || [];

    let rankHtml = '';
    if (!persons.length) {
      rankHtml = '<div class="cal-placeholder">Noch keine Erledigungen diese Woche.</div>';
    } else {
      const sorted = [...persons].sort((a, b) => b.count - a.count);
      const medals = ['🥇', '🥈', '🥉'];
      rankHtml = sorted.map((p, i) => {
        const medal = medals[i] || `${i + 1}.`;
        const isLeader = overall?.leader?.person_id === p.person_id;
        const pts = p.total_points ?? p.count ?? 0;
        const compl = p.total_completions ?? p.count ?? 0;
        const ptLabel = pts === 1 ? 'Punkt' : 'Punkte';
        const sub = pts !== compl ? `<span style="font-size:0.68rem;color:var(--muted);"> · ${compl} ${compl === 1 ? 'Aufgabe' : 'Aufgaben'}</span>` : '';
        return `<div class="chore-rank-row${isLeader ? ' chore-rank-leader' : ''}" style="cursor:pointer;" onclick="window._choresPlus.showPersonDetail(${p.person_id})">
          <span class="chore-rank-pos">${medal}</span>
          <span class="chore-color-dot" style="background:${_personColor(p.person_id)}"></span>
          <span class="chore-rank-name">${escapeHTML(p.name)}</span>
          <span class="chore-rank-count">${pts} ${ptLabel}${sub}</span>
        </div>`;
      }).join('');
    }

    overlay.innerHTML = `
      <div style="font-size:0.62rem;font-weight:800;letter-spacing:0.14em;color:var(--accent);text-transform:uppercase;margin-bottom:14px;">📊 Wochenübersicht</div>
      <div class="chore-rank-list">${rankHtml}</div>`;
  }

  async function showHallOfFame() {
    state.selectedTaskId = null;
    state.selectedPersonId = null;
    state.showingOverall = false;
    document.getElementById('left-content').innerHTML = _renderTaskList();
    setPanel('right', '', '');
    const overlay = document.getElementById('cal-overlay');
    if (!overlay) return;
    overlay.innerHTML = '<div class="cal-placeholder">Lade…</div>';
    overlay.classList.add('active');

    const data = await _fetchHallOfFame();
    if (!_isOpen) return; // während des Ladens geschlossen/wegnavigiert
    state.hallOfFameCache = data;
    if (!data || !data.hall_of_fame.length) {
      overlay.innerHTML = '<div class="cal-placeholder">Noch keine abgeschlossenen Wochen — die Hall of Fame füllt sich ab nächster Woche.</div>';
      return;
    }

    const medals = ['🥇', '🥈', '🥉'];
    const rankHtml = data.hall_of_fame.map((p, i) => {
      const medal = medals[i] || `${i + 1}.`;
      const wins = p.wins;
      const wLabel = wins === 1 ? 'Sieg' : 'Siege';
      return `<div class="chore-rank-row" style="cursor:pointer;" onclick="window._choresPlus.showHallOfFamePerson(${p.person_id})">
        <span class="chore-rank-pos">${medal}</span>
        <span class="chore-color-dot" style="background:${_personColor(p.person_id)}"></span>
        <span class="chore-rank-name">${escapeHTML(p.name)}</span>
        <span class="chore-rank-count">${wins} ${wLabel}</span>
      </div>`;
    }).join('');

    overlay.innerHTML = `
      <div style="font-size:0.62rem;font-weight:800;letter-spacing:0.14em;color:var(--accent);text-transform:uppercase;margin-bottom:14px;">🏆 Hall of Fame · Alle Wochen</div>
      <div class="chore-rank-list">${rankHtml}</div>`;
  }

  async function showHallOfFamePerson(personId) {
    const overlay = document.getElementById('cal-overlay');
    if (!overlay) return;

    // Rangliste wurde gerade erst geladen (showHallOfFame()) — dieselben Daten
    // wiederverwenden statt die teure Aggregation ein zweites Mal anzustoßen.
    let data = state.hallOfFameCache;
    if (!data) {
      overlay.innerHTML = '<div class="cal-placeholder">Lade…</div>';
      data = await _fetchHallOfFame();
      if (!_isOpen) return; // während des Ladens geschlossen/wegnavigiert
      state.hallOfFameCache = data;
    }
    if (!data) { overlay.innerHTML = '<div class="cal-placeholder">Fehler beim Laden.</div>'; return; }

    const person = data.hall_of_fame.find(p => p.person_id === personId);
    if (!person) { overlay.innerHTML = '<div class="cal-placeholder">Person nicht gefunden.</div>'; return; }

    const winsLabel = person.wins === 1 ? 'Sieg' : 'Siege';
    const wonHtml = (person.won_weeks || []).map(w => `
      <div class="chore-recent-row">
        <span style="flex:1;min-width:0;font-weight:600;">${escapeHTML(w.week_label)}</span>
        <span style="color:var(--muted);font-size:0.78rem;flex-shrink:0;">${w.points} ${w.points === 1 ? 'Pkt' : 'Pkt'} · ${w.completions}×</span>
      </div>`).join('');

    overlay.innerHTML = `
      <div class="vehicle-detail-wrap">
        <div class="vehicle-detail-header">
          <div>
            <div class="vehicle-detail-kicker">Hall of Fame · ${person.wins} ${winsLabel}</div>
            <div class="vehicle-detail-title">${escapeHTML(person.name)}</div>
          </div>
          <button class="chore-back-btn" onclick="window._choresPlus.showHallOfFame()">← Rangliste</button>
        </div>
        <div class="chore-recent-list">${wonHtml || '<div class="cal-placeholder">Keine Siege.</div>'}</div>
      </div>`;
  }

  async function showPersonDetail(personId) {
    const overlay = document.getElementById('cal-overlay');
    if (!overlay) return;
    overlay.innerHTML = '<div class="cal-placeholder">Lade…</div>';
    overlay.classList.add('active');
    try {
      const r = await fetch(`/chores/persons/${personId}/completions?period=week`, { cache: 'no-store' });
      if (!r.ok) throw new Error();
      const d = await r.json();
      if (!_isOpen) return; // während des Ladens geschlossen/wegnavigiert
      const completions = d.completions || [];
      let rowsHtml;
      if (!completions.length) {
        rowsHtml = '<div class="cal-placeholder">Keine Erledigungen diese Woche.</div>';
      } else {
        rowsHtml = `<div class="chore-recent-list">${completions.map(c => `
          <div class="chore-recent-row">
            <span style="flex:1;min-width:0;font-weight:600;">${escapeHTML(c.task_name)}${_ptsBadge(c.task_points)}</span>
            <span style="color:var(--muted);font-size:0.78rem;flex-shrink:0;">${escapeHTML(c.completed_at_local)}</span>
          </div>`).join('')}</div>`;
      }
      overlay.innerHTML = `
        <div class="vehicle-detail-wrap">
          <div class="vehicle-detail-header">
            <div>
              <div class="vehicle-detail-kicker">Hausaufgaben · Diese Woche</div>
              <div class="vehicle-detail-title">${escapeHTML(d.person_name)}</div>
            </div>
            <button class="chore-back-btn" onclick="window._choresPlus.showOverall()">← Übersicht</button>
          </div>
          ${rowsHtml}
        </div>`;
    } catch {
      overlay.innerHTML = '<div class="cal-placeholder">Fehler beim Laden.</div>';
    }
  }

  async function showStatsTab(period) {
    if (!['week', 'month', 'year'].includes(period)) return;
    state.period = period;
    await _renderCenter();
  }

  async function selectPerson(personId) {
    state.selectedPersonId = state.selectedPersonId === personId ? null : personId;
    await _renderCenter();
  }

  const _choresLoggingInFlight = new Set();

  async function logCompletion(personId) {
    if (!state.selectedTaskId) return;
    // Doppel-Tap auf dem Touchscreen ignorieren, solange die vorherige
    // Anfrage für diese Person noch läuft — sonst wird eine Aufgabe doppelt
    // geloggt und verfälscht Punkte/Wochensieger.
    if (_choresLoggingInFlight.has(personId)) return;
    _choresLoggingInFlight.add(personId);
    const el = document.getElementById(`chore-person-${personId}`);
    if (el) {
      el.classList.add('chore-person-flash');
      setTimeout(() => el.classList.remove('chore-person-flash'), 400);
    }
    try {
      await fetch('/chores/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: state.selectedTaskId, person_id: personId }),
      });
    } catch {
      return;
    } finally {
      _choresLoggingInFlight.delete(personId);
    }
    await _renderCenter();
  }

  async function deleteCompletion(completionId) {
    try {
      await fetch(`/chores/completions/${completionId}`, { method: 'DELETE' });
    } catch {
      return;
    }
    await _renderCenter();
  }

  function close() {
    _isOpen = false;
    state.selectedTaskId = null;
    state.selectedPersonId = null;
    state.showingOverall = false;
    state.hallOfFameCache = null;
    const overlay = document.getElementById('cal-overlay');
    if (overlay) { overlay.classList.remove('active'); overlay.innerHTML = ''; }
    const lc = document.getElementById('left-content');
    if (lc) { lc.style.overflowY = ''; lc.innerHTML = ''; }
    const lf = document.getElementById('left-footer');
    if (lf) lf.innerHTML = '';
  }

  window._choresPlus = { open, close, selectTask, showStatsTab, selectPerson, logCompletion, deleteCompletion, showOverall, showPersonDetail, showHallOfFame, showHallOfFamePerson };
})();
