/*
 * rapidbus-card: live map + arrivals for the Prasarana Bus (RapidKL) integration.
 * Ships inside custom_components/prasarana_bus and is loaded automatically.
 * Map: Leaflet 1.9.4 (BSD-2) with OpenStreetMap tiles. Bus sprites: our own (tools/bus3d.py).
 */
const BASE = new URL(".", import.meta.url).pathname.replace(/\/$/, "");
const VERSION = new URL(import.meta.url).searchParams.get("v") || "dev";
const SPRITES = 32;
const SUFFIXES = ["_next_bus_eta", "_next_bus_distance", "_next_bus_status", "_next_scheduled_bus", "_active_buses", "_feed_updated"];
const STATUS_TEXT = {
  approaching: "Bus on the way",
  at_stop: "Bus at your stop",
  scheduled: "No live bus on the way yet. Times below are from the timetable.",
  none_heading_here: "Buses are out, but none are heading your way yet.",
  no_buses: "No buses are sharing their location right now.",
  no_service: "No buses scheduled for the next few hours.",
};

let leafletPromise;
function loadLeaflet() {
  if (window.L && window.L.map) return Promise.resolve(window.L);
  if (!leafletPromise) {
    leafletPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = `${BASE}/leaflet/leaflet.js?v=1.9.4`;
      s.onload = () => resolve(window.L);
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  return leafletPromise;
}

const spriteUrl = (bearing) => {
  const b = ((Number(bearing) || 0) % 360 + 360) % 360;
  const i = Math.round(b / (360 / SPRITES)) % SPRITES;
  return `${BASE}/buses/bus_${String(i).padStart(2, "0")}.svg?v=${VERSION}`;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Title case, but keep known acronyms upper case.
const ACRONYMS = new Set(["KL", "KLCC", "KLIA", "LRT", "MRT", "KTM", "BRT", "PJ", "UM", "UKM", "UPM", "UIA", "IOI", "TTDI", "PPR", "HKL", "PPUM", "LDP", "NPE", "MRR2", "SS", "USJ", "PJU", "PJS", "UOA", "IKEA", "AEON", "KPJ", "TBS", "ITT"]);
const title = (s) => String(s ?? "").split(/(\s+|-|\/)/).map((w) =>
  ACRONYMS.has(w.toUpperCase()) ? w.toUpperCase()
    : w.toLowerCase().replace(/^\w/, (c) => c.toUpperCase())).join("");
const stopName = (s) => title(String(s ?? "").replace(/^[A-Z]{1,4}\d{2,}[A-Z]?\s+/, ""));
const ageMin = (iso) => (iso ? (Date.now() - new Date(iso).getTime()) / 60000 : Infinity);
const fmtMin = (m) => (m == null ? "–" : m < 1 ? "Now" : `${Math.round(m)}`);

class RapidBusCard extends HTMLElement {
  static getStubConfig(hass) {
    const e = Object.keys(hass.states).find((id) => id.startsWith("sensor.rapidbus_") && id.endsWith("_next_bus_eta"))
      || Object.keys(hass.states).find((id) => id.startsWith("sensor.rapidbus_") && id.endsWith("_active_buses"));
    return { entity: e || "" };
  }
  static getConfigElement() { return document.createElement("rapidbus-card-editor"); }

  setConfig(config) {
    if (!config || !config.entity) throw new Error("Pick one of the integration's sensors (e.g. …_next_bus_eta)");
    let prefix = config.entity;
    for (const s of SUFFIXES) if (prefix.endsWith(s)) { prefix = prefix.slice(0, -s.length); break; }
    this._cfg = {
      show_map: true, map_height: 300, rows: 3, bus_size: 52,
      route_color: null, zoom: null, show_stops: true, dark_tiles: "auto",
      ...config,
    };
    this._ids = {
      eta: `${prefix}_next_bus_eta`, active: `${prefix}_active_buses`,
      status: `${prefix}_next_bus_status`, sched: `${prefix}_next_scheduled_bus`,
    };
    this._built = false;
    this._fitted = false;
    if (this._hass) this._render();
  }

  set hass(hass) {
    const old = this._hass;
    this._hass = hass;
    if (!this._cfg) return;
    if (old && Object.values(this._ids).every((id) => old.states[id] === hass.states[id])) return;
    this._render();
  }

  getCardSize() { return (this._cfg?.show_map ? Math.ceil(this._cfg.map_height / 50) : 0) + 2 + (this._cfg?.rows || 3); }
  getGridOptions() { return { columns: 12, min_columns: 6, rows: "auto" }; }

  _build() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const c = this._cfg;
    this.shadowRoot.innerHTML = `
      <link rel="stylesheet" href="${BASE}/leaflet/leaflet.css?v=1.9.4">
      <style>
        :host { --rb-navy: #1d2fa0; --rb-red: #e30613; --rb-live: var(--success-color, #2e9e4f); }
        ha-card { overflow: hidden; }
        .head { display: flex; align-items: center; gap: 12px; padding: 14px 16px 6px; }
        .chip { display: inline-flex; align-items: center; gap: 6px; font-weight: 700; font-size: 15px;
          padding: 3px 9px; border-radius: 9px; line-height: 20px; white-space: nowrap; }
        .chip.kl { background: var(--rb-navy); color: #fff; }
        .chip.feeder { background: var(--card-background-color, #fff); color: var(--primary-text-color);
          border: 2px solid #f7c600; }
        .chip ha-icon { --mdc-icon-size: 18px; }
        .stop { min-width: 0; }
        .stop .lbl { font-size: 12px; color: var(--secondary-text-color); }
        .stop .name { font-size: 18px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .map { height: ${Number(c.map_height)}px; margin: 8px 0 0; position: relative; z-index: 0; }
        .map.hidden { display: none; }
        .leaflet-container { background: var(--secondary-background-color, #eee); font: inherit; }
        :host(.dark) .leaflet-tile-pane { filter: invert(.9) hue-rotate(180deg) brightness(1.1) contrast(1.1) saturate(.35); }
        :host(.dark) .leaflet-control-attribution, :host(.dark) .leaflet-bar a { background: #222; color: #ccc; }
        .bus-icon img { width: 100%; height: 100%; display: block; filter: drop-shadow(0 1px 1px rgba(0,0,0,.25)); }
        .bus-icon.stale img { opacity: .45; filter: grayscale(.6); }
        .bus-icon.next img { filter: drop-shadow(0 0 4px rgba(46,158,79,.9)); }
        .stop-pin { width: 22px; height: 22px; border-radius: 50% 50% 50% 0; transform: rotate(-45deg);
          background: var(--rb-navy); border: 3px solid #fff; box-shadow: 0 1px 4px rgba(0,0,0,.4); }
        .leaflet-popup-content { margin: 10px 12px; font-size: 13px; line-height: 1.45; }
        .leaflet-popup-content b { font-size: 14px; }
        .list { padding: 4px 16px 12px; }
        .row { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid var(--divider-color, #e0e0e0); }
        .row:first-child, .note + .row { border-top: 0; }
        .row .mid { flex: 1; min-width: 0; }
        .row .hs { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .row .sub { font-size: 12px; color: var(--secondary-text-color); }
        .eta { text-align: right; white-space: nowrap; }
        .eta .n { font-size: 26px; font-weight: 700; line-height: 1; }
        .eta .u { font-size: 13px; font-weight: 600; margin-left: 2px; }
        .eta.live { color: var(--rb-live); }
        .eta.sched { color: var(--secondary-text-color); }
        .eta .tag { font-size: 11px; display: flex; align-items: center; justify-content: flex-end; gap: 3px; margin-top: 2px; }
        .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--rb-live); animation: p 1.6s infinite; }
        @keyframes p { 0% { box-shadow: 0 0 0 0 rgba(46,158,79,.6); } 70% { box-shadow: 0 0 0 7px rgba(46,158,79,0); } 100% { box-shadow: 0 0 0 0 rgba(46,158,79,0); } }
        .note { display: flex; gap: 8px; align-items: center; margin: 8px 0 2px; padding: 8px 10px; border-radius: 10px;
          font-size: 13px; background: rgba(255,152,0,.12); color: var(--primary-text-color); }
        .note ha-icon { --mdc-icon-size: 18px; color: #ff9800; }
        .foot { font-size: 11px; color: var(--secondary-text-color); padding: 0 16px 10px; display: flex; justify-content: space-between; }
      </style>
      <ha-card>
        <div class="head"><span class="chip" id="chip"></span><div class="stop"><div class="lbl" id="lbl"></div><div class="name" id="name"></div></div></div>
        <div class="map ${c.show_map ? "" : "hidden"}" id="map"></div>
        <div class="list" id="list"></div>
        <div class="foot" id="foot"></div>
      </ha-card>`;
    this._built = true;
    this._map = null;
    if (c.show_map) this._initMap();
  }

  async _initMap() {
    const L = await loadLeaflet();
    const el = this.shadowRoot.getElementById("map");
    if (!el || this._map) return;
    this._L = L;
    this._map = L.map(el, { zoomControl: true, attributionControl: true, scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      // HA pages send no Referer (same-origin policy), and OSM blocks tiles without one (403 "Access blocked").
      referrerPolicy: "strict-origin-when-cross-origin",
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(this._map);
    this._map.createPane("rbStops").style.zIndex = 450;
    this._routeLayer = L.layerGroup().addTo(this._map);
    this._stopLayer = L.layerGroup().addTo(this._map);
    this._busLayer = L.layerGroup().addTo(this._map);
    this._busMarkers = {};
    const toggleStops = () => {
      const show = this._map.getZoom() >= 14;
      if (show && !this._map.hasLayer(this._stopDots)) this._stopDots.addTo(this._map);
      if (!show && this._map.hasLayer(this._stopDots)) this._map.removeLayer(this._stopDots);
    };
    this._stopDots = L.layerGroup();
    this._map.on("zoomend", toggleStops);
    this._toggleStops = toggleStops;
    this._routeDrawn = null;
    // Stop auto-framing once the user pans or zooms by hand.
    this._userMoved = false;
    for (const ev of ["mousedown", "touchstart", "wheel", "keydown"]) el.addEventListener(ev, () => { this._userMoved = true; }, { passive: true });
    new ResizeObserver(() => {
      if (!this._map || !el.clientWidth || !el.clientHeight) return;
      this._map.invalidateSize();
      // The card can be laid out after the first fit (wrong size then): frame again until the user takes over.
      if (!this._userMoved) { this._fitted = false; this._updateMap(); }
    }).observe(el);
    this._updateMap();
  }

  _render() {
    if (!this._built) this._build();
    const h = this._hass, c = this._cfg, ids = this._ids;
    const dark = c.dark_tiles === "auto" || c.dark_tiles == null ? !!h.themes?.darkMode : !!c.dark_tiles;
    this.classList.toggle("dark", dark);
    const eta = h.states[ids.eta], act = h.states[ids.active], sched = h.states[ids.sched];
    const route = act?.attributes.route || eta?.attributes.route || "";
    const feeder = /^T\d/i.test(route);
    const sr = this.shadowRoot;
    const chip = sr.getElementById("chip");
    chip.className = `chip ${feeder ? "feeder" : "kl"}`;
    chip.innerHTML = `${esc(route)}<ha-icon icon="mdi:bus-side"></ha-icon>`;
    if (eta) {
      sr.getElementById("lbl").textContent = c.title || "Next arrivals at";
      sr.getElementById("name").textContent = c.stop_name || stopName(eta.attributes.stop_name);
    } else {
      sr.getElementById("lbl").textContent = c.title || "Live buses";
      sr.getElementById("name").textContent = act ? title(act.attributes.route_name || "") : `Entity not found: ${ids.active}`;
    }
    this._renderList(eta, act, sched);
    const n = act ? Number(act.state) : 0;
    sr.getElementById("foot").innerHTML = `<span>${isNaN(n) ? "" : `${n} bus${n === 1 ? "" : "es"} on GPS`}</span><span>${eta?.attributes.headway_min ? `Every ~${Math.round(eta.attributes.headway_min)} min` : ""}</span>`;
    this._updateMap();
  }

  _renderList(eta, act, sched) {
    const list = this.shadowRoot.getElementById("list");
    const rows = Number(this._cfg.rows) || 3;
    if (!eta) { list.innerHTML = ""; return; }
    const a = eta.attributes;
    const route = act?.attributes.route || "";
    const feeder = /^T\d/i.test(route);
    const chip = `<span class="chip ${feeder ? "feeder" : "kl"}" style="font-size:13px;padding:1px 7px">${esc(route)}</span>`;
    let html = "";
    const live = (a.upcoming || []).slice(0, rows);
    live.forEach((b) => {
      const stale = ageMin(b.last_seen) > 2;
      html += `<div class="row">${chip}<div class="mid"><div class="hs">${esc(title(b.heading_to) || "—")}</div>
        <div class="sub">${esc(b.plate)} · ${b.distance_km != null ? `${b.distance_km} km away` : ""}${stale ? " · GPS lagging" : ""}</div></div>
        <div class="eta live"><span class="n">${fmtMin(b.eta_min)}</span>${b.eta_min >= 1 ? '<span class="u">min</span>' : ""}
        <div class="tag"><span class="pulse"></span>Live</div></div></div>`;
    });
    const timetable = (sched?.attributes.upcoming || []);
    if (live.length < rows && timetable.length) {
      const lastLive = live.length ? Date.now() + live[live.length - 1].eta_min * 60000 : 0;
      timetable.filter((t) => new Date(t.datetime).getTime() > lastLive + 60000).slice(0, rows - live.length).forEach((t) => {
        const mins = (new Date(t.datetime).getTime() - Date.now()) / 60000;
        html += `<div class="row">${chip}<div class="mid"><div class="hs">${esc(title(t.heading_to) || "—")}</div>
          <div class="sub">Scheduled ${esc(t.time)}${sched.attributes.frequency_based ? " · based on frequency" : ""}</div></div>
          <div class="eta sched"><span class="n">${mins > 90 ? esc(t.time) : fmtMin(mins)}</span>${mins >= 1 && mins <= 90 ? '<span class="u">min</span>' : ""}
          <div class="tag"><ha-icon icon="mdi:clock-outline" style="--mdc-icon-size:13px"></ha-icon>Timetable</div></div></div>`;
      });
    }
    const status = a.status;
    if (!live.length && status && status !== "scheduled") {
      html = `<div class="note"><ha-icon icon="mdi:information-outline"></ha-icon>${esc(STATUS_TEXT[status] || status)}</div>` + html;
    } else if (!live.length && status === "scheduled") {
      html = `<div class="note"><ha-icon icon="mdi:clock-alert-outline"></ha-icon>${esc(STATUS_TEXT.scheduled)}</div>` + html;
    }
    list.innerHTML = html || `<div class="note"><ha-icon icon="mdi:information-outline"></ha-icon>${esc(STATUS_TEXT.no_buses)}</div>`;
  }

  _updateMap() {
    if (!this._map) return;
    const L = this._L, h = this._hass, c = this._cfg;
    const act = h.states[this._ids.active], eta = h.states[this._ids.eta];
    if (!act) return;
    const gj = act.attributes.route_geojson;
    const color = c.route_color || (this.classList.contains("dark") ? "#6f86ff" : "#1d2fa0");
    const key = gj ? JSON.stringify(gj).length + ":" + color : null;
    if (gj && key !== this._routeDrawn) {
      this._routeLayer.clearLayers();
      const casing = L.geoJSON(gj, { style: { color: this.classList.contains("dark") ? "#111" : "#ffffff", weight: 9, opacity: 0.9 }, interactive: false });
      const line = L.geoJSON(gj, { style: { color, weight: 6, opacity: 0.95, lineCap: "round", lineJoin: "round" }, interactive: false });
      casing.addTo(this._routeLayer); line.addTo(this._routeLayer);
      this._routeBounds = line.getBounds();
      this._routeDrawn = key;
      this._stopLayer.clearLayers();
      this._stopDots.clearLayers();
      if (c.show_stops) {
        (act.attributes.route_stops || []).forEach(([lat, lon, name]) => {
          L.circleMarker([lat, lon], { pane: "rbStops", radius: 3.5, color, weight: 2, fillColor: "#fff", fillOpacity: 1 })
            .bindTooltip(esc(name), { direction: "top" }).addTo(this._stopDots);
        });
      }
      if (eta?.attributes.latitude != null) {
        const pin = L.divIcon({ className: "", html: '<div class="stop-pin"></div>', iconSize: [22, 22], iconAnchor: [11, 26] });
        L.marker([eta.attributes.latitude, eta.attributes.longitude], { icon: pin, zIndexOffset: 500 })
          .bindTooltip(esc(stopName(eta.attributes.stop_name)), { direction: "top", offset: [0, -24] }).addTo(this._stopLayer);
      }
    }
    // buses
    const size = Number(c.bus_size) || 46;
    const nextPlate = eta?.attributes.plate;
    const seen = new Set();
    (act.attributes.buses || []).forEach((b) => {
      if (b.latitude == null) return;
      seen.add(b.plate);
      const cls = `bus-icon${ageMin(b.last_seen) > 2 ? " stale" : ""}${b.plate === nextPlate ? " next" : ""}`;
      const html = `<img src="${spriteUrl(b.bearing)}" alt="">`;
      const popup = `<b>${esc(b.plate)}</b><br>To ${esc(title(b.heading_to) || "—")}<br>${b.speed_kmh != null ? `${Math.round(b.speed_kmh)} km/h · ` : ""}${b.eta_min != null ? `${fmtMin(b.eta_min)}${b.eta_min >= 1 ? " min" : ""} to your stop` : "Not heading to your stop"}<br><span style="color:var(--secondary-text-color)">Seen ${Math.max(0, Math.round(ageMin(b.last_seen)))} min ago</span>`;
      let m = this._busMarkers[b.plate];
      const icon = L.divIcon({ className: cls, html, iconSize: [size, size], iconAnchor: [size / 2, size * 0.62] });
      if (!m) {
        m = L.marker([b.latitude, b.longitude], { icon, zIndexOffset: 1000 }).bindPopup(popup).addTo(this._busLayer);
        this._busMarkers[b.plate] = m;
      } else {
        m.setLatLng([b.latitude, b.longitude]);
        if (m._rbHtml !== html + cls) m.setIcon(icon);
        m.setPopupContent(popup);
      }
      m._rbHtml = html + cls;
    });
    for (const p of Object.keys(this._busMarkers)) {
      if (!seen.has(p)) { this._busLayer.removeLayer(this._busMarkers[p]); delete this._busMarkers[p]; }
    }
    const nb = (eta?.attributes.upcoming || [])[0];
    const frameKey = nb ? nb.plate : "";
    if (!this._userMoved && this._frameKey !== undefined && frameKey !== this._frameKey) this._fitted = false; // next bus changed
    const box = this._map.getContainer();
    if (!this._fitted && box.clientWidth > 0 && box.clientHeight > 0) {
      // Leaflet caches the container size, and before the first view is set invalidateSize() won't refresh it.
      this._map._sizeChanged = true;
      this._frameKey = frameKey;
      if (c.zoom && eta?.attributes.latitude != null) this._map.setView([eta.attributes.latitude, eta.attributes.longitude], c.zoom);
      else if (nb && eta?.attributes.latitude != null) {
        // like Pulse: frame your stop and the bus that's coming
        this._map.fitBounds(L.latLngBounds([[eta.attributes.latitude, eta.attributes.longitude], [nb.latitude, nb.longitude]]), { padding: [40, 40], maxZoom: 16 });
      } else if (this._routeBounds?.isValid()) this._map.fitBounds(this._routeBounds, { padding: [16, 16] });
      else return;
      this._fitted = true;
      this._toggleStops();
    }
  }
}

class RapidBusCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._draw(); }
  set hass(hass) { this._hass = hass; this._draw(); }
  _draw() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => ({
        entity: "Route or stop sensor", title: "Heading label", stop_name: "Stop name override", show_map: "Show map",
        map_height: "Map height (px)", zoom: "Zoom (blank = whole route)", rows: "Arrival rows", bus_size: "Bus icon size (px)",
        route_color: "Route line colour", show_stops: "Show stop dots", dark_tiles: "Map style",
      }[s.name] || s.name);
      this._form.addEventListener("value-changed", (ev) => {
        this._config = ev.detail.value;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { integration: "prasarana_bus", domain: "sensor" } } },
      { type: "grid", name: "", schema: [
        { name: "rows", selector: { number: { min: 1, max: 5, mode: "box" } } },
        { name: "show_map", selector: { boolean: {} } },
        { name: "map_height", selector: { number: { min: 150, max: 700, step: 10, mode: "box" } } },
        { name: "zoom", selector: { number: { min: 10, max: 18, mode: "box" } } },
        { name: "bus_size", selector: { number: { min: 24, max: 80, mode: "box" } } },
        { name: "route_color", selector: { text: {} } },
        { name: "show_stops", selector: { boolean: {} } },
        { name: "dark_tiles", selector: { select: { mode: "dropdown", options: [
          { value: "auto", label: "Follow theme" }, { value: true, label: "Always dark" }, { value: false, label: "Always light" }] } } },
      ] },
      { name: "title", selector: { text: {} } },
      { name: "stop_name", selector: { text: {} } },
    ];
  }
}

if (!customElements.get("rapidbus-card")) customElements.define("rapidbus-card", RapidBusCard);
if (!customElements.get("rapidbus-card-editor")) customElements.define("rapidbus-card-editor", RapidBusCardEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "rapidbus-card")) {
  window.customCards.push({
    type: "rapidbus-card", name: "Rapid Bus", preview: true,
    description: "Live RapidKL / MRT feeder buses on a map, with arrivals at your stop.",
    documentationURL: "https://github.com/zubir2k/homeassistant-rapidbus",
  });
}
console.info(`%c RAPIDBUS-CARD %c ${VERSION} `, "background:#e30613;color:#fff;font-weight:700", "background:#1d2fa0;color:#fff");
