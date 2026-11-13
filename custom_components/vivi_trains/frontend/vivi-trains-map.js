/**
 * Vivi Trains Map — Lovelace custom card
 * Shows live Vivi train positions forwarded by the integration.
 *
 * On Home Assistant 2026.9 and newer the base map comes from the Map tiles
 * integration: MapLibre draws the vector style when the browser can, and
 * Leaflet draws the proxied raster tiles when it cannot. Older installs keep
 * OpenStreetMap raster tiles.
 *
 * Resource: /vivi_trains_frontend/vivi-trains-map.js
 *
 *   type: custom:vivi-trains-map
 *   entity: sensor.vivi_carnikava_next_departure  # optional, centers on that station
 *   height: 480
 *   zoom: 9
 *   theme: auto                                 # auto, light, or dark
 */

const LATVIA_CENTER = [56.95, 24.1];
const LEAFLET_CSS = "/vivi_trains_frontend/vendor/leaflet.css";
const LEAFLET_JS = "/vivi_trains_frontend/vendor/leaflet.js";
const MAPLIBRE_CSS = "/vivi_trains_frontend/vendor/maplibre-gl.css";
const MAPLIBRE_JS = "/vivi_trains_frontend/vendor/maplibre-gl.js";
const MAP_TILES_PATH = "/api/map_tiles";
const TOKEN_HEADER = "X-Map-Tiles-Token";
const TOKEN_REFRESH_MS = 20 * 60 * 1000;
const TILE_RECOVERY_MS = 30 * 1000;
const STYLE_URLS = {
  light: "/static/map/light.json",
  dark: "/static/map/dark.json",
};
const PROXY_RASTER = `${MAP_TILES_PATH}/raster/{z}/{x}/{y}.png?token=`;
const OSM_RASTER = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const HOME_ICON =
  '<svg viewBox="0 0 24 24" aria-hidden="true">' +
  '<circle cx="12" cy="12" r="3" fill="currentColor"></circle>' +
  '<circle cx="12" cy="12" r="7.25" fill="none" stroke="currentColor" stroke-width="2"></circle>' +
  '<path d="M12 1.75v3.1M12 19.15V22.25M1.75 12h3.1M19.15 12H22.25" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path>' +
  "</svg>";

const _styleCache = new Map();
let _mapToken;
let _tokenRequest;
let _tokenTimer;
let _tokenConnection;
const _tokenListeners = new Set();

class ViviTrainsMap extends HTMLElement {
  constructor() {
    super();
    this._trains = [];
    this._connected = false;
    this._gotSnapshot = false;
    this._centered = false;
    this._engine = null;
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) {
    const height = Number.parseInt(config.height, 10);
    const zoom = Number(config.zoom);
    const theme = _normalizeTheme(config.theme);
    const themeChanged = Boolean(this._config) && this._config.theme !== theme;
    this._config = {
      ...config,
      height: Number.isFinite(height) && height >= 240 ? height : 480,
      zoom: Number.isFinite(zoom) ? zoom : null,
      theme,
    };
    if (!this._map) return;
    this._applyHeight();
    this._resize();
    if (themeChanged) this._applyTheme();
  }

  static getConfigElement() {
    return document.createElement("vivi-trains-map-editor");
  }

  static getStubConfig() {
    return { height: 480, theme: "auto" };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    if (!this._started) {
      this._started = true;
      this._renderShell();
      this._start();
    } else {
      this._applyTheme();
      this._maybeCenter();
    }
  }

  getCardSize() {
    const height = this._config ? this._config.height : 480;
    return Math.max(4, Math.ceil(height / 50));
  }

  disconnectedCallback() {
    this._alive = false;
    this._clearRetry();
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
    if (this._resizeFrame) {
      cancelAnimationFrame(this._resizeFrame);
      this._resizeFrame = 0;
    }
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
    if (this._tokenUnsub) {
      this._tokenUnsub();
      this._tokenUnsub = null;
    }
    this._destroyMap();
    this._started = false;
  }

