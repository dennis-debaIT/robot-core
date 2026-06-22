/* Einkaufslisten-Modul für display.html
 *
 * Nutzt GET/POST/PATCH/DELETE /shopping/items
 * Pollt alle 15 Sekunden wenn geöffnet (Änderungen von Handy sichtbar).
 */
(function () {
  'use strict';

  let _items      = [];
  let _pollTimer  = null;
  let _isOpen     = false;

  // ── DOM-Referenzen ──────────────────────────────────────────────────────

  function _overlay() { return document.getElementById('cal-overlay'); }
  function _leftContent() { return document.getElementById('left-content'); }

  // ── API ─────────────────────────────────────────────────────────────────

  async function _load() {
    try {
      const r = await fetch('/shopping/items', { cache: 'no-store' });
      if (!r.ok) return;
      const d = await r.json();
      _items = d.items || [];
      _render();
    } catch { /* offline — behalte alten Stand */ }
  }

  async function _addItem(text) {
    try {
      const r = await fetch('/shopping/items', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      if (!r.ok) return;
      const item = await r.json();
      _items.push(item);
      _render();
    } catch {}
  }

  async function _toggleItem(id) {
    const item = _items.find(i => i.id === id);
    if (!item) return;
    try {
      const r = await fetch(`/shopping/items/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checked: !item.checked }),
      });
      if (!r.ok) return;
      const updated = await r.json();
      const idx = _items.findIndex(i => i.id === id);
      if (idx !== -1) _items[idx] = updated;
      _render();
    } catch {}
  }

  async function _deleteItem(id) {
    try {
      const r = await fetch(`/shopping/items/${id}`, { method: 'DELETE' });
      if (!r.ok) return;
      _items = _items.filter(i => i.id !== id);
      _render();
    } catch {}
  }

  async function _clearChecked() {
    try {
      const r = await fetch('/shopping/items', { method: 'DELETE' });
      if (!r.ok) return;
      _items = _items.filter(i => !i.checked);
      _render();
    } catch {}
  }

  // ── Render ───────────────────────────────────────────────────────────────

  function _render() {
    const overlay = _overlay();
    if (!overlay || !_isOpen) return;

    const open   = _items.filter(i => !i.checked);
    const done   = _items.filter(i => i.checked);
    const hasDone = done.length > 0;

    overlay.innerHTML = `
      <div class="shopping-panel">
        <div class="shopping-header">
          <span class="shopping-title">🛒 Einkaufsliste</span>
          ${hasDone ? `<button class="shopping-clear-btn" onclick="window._shopping._clearChecked()">Erledigte löschen (${done.length})</button>` : ''}
        </div>
        <div class="shopping-input-row">
          <input id="shopping-input" class="shopping-input" type="text"
            placeholder="Artikel hinzufügen …"
            onkeydown="if(event.key==='Enter')window._shopping._submitInput()"
          />
          <button class="shopping-add-btn" onclick="window._shopping._submitInput()">+</button>
        </div>
        <ul class="shopping-list">
          ${open.map(i => _itemHtml(i)).join('')}
          ${hasDone ? '<li class="shopping-divider">Erledigt</li>' + done.map(i => _itemHtml(i)).join('') : ''}
        </ul>
        ${_items.length === 0 ? '<p class="shopping-empty">Liste ist leer</p>' : ''}
      </div>
    `;
    overlay.classList.add('active');
  }

  function _itemHtml(item) {
    const cls = item.checked ? 'shopping-item checked' : 'shopping-item';
    const txt = item.text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return `
      <li class="${cls}" onclick="window._shopping._toggleItem('${item.id}')">
        <span class="shopping-check">${item.checked ? '✓' : ''}</span>
        <span class="shopping-text">${txt}</span>
        <button class="shopping-delete-btn" onclick="event.stopPropagation();window._shopping._deleteItem('${item.id}')">✕</button>
      </li>`;
  }

  function _submitInput() {
    const input = document.getElementById('shopping-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    _addItem(text);
  }

  // ── Lifecycle ────────────────────────────────────────────────────────────

  function open() {
    _isOpen = true;
    _render();
    _load();
    _pollTimer = setInterval(_load, 15000);
  }

  function close() {
    _isOpen = false;
    clearInterval(_pollTimer);
    _pollTimer = null;
    const overlay = _overlay();
    if (overlay) { overlay.classList.remove('active'); overlay.innerHTML = ''; }
  }

  window._shopping = { open, close, _toggleItem, _deleteItem, _clearChecked, _submitInput };
})();
