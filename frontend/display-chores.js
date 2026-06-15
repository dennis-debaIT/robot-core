// Hausaufgaben — Erika Plus (kostenpflichtig)
//
// Linkes Panel: Aufgabenliste (admin-verwaltet). Klick → Verlauf/Statistik
// im Center-Overlay (Woche/Monat/Jahr, Personen-Totals + Balkendiagramm via
// window._svgEnergyBar aus display.html). Rechtes Panel: Personenliste aus
// dem bestehenden Personenprofile-System (/profiles) — Klick loggt eine
// Erledigung für die gerade ausgewählte Aufgabe.

(function () {
  const state = {
    tasks: [],
    persons: [],
    selectedTaskId: null,
    period: 'week',
    overallWinnerEnabled: true,
  };

  const PERIOD_LABEL = { week: 'Woche', month: 'Monat', year: 'Jahr' };

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
      state.persons = (d.items || []).map(p => ({ id: p.id, name: p.name }));
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

  async function _fetchOverallStats() {
    try {
      const r = await fetch('/chores/overall-stats', { cache: 'no-store' });
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
      return `
        <div class="vehicle-list-item${selected}" onclick="window._choresPlus.selectTask(${t.id})">
          <span style="font-size:1.15rem;flex-shrink:0;">${escapeHTML(t.icon || '🧹')}</span>
          <div style="flex:1;min-width:0;">
            <div class="vehicle-list-name">${escapeHTML(t.name)}</div>
          </div>
        </div>`;
    }).join('');
  }

  function _renderPersonList() {
    if (!state.selectedTaskId) return '<div class="cal-placeholder">Erst Aufgabe auswählen.</div>';
    if (!state.persons.length) return '<div class="cal-placeholder">Keine Personen angelegt.</div>';
    return state.persons.map(p => `
      <div class="vehicle-list-item" id="chore-person-${p.id}" onclick="window._choresPlus.logCompletion(${p.id})">
        <span style="font-size:1.15rem;flex-shrink:0;">🙋</span>
        <div style="flex:1;min-width:0;">
          <div class="vehicle-list-name">${escapeHTML(p.name)}</div>
        </div>
      </div>`).join('');
  }

  async function _renderOverallBanner() {
    if (!state.overallWinnerEnabled) return '';
    const overall = await _fetchOverallStats();
    if (!overall || !overall.leader) {
      return '<div class="chore-banner">🏆 Wochensieger: noch keine Erledigungen diese Woche.</div>';
    }
    const unit = overall.leader.count === 1 ? 'Aufgabe' : 'Aufgaben';
    return `<div class="chore-banner">🏆 Wochensieger: ${escapeHTML(overall.leader.name)} (${overall.leader.count} ${unit})</div>`;
  }

  function _renderTaskStats(stats) {
    if (!stats) return '<div class="cal-placeholder">Aufgabe nicht gefunden.</div>';
    const persons = stats.persons || [];
    const leaderHtml = stats.leader
      ? `<div class="chore-leader">🏆 Wochensieger dieser Aufgabe: ${escapeHTML(stats.leader.name)} (${stats.leader.count})</div>`
      : '<div class="chore-leader" style="color:var(--muted);">Noch keine Erledigungen in diesem Zeitraum.</div>';
    const totalsHtml = persons.length
      ? persons.map(p => `<div class="chore-total-row"><span>${escapeHTML(p.name)}</span><span>${p.count}</span></div>`).join('')
      : '';
    const labels = persons.map(p => p.name);
    const values = persons.map(p => p.count);
    const chart = labels.length
      ? window._svgEnergyBar(labels, values, 'x', 680, 160, '#00c832')
      : '<div style="color:var(--muted);text-align:center;padding:20px 0;font-size:0.85rem;">Keine Erledigungen in diesem Zeitraum</div>';

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
            <div class="vehicle-detail-title">${escapeHTML(stats.task_name)}</div>
          </div>
        </div>
        ${leaderHtml}
        ${totalsHtml ? `<div class="chore-totals">${totalsHtml}</div>` : ''}
        <div style="display:flex;align-items:center;justify-content:space-between;margin-top:8px;margin-bottom:10px;">
          <div style="font-size:0.62rem;color:var(--muted);letter-spacing:0.1em;">ERLEDIGUNGEN</div>
          <div style="display:flex;gap:10px;">${tabs}</div>
        </div>
        <div id="chore-chart-inner">${chart}</div>
      </div>`;
  }

  async function _renderCenter() {
    const overlay = document.getElementById('cal-overlay');
    if (!overlay) return;
    const banner = await _renderOverallBanner();
    if (!state.selectedTaskId) {
      overlay.innerHTML = `${banner}<div class="cal-placeholder">Aufgabe auswählen, um den Verlauf zu sehen.</div>`;
      overlay.classList.add('active');
      return;
    }
    const stats = await _fetchStats(state.selectedTaskId, state.period);
    overlay.innerHTML = banner + _renderTaskStats(stats);
    overlay.classList.add('active');
  }

  async function open() {
    await Promise.all([_loadTasks(), _loadPersons()]);
    document.getElementById('left-label').textContent = 'Hausaufgaben';
    const lc = document.getElementById('left-content');
    lc.style.overflowY = 'auto';
    lc.innerHTML = _renderTaskList();
    setPanel('right', 'Personen', _renderPersonList());
    await _renderCenter();
  }

  async function selectTask(taskId) {
    state.selectedTaskId = taskId;
    state.period = 'week';
    document.getElementById('left-content').innerHTML = _renderTaskList();
    setPanel('right', 'Personen', _renderPersonList());
    await _renderCenter();
  }

  async function showStatsTab(period) {
    if (!['week', 'month', 'year'].includes(period)) return;
    state.period = period;
    await _renderCenter();
  }

  async function logCompletion(personId) {
    if (!state.selectedTaskId) return;
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
    }
    await _renderCenter();
  }

  function close() {
    state.selectedTaskId = null;
    const overlay = document.getElementById('cal-overlay');
    if (overlay) { overlay.classList.remove('active'); overlay.innerHTML = ''; }
    const lc = document.getElementById('left-content');
    if (lc) lc.style.overflowY = '';
  }

  window._choresPlus = { open, close, selectTask, showStatsTab, logCompletion };
})();