  _renderShell() {
    const height = this._config.height;
    this.shadowRoot.innerHTML = `
      <link rel="stylesheet" href="${LEAFLET_CSS}">
      <link rel="stylesheet" href="${MAPLIBRE_CSS}">
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
        .map.dark { background: #191b2c; }
        .leaflet-bar a.vivi-home,
        .maplibregl-ctrl-group button.vivi-home {
          display: flex;
          align-items: center;
          justify-content: center;
          color: #333;
          line-height: 0;
        }
        .leaflet-bar a.vivi-home svg,
        .maplibregl-ctrl-group button.vivi-home svg {
          display: block;
          width: 18px;
          height: 18px;
        }
        .maplibregl-popup-content,
        .maplibregl-popup-close-button,
        .leaflet-popup-content {
          color: #1c1c1e;
        }
        .map.dark .leaflet-tile-pane .leaflet-tile {
          filter: invert(0.9) hue-rotate(170deg) brightness(1.5) contrast(1.2) saturate(0.3);
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

  _isDark() {
    const theme = this._config && this._config.theme;
    if (theme === "dark") return true;
    if (theme === "light") return false;
    const themes = this._hass && this._hass.themes;
    if (themes && typeof themes.darkMode === "boolean") return themes.darkMode;
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  _applyTheme() {
    const container = this.shadowRoot && this.shadowRoot.querySelector(".map");
    const dark = this._isDark();
    if (container) container.classList.toggle("dark", dark);
    if (this._engine === "vector" && dark !== this._vectorDark) {
      this._reloadVectorStyle();
    }
  }

  async _start() {
    this._alive = true;
    const container = this.shadowRoot.querySelector(".map");
    this._keepGesturesOnMap(container);
    this._resizeObserver = new ResizeObserver(() => this._resize());
    this._resizeObserver.observe(container);
    try {
      const connection = this._hass && this._hass.connection;
      const token = connection ? await _ensureMapToken(connection) : null;
      if (!this.isConnected || !this._alive || this._map) return;
      let vector = false;
      if (token && _supportsWebGL2()) {
        try {
          vector = await this._startVector(container);
        } catch (err) {
          console.error("Vivi vector map failed, using raster tiles", err);
          this._destroyMap();
          container.replaceChildren();
        }
      }
      if (!this.isConnected || !this._alive) return;
      if (!vector) await this._startRaster(container, token);
      if (!this.isConnected || !this._alive || !this._map) return;
      this._tokenUnsub = _subscribeMapToken((next) => this._onToken(next));
      this._applyTheme();
      this._maybeCenter();
      this._resize();
      await this._subscribe();
    } catch (err) {
      if (!this.isConnected || !this._alive) return;
      this._setStatus("Live map unavailable");
      console.error("Vivi train map failed to start", err);
    }
  }

  async _startVector(container) {
    const maplibre = await _loadMapLibre();
    if (!this.isConnected || !this._alive) return false;
    const dark = this._isDark();
    const style = await _loadHaStyle(dark);
    if (!this.isConnected || !this._alive) return false;
    const home = this._homeView();
    const map = new maplibre.Map({
      container,
      style,
      center: [home.center[1], home.center[0]],
      zoom: home.zoom,
      minZoom: 1,
      maxZoom: 20,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
      localIdeographFontFamily: "sans-serif",
      attributionControl: true,
      transformRequest: (url) => _withMapTilesToken(url),
    });
    this._map = map;
    this._maplibre = maplibre;
    this._engine = "vector";
    this._vectorDark = dark;
    if (!this.isConnected || !this._alive) {
      this._destroyMap();
      return false;
    }
    if (map.touchZoomRotate) map.touchZoomRotate.disableRotation();
    if (map.keyboard) map.keyboard.disableRotation();
    map.addControl(new maplibre.NavigationControl({ showCompass: false }), "top-left");
    map.addControl(new HomeControl(this), "top-left");
    map.on("click", (event) => this._onVectorClick(event));
    map.on("style.load", () => {
      this._installVectorLayers();
      this._draw();
    });
    map.on("error", (event) => this._onVectorError(event));
    return true;
  }

  async _startRaster(container, token) {
    const leaflet = await _loadLeaflet();
    if (!this.isConnected || !this._alive || this._map) return;
    const home = this._homeView();
    this._map = leaflet.map(container, {
      zoomControl: true,
      scrollWheelZoom: true,
      touchZoom: true,
      doubleClickZoom: true,
      boxZoom: true,
      maxZoom: token ? 20 : 19,
    }).setView(home.center, home.zoom);
    this._engine = "raster";
    if (!this.isConnected || !this._alive) {
      this._destroyMap();
      return;
    }
    this._tiles = _rasterLayer(leaflet, token).addTo(this._map);
    this._layer = leaflet.layerGroup().addTo(this._map);
    this._addHomeControl(leaflet);
  }

  _destroyMap() {
    if (this._stationPopup) {
      this._stationPopup.remove();
      this._stationPopup = null;
    }
    if (this._trainPopup) {
      this._trainPopup.remove();
      this._trainPopup = null;
    }
    if (this._map) {
      this._map.remove();
      this._map = null;
    }
    this._tiles = null;
    this._layer = null;
    this._engine = null;
    this._maplibre = null;
    this._vectorPointer = false;
  }

  _installVectorLayers() {
    const map = this._map;
    if (!map || map.getSource("vivi-trains")) return;
    const empty = _featureCollection([]);
    map.addSource("vivi-routes", { type: "geojson", data: empty });
    map.addSource("vivi-trains", { type: "geojson", data: empty });
    map.addSource("vivi-station", { type: "geojson", data: empty });
    map.addLayer({
      id: "vivi-routes",
      type: "line",
      source: "vivi-routes",
      paint: {
        "line-color": ["get", "color"],
        "line-width": 3,
        "line-opacity": 0.45,
      },
    });
    map.addLayer({
      id: "vivi-trains",
      type: "circle",
      source: "vivi-trains",
      paint: {
        "circle-radius": 7,
        "circle-color": ["get", "color"],
        "circle-stroke-color": "#1c1c1e",
        "circle-stroke-width": 1,
        "circle-opacity": 0.95,
      },
    });
    map.addLayer({
      id: "vivi-station",
      type: "circle",
      source: "vivi-station",
      paint: {
        "circle-radius": 5,
        "circle-color": "#ffffff",
        "circle-stroke-color": "#1c1c1e",
        "circle-stroke-width": 2,
      },
    });
    if (this._vectorPointer) return;
    this._vectorPointer = true;
    const canvas = map.getCanvas();
    const pointer = () => {
      canvas.style.cursor = "pointer";
    };
    const plain = () => {
      canvas.style.cursor = "";
    };
    map.on("mouseenter", "vivi-trains", pointer);
    map.on("mouseleave", "vivi-trains", plain);
    map.on("mouseenter", "vivi-station", (event) => {
      pointer();
      this._showStationTip(event);
    });
    map.on("mouseleave", "vivi-station", () => {
      plain();
      if (this._stationPopup) this._stationPopup.remove();
    });
  }

  async _reloadVectorStyle() {
    if (this._engine !== "vector" || !this._map) return;
    const generation = (this._styleGeneration || 0) + 1;
    this._styleGeneration = generation;
    const dark = this._isDark();
    let style;
    try {
      style = await _loadHaStyle(dark);
    } catch (err) {
      console.error("Vivi map style failed to load", err);
      return;
    }
    if (generation !== this._styleGeneration || this._engine !== "vector" || !this._map) return;
    this._vectorDark = dark;
    this._map.setStyle(style);
  }

  _onVectorError(event) {
    const status = event && event.error && event.error.status;
    if (status !== undefined && status !== 403 && status !== 404) return;
    const now = Date.now();
    if (now - (this._lastRecovery || 0) < TILE_RECOVERY_MS) return;
    this._lastRecovery = now;
    const connection = this._hass && this._hass.connection;
    if (!connection) return;
    _refreshMapToken(connection).then((token) => {
      if (!token || this._engine !== "vector" || !this._map) return;
      this._vectorDark = null;
      this._reloadVectorStyle();
    });
  }

  _onVectorClick(event) {
    const map = this._map;
    if (!map || !map.getLayer("vivi-trains")) return;
    const trains = map.queryRenderedFeatures(event.point, { layers: ["vivi-trains"] });
    if (!trains.length) return;
    const props = trains[0].properties || {};
    const coordinates = trains[0].geometry && trains[0].geometry.coordinates;
    this._openTrainPopup(coordinates, props);
  }

  _openTrainPopup(coordinates, train) {
    if (!this._map || !this._maplibre || !coordinates) return;
    if (!this._trainPopup) {
      this._trainPopup = new this._maplibre.Popup({ maxWidth: "240px", offset: 12 });
    }
    this._trainPopup.setLngLat(coordinates).setHTML(this._popup(train)).addTo(this._map);
  }

  _showStationTip(event) {
    const feature = event.features && event.features[0];
    if (!feature || !this._map || !this._maplibre) return;
    const name = (feature.properties && feature.properties.name) || "Station";
    if (!this._stationPopup) {
      this._stationPopup = new this._maplibre.Popup({
        closeButton: false,
        closeOnClick: false,
        offset: 8,
      });
    }
    this._stationPopup
      .setLngLat(feature.geometry.coordinates)
      .setText(name)
      .addTo(this._map);
  }

  _onToken(token) {
    if (this._engine !== "raster" || !this._tiles || !token) return;
    this._tiles.setUrl(PROXY_RASTER + encodeURIComponent(token));
    if (this._map && this._map.options) this._map.options.maxZoom = 20;
    if (this._map && this._map.setMaxZoom) this._map.setMaxZoom(20);
  }

  _resize() {
    if (this._resizeFrame) return;
    this._resizeFrame = requestAnimationFrame(() => {
      this._resizeFrame = 0;
      if (!this._map) return;
      if (this._engine === "vector") this._map.resize();
      else this._map.invalidateSize();
    });
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
    if (this._engine === "vector") this._drawVector();
    else if (this._engine === "raster") this._drawRaster();
  }

  _drawRaster() {
    if (!this._map || !this._layer || !window.L) return;
    this._layer.clearLayers();
    const leaflet = window.L;
    for (const train of this._trains) {
      if (!Number.isFinite(train.lat) || !Number.isFinite(train.lon)) continue;
      const color = _trainColor(train.color);
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
      stationMarker.addTo(this._layer);
    }
  }

  _drawVector() {
    const map = this._map;
    if (!map || !map.getSource("vivi-trains")) return;
    const routes = [];
    const points = [];
    for (const train of this._trains) {
      if (!Number.isFinite(train.lat) || !Number.isFinite(train.lon)) continue;
      const color = _trainColor(train.color);
      const line = _lineCoordinates(train.polyline);
      if (line.length > 1) {
        routes.push({
          type: "Feature",
          properties: { color },
          geometry: { type: "LineString", coordinates: line },
        });
      }
      points.push({
        type: "Feature",
        properties: {
          train: train.train || "",
          name: train.name || "",
          delay: Number(train.delay) || 0,
          next_stop: train.next_stop || "",
          color,
          lat: train.lat,
          lon: train.lon,
        },
        geometry: { type: "Point", coordinates: [train.lon, train.lat] },
      });
    }
    map.getSource("vivi-routes").setData(_featureCollection(routes));
    map.getSource("vivi-trains").setData(_featureCollection(points));
    const station = this._stationPosition();
    const stationFeatures = station
      ? [{
          type: "Feature",
          properties: { name: this._stationName() || "Station" },
          geometry: { type: "Point", coordinates: [station[1], station[0]] },
        }]
      : [];
    map.getSource("vivi-station").setData(_featureCollection(stationFeatures));
  }

  _popup(train) {
    const delay = Number(train.delay) > 0 ? `+${Number(train.delay)} min` : "On time";
    const next = train.next_stop ? `<div>Next: ${_esc(train.next_stop)}</div>` : "";
    const name = train.name ? `<div>${_esc(train.name)}</div>` : "";
    return `<strong>${_esc(train.train || "Train")}</strong>${name}<div>${_esc(delay)}</div>${next}`;
  }

  _keepGesturesOnMap(container) {
    // Lovelace scrolls the dashboard on wheel and touch. Stop those events
    // after the map has used them, so pinch, drag, and scroll zoom the map.
    const stop = (event) => event.stopPropagation();
    container.addEventListener("wheel", stop);
    container.addEventListener("touchstart", stop);
    container.addEventListener("touchmove", stop);
  }

  _homeView() {
    const station = this._stationPosition();
    return {
      center: station || LATVIA_CENTER,
      zoom: this._config.zoom ?? (this._config.entity ? 10 : 7),
    };
  }

  _zoomHome() {
    const home = this._homeView();
    this._moveTo(home.center[0], home.center[1], home.zoom, true);
  }

  _moveTo(lat, lon, zoom, animate) {
    if (!this._map || !Number.isFinite(lat) || !Number.isFinite(lon)) return;
    if (this._engine === "vector") {
      const camera = { center: [lon, lat], zoom };
      if (animate) this._map.flyTo({ ...camera, duration: 500 });
      else this._map.jumpTo(camera);
      return;
    }
    if (animate) this._map.flyTo([lat, lon], zoom, { duration: 0.5 });
    else this._map.setView([lat, lon], zoom);
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
        button.innerHTML = HOME_ICON;
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
    this._moveTo(home.center[0], home.center[1], home.zoom, false);
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

class HomeControl {
  constructor(card) {
    this._card = card;
  }

  onAdd() {
    const container = document.createElement("div");
    container.className = "maplibregl-ctrl maplibregl-ctrl-group";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "vivi-home";
    button.title = "Current location";
    button.setAttribute("aria-label", "Current location");
    button.innerHTML = HOME_ICON;
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      this._card._zoomHome();
    });
    container.appendChild(button);
    this._container = container;
    return container;
  }

  onRemove() {
    if (this._container) this._container.remove();
  }
}

function _esc(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _trainColor(color) {
  return /^#[0-9a-fA-F]{3,8}$/.test(color || "") ? color : "#F8DB22";
}

function _featureCollection(features) {
  return { type: "FeatureCollection", features };
}

function _lineCoordinates(polyline) {
  if (!Array.isArray(polyline)) return [];
  const coordinates = [];
  for (const pair of polyline) {
    if (!Array.isArray(pair) || pair.length < 2) continue;
    const lat = Number(pair[0]);
    const lon = Number(pair[1]);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
    coordinates.push([lon, lat]);
  }
  return coordinates;
}

function _supportsWebGL2() {
  if (_supportsWebGL2.cached !== undefined) return _supportsWebGL2.cached;
  try {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("webgl2");
    _supportsWebGL2.cached = Boolean(context);
    const lose = context && context.getExtension("WEBGL_lose_context");
    if (lose) lose.loseContext();
  } catch (err) {
    _supportsWebGL2.cached = false;
  }
  return _supportsWebGL2.cached;
}

function _wait(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function _readMapToken(connection) {
  try {
    const result = await connection.sendMessagePromise({ type: "map_tiles/access_token" });
    if (result && typeof result.token === "string" && result.token) return result.token;
  } catch (err) {
    // Core older than 2026.9 has no Map tiles command.
  }
  return null;
}

async function _fetchMapToken(connection) {
  const delays = [0, 400, 1000];
  for (const delay of delays) {
    if (delay) await _wait(delay);
    const token = await _readMapToken(connection);
    if (token) return token;
  }
  return null;
}

async function _ensureMapToken(connection) {
  _tokenConnection = connection;
  if (_mapToken) return _mapToken;
  if (!_tokenRequest) {
    _tokenRequest = _fetchMapToken(connection).finally(() => {
      _tokenRequest = undefined;
    });
  }
  const token = await _tokenRequest;
  if (token) {
    _mapToken = token;
    _scheduleTokenRefresh();
  }
  return _mapToken || null;
}

function _scheduleTokenRefresh() {
  if (_tokenTimer) return;
  _tokenTimer = setInterval(() => {
    const connection = _tokenConnection;
    if (!connection) return;
    _readMapToken(connection).then((token) => {
      if (token) _publishMapToken(token);
    });
  }, TOKEN_REFRESH_MS);
}

function _publishMapToken(token) {
  if (!token || token === _mapToken) return;
  _mapToken = token;
  _tokenListeners.forEach((listener) => listener(token));
}

async function _refreshMapToken(connection) {
  _tokenConnection = connection || _tokenConnection;
  if (!_tokenConnection) return null;
  const token = await _readMapToken(_tokenConnection);
  if (token) _publishMapToken(token);
  return token || _mapToken || null;
}

function _subscribeMapToken(listener) {
  _tokenListeners.add(listener);
  return () => _tokenListeners.delete(listener);
}

function _withMapTilesToken(url) {
  let parsed;
  try {
    parsed = new URL(url, location.origin);
  } catch (err) {
    return { url };
  }
  if (!parsed.pathname.startsWith(`${MAP_TILES_PATH}/`) || !_mapToken) {
    return { url: parsed.href };
  }
  return {
    url: parsed.href,
    headers: { [TOKEN_HEADER]: _mapToken },
  };
}

async function _loadHaStyle(dark) {
  const name = dark ? "dark" : "light";
  if (!_styleCache.has(name)) {
    const request = fetch(STYLE_URLS[name], { credentials: "same-origin" }).then((response) => {
      if (!response.ok) throw new Error(`Home Assistant map style ${name} is unavailable`);
      return response.json();
    });
    _styleCache.set(name, request);
    request.catch(() => _styleCache.delete(name));
  }
  const style = await _styleCache.get(name);
  return structuredClone(style);
}

function _rasterLayer(leaflet, token) {
  if (token) {
    return leaflet.tileLayer(PROXY_RASTER + encodeURIComponent(token), {
      maxZoom: 20,
      maxNativeZoom: 19,
      attribution: OSM_ATTRIBUTION,
    });
  }
  // Home Assistant sends Referrer-Policy: no-referrer. OSM blocks those
  // tile requests, so each tile image has to name its own referrer policy.
  return leaflet.tileLayer(OSM_RASTER, {
    maxZoom: 19,
    attribution: OSM_ATTRIBUTION,
    referrerPolicy: "strict-origin-when-cross-origin",
  });
}

function _loadScript(url, ready) {
  return new Promise((resolve, reject) => {
    if (ready()) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = url;
    script.onload = () => (ready() ? resolve() : reject(new Error(`${url} did not load`)));
    script.onerror = () => reject(new Error(`Unable to load ${url}`));
    document.head.appendChild(script);
  });
}

function _loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (!window.__viviLeaflet) {
    window.__viviLeaflet = _loadScript(LEAFLET_JS, () => window.L).then(() => window.L);
  }
  return window.__viviLeaflet;
}

function _loadMapLibre() {
  if (window.maplibregl) return Promise.resolve(window.maplibregl);
  if (!window.__viviMapLibre) {
    window.__viviMapLibre = _loadScript(MAPLIBRE_JS, () => window.maplibregl).then(() => window.maplibregl);
  }
  return window.__viviMapLibre;
}

class ViviTrainsMapEditor extends HTMLElement {
  setConfig(config) {
    this._config = { theme: "auto", ...config, theme: _normalizeTheme(config && config.theme) };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
  }

  _render() {
    if (!this._form) {
      const form = document.createElement("ha-form");
      form.schema = [
        { name: "entity", selector: { entity: { domain: "sensor" } } },
        {
          name: "height",
          selector: { number: { min: 240, max: 1600, mode: "box", unit_of_measurement: "px" } },
        },
        {
          name: "zoom",
          selector: { number: { min: 1, max: 18, step: 1, mode: "box" } },
        },
        {
          name: "theme",
          required: true,
          selector: { select: { mode: "dropdown", options: THEME_OPTIONS } },
        },
      ];
      form.computeLabel = (schema) =>
        ({
          entity: "Station",
          height: "Height",
          zoom: "Zoom",
          theme: "Map theme",
        })[schema.name] || schema.name;
      form.computeHelper = (schema) =>
        ({
          entity: "Optional. Centers the map on this station.",
          theme: "Follow dashboard uses the current Home Assistant theme.",
        })[schema.name] || "";
      form.addEventListener("value-changed", (event) => {
        event.stopPropagation();
        const config = { ...event.detail.value };
        config.theme = _normalizeTheme(config.theme);
        if (config.zoom === "" || config.zoom == null) delete config.zoom;
        if (config.height === "" || config.height == null) delete config.height;
        if (!config.entity) delete config.entity;
        this._config = config;
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config },
            bubbles: true,
            composed: true,
          }),
        );
      });
      this._form = form;
      this.append(form);
    }
    this._form.data = this._config;
    if (this._hass) this._form.hass = this._hass;
  }
}

function _normalizeTheme(value) {
  const theme = String(value || "").trim().toLowerCase();
  if (theme === "light" || theme === "dark") return theme;
  return "auto";
}

const THEME_OPTIONS = [
  { value: "auto", label: "Follow dashboard" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

customElements.define("vivi-trains-map", ViviTrainsMap);
customElements.define("vivi-trains-map-editor", ViviTrainsMapEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "vivi-trains-map",
  name: "Vivi Trains Map",
  description: "Live map of running Latvian Vivi trains.",
  preview: false,
});

console.info(
  "%c VIVI-TRAINS-MAP %c v1.3.0 ",
  "background:#F8DB22;color:#000;font-weight:700;padding:2px 4px;border-radius:3px 0 0 3px",
  "background:#1c1c1e;color:#F8DB22;font-weight:700;padding:2px 4px;border-radius:0 3px 3px 0",
);
