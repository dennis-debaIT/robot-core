/* Sync-Modul — Einkaufsliste (display.html)
 *
 * Nutzt GET/POST/PATCH/DELETE /sync/items
 * Live-Updates über SSE (/sync/items/stream) — Änderungen vom Handy landen
 * über den 3s-Fast-Sync-Loop in robot-core und werden von dort innerhalb von
 * ~200ms weitergestreamt. Der Browser reconnected den EventSource bei
 * Verbindungsabbruch automatisch (Standardverhalten, kein eigener Retry nötig).
 * Offene Einträge per Drag & Drop sortierbar (Maus + Touch).
 *
 * Render-Strategie:
 *   _renderShell() — einmalig beim Öffnen, baut statisches Gerüst (Header, Input)
 *   _renderList()  — bei jedem Update, tauscht nur Liste + Clear-Button aus
 *   → Input-Feld wird nie neu erstellt; Fokus und Tipp-Text bleiben erhalten
 */
(function () {
  'use strict';

  let _items       = [];
  let _eventSource = null;
  let _isOpen      = false;

  // ── Drag-State ──────────────────────────────────────────────────────────────
  let _dragId      = null;
  let _dragGhost   = null;
  let _dragOverId  = null;
  let _dragStartY  = 0;

  function _injectStyles() {
    if (document.getElementById('sync-drag-styles')) return;
    const s = document.createElement('style');
    s.id = 'sync-drag-styles';
    s.textContent = `
      .shopping-drag-handle {
        cursor: grab; padding: 0 8px 0 0; color: var(--color-muted, #666);
        font-size: 1.1rem; user-select: none; touch-action: none;
        flex-shrink: 0;
      }
      .shopping-item.drag-over { outline: 2px solid #00C8FF; border-radius: 6px; }
      .shopping-drag-ghost {
        position: fixed; pointer-events: none; z-index: 9999;
        opacity: 0.75; box-shadow: 0 4px 16px rgba(0,0,0,.5);
        background: var(--color-surface, #15151F);
        border-radius: 8px; padding: 10px 14px;
        color: var(--color-fg, #fff); font-size: .95rem;
        display: flex; align-items: center; gap: 8px; max-width: 340px;
      }
    `;
    document.head.appendChild(s);
  }

  function _overlay() { return document.getElementById('cal-overlay'); }

  // ── API ─────────────────────────────────────────────────────────────────────

  async function _addItem(text) {
    try {
      const r = await fetch('/sync/items', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      if (!r.ok) return;
      const item = await r.json();
      _items.push(item);
      _renderList();
    } catch {}
  }

  async function _toggleItem(id) {
    const item = _items.find(i => i.id === id);
    if (!item) return;
    try {
      const r = await fetch(`/sync/items/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checked: !item.checked }),
      });
      if (!r.ok) return;
      const updated = await r.json();
      const idx = _items.findIndex(i => i.id === id);
      if (idx !== -1) _items[idx] = updated;
      _renderList();
    } catch {}
  }

  async function _deleteItem(id) {
    try {
      const r = await fetch(`/sync/items/${id}`, { method: 'DELETE' });
      if (!r.ok) return;
      _items = _items.filter(i => i.id !== id);
      _renderList();
    } catch {}
  }

  async function _clearChecked() {
    try {
      const r = await fetch('/sync/items', { method: 'DELETE' });
      if (!r.ok) return;
      _items = _items.filter(i => !i.checked);
      _renderList();
    } catch {}
  }

  // ── Drag & Drop ─────────────────────────────────────────────────────────────

  function _dragDown(e, id) {
    e.preventDefault();
    e.stopPropagation();
    _dragId = id;
    const pt = e.touches ? e.touches[0] : e;
    _dragStartY = pt.clientY;

    // Ghost anlegen
    const txt = (_items.find(i => i.id === id) || {}).text || '';
    _dragGhost = document.createElement('div');
    _dragGhost.className = 'shopping-drag-ghost';
    _dragGhost.textContent = '⠿ ' + txt;
    _dragGhost.style.left = pt.clientX + 'px';
    _dragGhost.style.top  = pt.clientY + 'px';
    document.body.appendChild(_dragGhost);

    document.addEventListener('mousemove',  _dragMove);
    document.addEventListener('touchmove',  _dragMove, { passive: false });
    document.addEventListener('mouseup',    _dragEnd);
    document.addEventListener('touchend',   _dragEnd);
  }

  function _dragMove(e) {
    if (!_dragId) return;
    e.preventDefault();
    const pt = e.touches ? e.touches[0] : e;
    _dragGhost.style.left = (pt.clientX + 12) + 'px';
    _dragGhost.style.top  = (pt.clientY - 20) + 'px';

    // Ziel-Element ermitteln
    _dragGhost.style.display = 'none';
    const el = document.elementFromPoint(pt.clientX, pt.clientY);
    _dragGhost.style.display = '';
    const li = el ? el.closest('.shopping-item[data-id]') : null;
    const newOverId = li ? li.dataset.id : null;
    if (newOverId !== _dragOverId) {
      document.querySelectorAll('.shopping-item.drag-over').forEach(e => e.classList.remove('drag-over'));
      if (li && newOverId !== _dragId) li.classList.add('drag-over');
      _dragOverId = newOverId;
    }
  }

  function _dragEnd() {
    document.removeEventListener('mousemove',  _dragMove);
    document.removeEventListener('touchmove',  _dragMove);
    document.removeEventListener('mouseup',    _dragEnd);
    document.removeEventListener('touchend',   _dragEnd);
    if (_dragGhost) { _dragGhost.remove(); _dragGhost = null; }
    document.querySelectorAll('.shopping-item.drag-over').forEach(e => e.classList.remove('drag-over'));

    if (_dragId && _dragOverId && _dragId !== _dragOverId) {
      const open     = _items.filter(i => !i.checked);
      const fromIdx  = open.findIndex(i => i.id === _dragId);
      const toIdx    = open.findIndex(i => i.id === _dragOverId);
      if (fromIdx !== -1 && toIdx !== -1) {
        const [moved] = open.splice(fromIdx, 1);
        open.splice(toIdx, 0, moved);
        // sort_order neu setzen und in _items spiegeln
        open.forEach((item, idx) => { item.sort_order = idx; });
        _items = [...open, ..._items.filter(i => i.checked)];
        _saveOrder(open);
        _renderList();
      }
    }
    _dragId = _dragOverId = null;
  }

  function _saveOrder(orderedOpen) {
    orderedOpen.forEach((item, idx) => {
      fetch(`/sync/items/${item.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sort_order: idx }),
      }).catch(() => {});
    });
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  function _renderShell() {
    const overlay = _overlay();
    if (!overlay) return;
    overlay.innerHTML = `
      <div class="shopping-panel">
        <div class="shopping-header">
          <span class="shopping-title">🛒 Einkaufsliste</span>
          <span id="sync-clear-wrap"></span>
        </div>
        <div class="shopping-input-row">
          <input id="sync-input" class="shopping-input" type="text"
            placeholder="Artikel hinzufügen …"
            onkeydown="if(event.key==='Enter')window._sync._submitInput()"
          />
          <button class="shopping-add-btn" onclick="window._sync._submitInput()">+</button>
        </div>
        <ul id="sync-list" class="shopping-list"></ul>
        <p id="sync-empty" class="shopping-empty" style="display:none">Liste ist leer</p>
      </div>
    `;
    overlay.classList.add('active');
  }

  function _renderList() {
    if (!_isOpen) return;
    const list      = document.getElementById('sync-list');
    const emptyMsg  = document.getElementById('sync-empty');
    const clearWrap = document.getElementById('sync-clear-wrap');
    if (!list) return;

    const open    = _items.filter(i => !i.checked);
    const done    = _items.filter(i => i.checked);
    const hasDone = done.length > 0;

    list.innerHTML = open.map(i => _itemHtml(i, false)).join('')
      + (hasDone ? '<li class="shopping-divider">Erledigt</li>' + done.map(i => _itemHtml(i, true)).join('') : '');

    if (emptyMsg)  emptyMsg.style.display  = _items.length === 0 ? '' : 'none';
    if (clearWrap) clearWrap.innerHTML = hasDone
      ? `<button class="shopping-clear-btn" onclick="window._sync._clearChecked()">Erledigte löschen (${done.length})</button>`
      : '';
  }

  function _itemHtml(item, isDone) {
    const cls = isDone ? 'shopping-item checked' : 'shopping-item';
    const txt = item.text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const handle = isDone ? '' :
      `<span class="shopping-drag-handle"
         onmousedown="event.stopPropagation();window._sync._dragDown(event,'${item.id}')"
         ontouchstart="event.stopPropagation();window._sync._dragDown(event,'${item.id}')">⠿</span>`;
    return `
      <li class="${cls}" data-id="${item.id}" onclick="window._sync._toggleItem('${item.id}')">
        ${handle}
        <span class="shopping-check">${isDone ? '✓' : ''}</span>
        <span class="shopping-text">${txt}</span>
        <button class="shopping-delete-btn"
          onclick="event.stopPropagation();window._sync._deleteItem('${item.id}')">✕</button>
      </li>`;
  }

  function _submitInput() {
    const input = document.getElementById('sync-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    _addItem(text);
  }

  // ── Lifecycle ────────────────────────────────────────────────────────────────

  function _connectStream() {
    if (_eventSource) return;
    _eventSource = new EventSource('/sync/items/stream');
    _eventSource.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        _items = data.items || [];
        _renderList();
      } catch {}
    };
    // EventSource reconnected bei Verbindungsabbruch automatisch (Browser-Standard).
  }

  function _disconnectStream() {
    if (_eventSource) { _eventSource.close(); _eventSource = null; }
  }

  function open() {
    _injectStyles();
    _isOpen = true;
    _renderShell();
    _connectStream();
  }

  function close() {
    _isOpen = false;
    _disconnectStream();
    const overlay = _overlay();
    if (overlay) { overlay.classList.remove('active'); overlay.innerHTML = ''; }
  }

  window._sync = { open, close, _toggleItem, _deleteItem, _clearChecked, _submitInput, _dragDown };
})();
