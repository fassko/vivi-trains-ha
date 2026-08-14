/**
 * Vivi Trains Card — Lovelace custom card
 * Shows next departures from a configured Vivi train station.
 *
 * Installation:
 *   1. Install the Vivi Trains integration and restart Home Assistant.
 *   2. Add resource in Lovelace: /vivi_trains_frontend/vivi-trains-card.js
 *   3. Use card type: custom:vivi-trains-card
 *
 * Card config example:
 *   type: custom:vivi-trains-card
 *   entity: sensor.vivi_carnikava_next_departure
 *   title: Carnikava → Rīga        # optional override
 *   max_departures: 5              # optional, default 5
 *   direction: towards_riga        # optional: all, towards_riga, from_riga
 *   show_route_color: true         # optional, default true
 */

class ViviTrainsCard extends HTMLElement {
  constructor() {
    super();
    this._pageIndex = 0;
    this.attachShadow({ mode: 'open' });
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('Please define an entity (sensor.vivi_*_next_departure)');
    }
    this._config = {
      max_departures: 5,
      direction: 'all',
      show_route_color: true,
      ...config,
    };
    this._config.direction = this._normalizeDirection(this._config.direction);
    this._config.show_route_color = this._normalizeBoolean(this._config.show_route_color);
    this._pageIndex = 0;
  }

  getCardSize() {
    return 4;
  }

  _render() {
    if (!this._hass || !this._config) return;

    const entityId = this._config.entity;
    const stateObj = this._hass.states[entityId];

    const shadow = this.shadowRoot;

    if (!stateObj) {
      shadow.innerHTML = `
        <style>${this._styles()}</style>
        <ha-card class="vivi-card">
          <div class="header">
            <span class="icon">🚂</span>
            <span class="title">Vivi Trains</span>
          </div>
          <div class="unavailable">Entity not found: ${entityId}</div>
        </ha-card>`;
      return;
    }

    const attrs = stateObj.attributes || {};
    const stationName = attrs.station_name || entityId;
    const title = this._config.title || stationName;
    const allDepartures = attrs.next_departures || [];
    const filteredDepartures = this._filterDepartures(allDepartures);
    const pageSize = this._pageSize();
    const pageCount = Math.max(1, Math.ceil(filteredDepartures.length / pageSize));
    this._pageIndex = Math.max(0, Math.min(this._pageIndex, pageCount - 1));
    const startIndex = this._pageIndex * pageSize;
    const departures = filteredDepartures.slice(startIndex, startIndex + pageSize);
    const updatedAt = attrs.updated_at ? new Date(attrs.updated_at).toLocaleTimeString() : '';

    const rows = departures.length === 0
      ? `<div class="no-trains">${this._escHtml(this._emptyMessage())}</div>`
      : departures.map((dep, i) => this._renderRow(dep, startIndex === 0 && i === 0)).join('');

    shadow.innerHTML = `
      <style>${this._styles()}</style>
      <ha-card class="vivi-card">
        <div class="header">
          <span class="icon">🚂</span>
          <span class="title">${this._escHtml(title)}</span>
          <span class="updated">Updated ${updatedAt}</span>
        </div>
        <div class="table-header">
          <span class="col-time">Departure</span>
          <span class="col-min">Min</span>
          <span class="col-dest">Destination</span>
          <span class="col-days">Days</span>
        </div>
        <div class="rows">${rows}</div>
        ${this._renderFooter(filteredDepartures.length, pageSize)}
      </ha-card>`;

    this._attachPaginationEvents();
  }

  _renderRow(dep, isNext) {
    const colorDot = this._config.show_route_color
      ? `<span class="color-dot" style="background:${this._routeColor(dep.route_color)}"></span>`
      : '';

    const minText = dep.minutes_until === 0
      ? '<span class="now-badge">NOW</span>'
      : dep.minutes_until === 1
        ? '1 min'
        : `${dep.minutes_until} min`;

    const rowClass = isNext ? 'row row-next' : 'row';

    return `
      <div class="${rowClass}">
        <span class="col-time">
          ${colorDot}
          ${this._escHtml(dep.time || '')}
        </span>
        <span class="col-min">${minText}</span>
        <span class="col-dest">${this._escHtml(dep.destination || '—')}</span>
        <span class="col-days">${this._escHtml(dep.service_days || '')}</span>
      </div>`;
  }

  _renderFooter(totalDepartures, pageSize) {
    const hasPages = totalDepartures > pageSize;
    if (!hasPages) {
      return `
        <div class="footer footer-single">
          <a href="https://vivi.lv" target="_blank" rel="noopener">vivi.lv</a>
        </div>`;
    }

    const pageCount = Math.ceil(totalDepartures / pageSize);
    const pageNumber = this._pageIndex + 1;
    const previousDisabled = this._pageIndex === 0 ? 'disabled' : '';
    const nextDisabled = this._pageIndex >= pageCount - 1 ? 'disabled' : '';

    return `
      <div class="footer footer-paged">
        <a href="https://vivi.lv" target="_blank" rel="noopener">vivi.lv</a>
        <div class="pager" aria-label="Departure pages">
          <button class="pager-button" data-page-action="previous" ${previousDisabled}>Previous</button>
          <span class="pager-count">${pageNumber}/${pageCount}</span>
          <button class="pager-button" data-page-action="next" ${nextDisabled}>Next</button>
        </div>
      </div>`;
  }

  _styles() {
    return `
      :host {
        --vivi-yellow: #F8DB22;
        --vivi-card-bg: var(--ha-card-background, var(--card-background-color, #fff));
        --vivi-border: var(--ha-card-border-color, var(--divider-color, #e0e0e0));
        --vivi-text: var(--primary-text-color, #212121);
        --vivi-muted: var(--secondary-text-color, #727272);
        --vivi-hover-bg: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
        --vivi-next-bg: rgba(248, 219, 34, 0.08);
        --vivi-next-border: rgba(248, 219, 34, 0.35);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      }

      ha-card.vivi-card {
        background: var(--vivi-card-bg);
        border-radius: var(--ha-card-border-radius, 12px);
        overflow: hidden;
        color: var(--vivi-text);
        border: 1px solid var(--vivi-border);
      }

      .header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 14px 16px 12px;
        border-bottom: 1px solid var(--vivi-border);
      }

      .icon { font-size: 20px; }

      .title {
        font-size: 16px;
        font-weight: 600;
        color: var(--vivi-yellow);
        flex: 1;
      }

      .updated {
        font-size: 10px;
        color: var(--vivi-muted);
      }

      .table-header {
        display: grid;
        grid-template-columns: 170px 80px minmax(160px, 1fr) 70px;
        column-gap: 18px;
        padding: 8px 16px 4px;
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0;
        color: var(--vivi-muted);
        border-bottom: 1px solid var(--vivi-border);
      }

      .table-header span {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .rows { padding: 4px 0 8px; }

      .row {
        display: grid;
        grid-template-columns: 170px 80px minmax(160px, 1fr) 70px;
        column-gap: 18px;
        align-items: center;
        padding: 8px 16px;
        border-bottom: 1px solid transparent;
        transition: background 0.15s;
      }

      .row:hover { background: var(--vivi-hover-bg); }

      .row-next {
        background: var(--vivi-next-bg);
        border-left: 3px solid var(--vivi-yellow);
        padding-left: 13px;
      }

      .col-time {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 15px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
      }

      .color-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
      }

      .col-min {
        font-size: 13px;
        color: var(--vivi-muted);
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
      }

      .row-next .col-min { color: var(--vivi-yellow); font-weight: 600; }

      .now-badge {
        display: inline-block;
        background: var(--vivi-yellow);
        color: #000;
        font-size: 10px;
        font-weight: 700;
        padding: 1px 5px;
        border-radius: 4px;
        letter-spacing: 0.3px;
      }

      .col-dest {
        font-size: 13px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .col-days {
        font-size: 11px;
        color: var(--vivi-muted);
        text-align: right;
        white-space: nowrap;
      }

      @media (max-width: 520px) {
        .table-header,
        .row {
          grid-template-columns: minmax(108px, 1fr) 60px minmax(0, 1.4fr);
          column-gap: 10px;
        }

        .col-days {
          display: none;
        }
      }

      .no-trains {
        padding: 20px 16px;
        color: var(--vivi-muted);
        text-align: center;
        font-size: 13px;
      }

      .unavailable {
        padding: 16px;
        color: var(--error-color, #cf6679);
        font-size: 13px;
      }

      .footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 8px 16px;
        border-top: 1px solid var(--vivi-border);
      }

      .footer-single { justify-content: flex-end; }

      .footer a {
        font-size: 10px;
        color: var(--vivi-muted);
        text-decoration: none;
      }

      .footer a:hover { color: var(--vivi-yellow); }

      .pager {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .pager-button {
        appearance: none;
        border: 1px solid var(--vivi-border);
        border-radius: 6px;
        background: transparent;
        color: var(--primary-text-color, var(--vivi-text));
        cursor: pointer;
        font: inherit;
        font-size: 12px;
        line-height: 1;
        padding: 6px 9px;
      }

      .pager-button:hover:not(:disabled) {
        background: var(--vivi-hover-bg);
      }

      .pager-button:disabled {
        color: var(--vivi-muted);
        cursor: default;
        opacity: 0.55;
      }

      .pager-count {
        color: var(--vivi-muted);
        font-size: 11px;
        min-width: 32px;
        text-align: center;
      }
    `;
  }

  _escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  _routeColor(color) {
    const value = String(color || '').trim();
    return /^#[0-9a-fA-F]{6}$/.test(value) ? value : '#F8DB22';
  }

  _filterDepartures(departures) {
    const direction = this._config.direction;
    if (direction === 'all') {
      return departures;
    }

    return departures.filter((dep) => this._matchesDirection(dep, direction));
  }

  _attachPaginationEvents() {
    this.shadowRoot.querySelectorAll('[data-page-action]').forEach((button) => {
      button.addEventListener('click', (event) => {
        const action = event.currentTarget.dataset.pageAction;
        this._pageIndex += action === 'next' ? 1 : -1;
        this._render();
      });
    });
  }

  _pageSize() {
    const value = Number.parseInt(this._config.max_departures, 10);
    return Number.isFinite(value) && value > 0 ? value : 5;
  }

  _matchesDirection(dep, direction) {
    const parts = this._routeParts(dep.destination);
    if (parts.length < 2) {
      return false;
    }

    if (direction === 'towards_riga') {
      return parts[parts.length - 1] === 'riga';
    }

    if (direction === 'from_riga') {
      return parts[0] === 'riga';
    }

    return true;
  }

  _routeParts(destination) {
    return String(destination || '')
      .split(/\s+[-–—]\s+/)
      .map((part) => this._normalizeText(part))
      .filter(Boolean);
  }

  _normalizeDirection(direction) {
    const value = this._normalizeText(direction).replace(/[-\s]+/g, '_');

    if (['towards_riga', 'toward_riga', 'to_riga'].includes(value)) {
      return 'towards_riga';
    }

    if (value === 'from_riga') {
      return 'from_riga';
    }

    if (!value || value === 'all') {
      return 'all';
    }

    throw new Error('direction must be one of: all, towards_riga, from_riga');
  }

  _normalizeBoolean(value) {
    if (typeof value === 'boolean') {
      return value;
    }

    if (typeof value === 'string') {
      const normalized = this._normalizeText(value);
      if (['false', 'no', 'off', '0'].includes(normalized)) {
        return false;
      }
      if (['true', 'yes', 'on', '1'].includes(normalized)) {
        return true;
      }
    }

    return Boolean(value);
  }

  _normalizeText(value) {
    return String(value || '')
      .trim()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase();
  }

  _emptyMessage() {
    if (this._config.direction === 'towards_riga') {
      return 'No upcoming trains towards Rīga found.';
    }

    if (this._config.direction === 'from_riga') {
      return 'No upcoming trains from Rīga found.';
    }

    return 'No upcoming trains found.';
  }
}

customElements.define('vivi-trains-card', ViviTrainsCard);

// Register card in HA's custom card picker
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'vivi-trains-card',
  name: 'Vivi Trains Card',
  description: 'Shows next departures from a Latvian Vivi train station.',
  preview: false,
});

console.info(
  '%c VIVI-TRAINS-CARD %c v1.0.4 ',
  'background:#F8DB22;color:#000;font-weight:700;padding:2px 4px;border-radius:3px 0 0 3px',
  'background:#1c1c1e;color:#F8DB22;font-weight:700;padding:2px 4px;border-radius:0 3px 3px 0',
);
