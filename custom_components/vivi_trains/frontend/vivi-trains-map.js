/**
 * Vivi Trains Map — Lovelace custom card
 * Shows live Vivi train positions forwarded by the integration.
 *
 * Resource: /vivi_trains_frontend/vivi-trains-map.js
 *
 *   type: custom:vivi-trains-map
 *   entity: sensor.vivi_carnikava_next_departure  # optional, centers on that station
 *   height: 480
 *   zoom: 9
 */

const LATVIA_CENTER = [56.95, 24.1];
const LEAFLET_CSS = "/vivi_trains_frontend/vendor/leaflet.css";
const LEAFLET_JS = "/vivi_trains_frontend/vendor/leaflet.js";

class ViviTrainsMap extends HTMLElement {
  constructor() {
    super();
    this._trains = [];
    this._connected = false;
    this._gotSnapshot = false;
    this._centered = false;
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) {
    const height = Number.parseInt(config.height, 10);
    const zoom = Number(config.zoom);
    this._config = {
      ...config,
      height: Number.isFinite(height) && height >= 240 ? height : 480,
      zoom: Number.isFinite(zoom) ? zoom : null,
    };
    if (this._map) {
      this._applyHeight();
      this._map.invalidateSize();
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    if (!this._started) {
      this._started = true;
      this._renderShell();
      this._start();
    } else {
      this._maybeCenter();
    }
  }

  getCardSize() {
    const height = this._config ? this._config.height : 480;
    return Math.max(4, Math.ceil(height / 50));
  }

  disconnectedCallback() {
    this._clearRetry();
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
    if (this._map) {
      this._map.remove();
      this._map = null;
    }
    this._started = false;
  }

  _renderShell() {
    const height = this._config.height;
    this.shadowRoot.innerHTML = `
      <link rel="stylesheet" href="${LEAFLET_CSS}">
      <style>
        :host { display: block; }
        ha-card.vivi-map {
          position: relative;
          height: ${height}px;
          overflow: hidden;
          border-radius: var(--ha-card-border-radius, 12px);
          background: var(--ha-card-background, var(--card-background-color, #fff));
        }
        .map {
          height: 100%;
          width: 100%;
          background: #dbe7dc;
          touch-action: none;
        }
        .leaflet-bar a.vivi-home {
          display: flex;
          align-items: center;
          justify-content: center;
          line-height: 0;
        }
        .leaflet-bar a.vivi-home svg {
          display: block;
          width: 18px;
          height: 18px;
        }
        .status {
          position: absolute;
          z-index: 500;
          left: 12px;
          right: 12px;
          top: 12px;
          padding: 8px 10px;
          border-radius: 8px;
          background: var(--ha-card-background, rgba(255, 255, 255, 0.92));
          color: var(--primary-text-color, #212121);
          font-size: 13px;
          box-shadow: 0 1px 4px rgba(0, 0, 0, 0.18);
        }
        .status[hidden] { display: none; }
      </style>
      <ha-card class="vivi-map">
        <div class="map"></div>
        <div class="status">Waiting for live trains…</div>
      </ha-card>`;
  }

  _applyHeight() {
    const card = this.shadowRoot.querySelector("ha-card");
    if (card) card.style.height = `${this._config.height}px`;
  }

  async _start() {
    try {
      const leaflet = await _loadLeaflet();
      if (!this.isConnected || this._map) return;
      const container = this.shadowRoot.querySelector(".map");
      const zoom = this._config.zoom ?? (this._config.entity ? 10 : 7);
      this._map = leaflet.map(container, {
        zoomControl: true,
        scrollWheelZoom: true,
        touchZoom: true,
        doubleClickZoom: true,
        boxZoom: true,
      }).setView(LATVIA_CENTER, zoom);
      this._keepGesturesOnMap(container);
      // Home Assistant sends Referrer-Policy: no-referrer. OSM blocks those
      // tile requests, so each tile image has to name its own referrer policy.
      leaflet.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        referrerPolicy: "strict-origin-when-cross-origin",
      }).addTo(this._map);
      this._layer = leaflet.layerGroup().addTo(this._map);
      this._addHomeControl(leaflet);
      this._maybeCenter();
      requestAnimationFrame(() => this._map && this._map.invalidateSize());
      await this._subscribe();
    } catch (err) {
      this._setStatus("Live map unavailable");
      console.error("Vivi train map failed to start", err);
    }
  }

  async _subscribe() {
    this._clearRetry();
    if (!this._hass || !this._hass.connection) {
      this._setStatus("Live map unavailable");
      return;
    }
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
    try {
      const unsub = await this._hass.connection.subscribeMessage(
        (payload) => this._onSnapshot(payload),
        { type: "vivi_trains/subscribe_trains" },
      );
      this._unsub = typeof unsub === "function" ? unsub : null;
    } catch (err) {
      this._connected = false;
      this._setStatus("Live map unavailable");
      this._scheduleRetry();
    }
  }

  _onSnapshot(payload) {
    this._gotSnapshot = true;
    this._connected = Boolean(payload && payload.connected);
    this._trains = (payload && payload.trains) || [];
    this._draw();
    if (!this._connected) {
      this._setStatus("Live map unavailable");
      this._scheduleRetry();
      return;
    }
    this._clearRetry();
    this._setStatus(this._trains.length === 0 ? "No trains on the map right now" : "");
  }

  _scheduleRetry() {
    if (this._retry) return;
    this._retry = setTimeout(() => {
      this._retry = null;
      this._subscribe();
    }, 10000);
  }

  _clearRetry() {
    if (this._retry) {
      clearTimeout(this._retry);
      this._retry = null;
    }
  }

  _setStatus(text) {
    const status = this.shadowRoot && this.shadowRoot.querySelector(".status");
    if (!status) return;
    status.hidden = !text;
    status.textContent = text;
  }

  _draw() {
    if (!this._map || !window.L) return;
    this._layer.clearLayers();
    const leaflet = window.L;
    for (const train of this._trains) {
      if (!Number.isFinite(train.lat) || !Number.isFinite(train.lon)) continue;
      const color = /^#[0-9a-fA-F]{3,8}$/.test(train.color || "") ? train.color : "#F8DB22";
      if (Array.isArray(train.polyline) && train.polyline.length > 1) {
        leaflet.polyline(train.polyline, { color, weight: 3, opacity: 0.45 }).addTo(this._layer);
      }
      const marker = leaflet.circleMarker([train.lat, train.lon], {
        radius: 7,
        color: "#1c1c1e",
        weight: 1,
        fillColor: color,
        fillOpacity: 0.95,
      }).bindPopup(this._popup(train));
      marker.on("click", () => this._zoomTo(marker.getLatLng()));
      marker.addTo(this._layer);
    }
    const station = this._stationPosition();
    if (station) {
      const stationMarker = leaflet.circleMarker(station, {
        radius: 5,
        color: "#1c1c1e",
        weight: 2,
        fillColor: "#ffffff",
        fillOpacity: 1,
      }).bindTooltip(this._stationName() || "Station");
      stationMarker.on("click", () => this._zoomTo(stationMarker.getLatLng()));
      stationMarker.addTo(this._layer);
    }
  }

  _popup(train) {
    const delay = Number(train.delay) > 0 ? `+${Number(train.delay)} min` : "On time";
    const next = train.next_stop ? `<div>Next: ${_esc(train.next_stop)}</div>` : "";
    const name = train.name ? `<div>${_esc(train.name)}</div>` : "";
    return `<strong>${_esc(train.train || "Train")}</strong>${name}<div>${_esc(delay)}</div>${next}`;
  }

  _keepGesturesOnMap(container) {
    // Lovelace scrolls the dashboard on wheel and touch. Stop those events
    // after Leaflet has used them, so pinch, drag, and scroll zoom the map.
    const stop = (event) => event.stopPropagation();
    container.addEventListener("wheel", stop);
    container.addEventListener("touchstart", stop);
    container.addEventListener("touchmove", stop);
  }

  _zoomTo(latlng) {
    if (!this._map || !latlng) return;
    const zoom = Math.min(15, Math.max(this._map.getZoom() + 1, 13));
    this._map.flyTo(latlng, zoom, { duration: 0.5 });
  }

  _homeView() {
    const station = this._stationPosition();
    return {
      center: station || LATVIA_CENTER,
      zoom: this._config.zoom ?? (this._config.entity ? 10 : 7),
    };
  }

  _zoomHome() {
    if (!this._map) return;
    const home = this._homeView();
    this._map.flyTo(home.center, home.zoom, { duration: 0.5 });
  }

  _addHomeControl(leaflet) {
    const card = this;
    const HomeControl = leaflet.Control.extend({
      options: { position: "topleft" },
      onAdd() {
        const container = leaflet.DomUtil.create("div", "leaflet-bar leaflet-control");
        const button = leaflet.DomUtil.create("a", "vivi-home", container);
        button.href = "#";
        button.title = "Current location";
        button.setAttribute("role", "button");
        button.setAttribute("aria-label", "Current location");
        button.innerHTML =
          '<svg viewBox="0 0 24 24" aria-hidden="true">' +
          '<circle cx="12" cy="12" r="3" fill="currentColor"></circle>' +
          '<circle cx="12" cy="12" r="7.25" fill="none" stroke="currentColor" stroke-width="2"></circle>' +
          '<path d="M12 1.75v3.1M12 19.15V22.25M1.75 12h3.1M19.15 12H22.25" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path>' +
          "</svg>";
        leaflet.DomEvent.disableClickPropagation(container);
        leaflet.DomEvent.on(button, "click", (event) => {
          leaflet.DomEvent.preventDefault(event);
          leaflet.DomEvent.stopPropagation(event);
          card._zoomHome();
        });
        return container;
      },
    });
    new HomeControl().addTo(this._map);
  }

  _maybeCenter() {
    if (!this._map || this._centered) return;
    if (this._config.entity && !this._stationPosition()) return;
    const home = this._homeView();
    this._map.setView(home.center, home.zoom);
    this._centered = true;
  }

  _stationState() {
    if (!this._hass || !this._config.entity) return null;
    return this._hass.states[this._config.entity] || null;
  }

  _stationPosition() {
    const state = this._stationState();
    if (!state) return null;
    const lat = Number(state.attributes && state.attributes.latitude);
    const lon = Number(state.attributes && state.attributes.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    return [lat, lon];
  }

  _stationName() {
    const state = this._stationState();
    return (state && state.attributes && state.attributes.station_name) || "";
  }
}

function _esc(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (!window.__viviLeaflet) {
    window.__viviLeaflet = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = LEAFLET_JS;
      script.onload = () => (window.L ? resolve(window.L) : reject(new Error("Leaflet did not load")));
      script.onerror = () => reject(new Error("Unable to load Leaflet"));
      document.head.appendChild(script);
    });
  }
  return window.__viviLeaflet;
}

customElements.define("vivi-trains-map", ViviTrainsMap);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "vivi-trains-map",
  name: "Vivi Trains Map",
  description: "Live map of running Latvian Vivi trains.",
  preview: false,
});

console.info(
  "%c VIVI-TRAINS-MAP %c v1.2.0 ",
  "background:#F8DB22;color:#000;font-weight:700;padding:2px 4px;border-radius:3px 0 0 3px",
  "background:#1c1c1e;color:#F8DB22;font-weight:700;padding:2px 4px;border-radius:0 3px 3px 0",
);
