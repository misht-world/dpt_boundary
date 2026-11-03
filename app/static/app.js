/* Схемы границ территорий — фронтенд */
"use strict";

const map = L.map("map", { zoomControl: true }).setView([59.94, 30.31], 11); // СПб

let currentLayers = [];
let basemaps = [];

const el = (id) => document.getElementById(id);

function setBasemap(id) {
  currentLayers.forEach((l) => map.removeLayer(l));
  currentLayers = [];
  const bm = basemaps.find((b) => b.id === id);
  if (!bm) return;
  bm.layers.forEach((ly) => {
    const tl = L.tileLayer(ly.url, {
      maxZoom: bm.max_zoom,
      opacity: ly.opacity,
      attribution: "",
    });
    tl.addTo(map);
    currentLayers.push(tl);
  });
}

fetch("/api/basemaps")
  .then((r) => r.json())
  .then((list) => {
    basemaps = list;
    const sel = el("basemap");
    list.forEach((b) => {
      const o = document.createElement("option");
      o.value = b.id;
      o.textContent = b.title;
      sel.appendChild(o);
    });
    sel.value = "osm_gp_zu";
    setBasemap("osm_gp_zu");
    sel.addEventListener("change", () => setBasemap(sel.value));
  });

/* --- рисование --- */
map.pm.setLang("ru");
map.pm.addControls({
  position: "topleft",
  drawMarker: false, drawCircleMarker: false, drawPolyline: false,
  drawRectangle: true, drawPolygon: true, drawCircle: false, drawText: false,
  editMode: true, dragMode: true, cutPolygon: false, removalMode: true,
  rotateMode: false,
});
map.pm.setPathOptions({ color: "#0099ff", weight: 3, fillOpacity: 0.05 });

let boundary = null; // текущий контур (Polygon layer)
let labelMarkers = []; // подписи на карте
let frameRect = null; // рамка будущей схемы
let manualFrame = false; // рамка отредактирована вручную

/* рамка кадра: та же логика, что padded_bbox на сервере */
const FRAME_PADDING = 0.18;

function toWorld(lat, lng) {
  const x = (lng + 180) / 360;
  const y = (1 - Math.asinh(Math.tan((lat * Math.PI) / 180)) / Math.PI) / 2;
  return [x, y];
}
function fromWorld(x, y) {
  const lng = x * 360 - 180;
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180) / Math.PI;
  return [lat, lng];
}

function updateFrame() {
  if (!boundary) {
    if (frameRect) { map.removeLayer(frameRect); frameRect = null; }
    manualFrame = false;
    el("manualframe").checked = false;
    el("manualframe").disabled = true;
    return;
  }
  el("manualframe").disabled = false;
  if (manualFrame) { // рамку ведёт пользователь — не пересчитываем
    if (typeof refreshLabelSizes === "function") refreshLabelSizes();
    return;
  }
  const pts = boundary.getLatLngs()[0].map((p) => toWorld(p.lat, p.lng));
  let x1 = Math.min(...pts.map((p) => p[0]));
  let x2 = Math.max(...pts.map((p) => p[0]));
  let y1 = Math.min(...pts.map((p) => p[1]));
  let y2 = Math.max(...pts.map((p) => p[1]));
  const pad = Math.max(x2 - x1, y2 - y1, 1e-9) * FRAME_PADDING;
  const bounds = L.latLngBounds(
    fromWorld(x1 - pad, y2 + pad),
    fromWorld(x2 + pad, y1 - pad)
  );
  if (frameRect) {
    frameRect.setBounds(bounds);
  } else {
    frameRect = L.rectangle(bounds, {
      color: "#666", weight: 1.5, dashArray: "6 6",
      fill: false, interactive: false, pmIgnore: true,
    }).addTo(map);
    ["pm:edit", "pm:markerdrag", "pm:markerdragend", "pm:dragend"]
      .forEach((ev) => frameRect.on(ev, () => {
        if (typeof refreshLabelSizes === "function") refreshLabelSizes();
      }));
  }
  if (typeof refreshLabelSizes === "function") refreshLabelSizes();
}

/* текущая рамка для сервера: [W, S, E, N] */
function frameBBox() {
  if (!manualFrame || !frameRect) return null;
  const b = frameRect.getBounds();
  return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
}

el("manualframe").addEventListener("change", () => {
  manualFrame = el("manualframe").checked;
  if (!frameRect) return;
  if (manualFrame) {
    frameRect.options.pmIgnore = false;
    L.PM.reInitLayer(frameRect);
    frameRect.setStyle({ color: "#e07b00", interactive: true });
    frameRect.pm.enable({ allowSelfIntersection: false });
  } else {
    if (frameRect.pm) frameRect.pm.disable();
    frameRect.options.pmIgnore = true;
    frameRect.setStyle({ color: "#666", interactive: false });
    updateFrame(); // назад к автоматической рамке
  }
});

function setBoundary(layer) {
  if (boundary && boundary !== layer) map.removeLayer(boundary);
  boundary = layer;
  el("generate").disabled = !boundary;
  el("loadlabels").disabled = !boundary;
  if (layer) {
    ["pm:edit", "pm:dragend", "pm:markerdragend", "pm:vertexremoved"]
      .forEach((ev) => layer.on(ev, updateFrame));
  }
  updateFrame();
}

/* --- импорт DXF --- */
fetch("/api/dxf_crs").then((r) => r.json()).then((list) => {
  const sel = el("dxfcrs");
  list.forEach((c) => {
    const o = document.createElement("option");
    o.value = c.id;
    o.textContent = c.title;
    sel.appendChild(o);
  });
});

el("dxffile").addEventListener("change", () => {
  el("dxfload").disabled = !el("dxffile").files.length;
});

el("dxfload").addEventListener("click", async () => {
  const f = el("dxffile").files[0];
  if (!f) return;
  const status = el("status");
  status.className = "";
  status.textContent = "Читаю DXF…";
  el("dxfload").disabled = true;
  try {
    const fd = new FormData();
    fd.append("file", f);
    fd.append("crs", el("dxfcrs").value);
    fd.append("axes", el("dxfaxes").value);
    const resp = await fetch("/api/import_dxf", { method: "POST", body: fd });
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
    const data = await resp.json();
    const latlngs = data.coords.map((c) => [c[1], c[0]]);
    const layer = L.polygon(latlngs, {
      color: "#0099ff", weight: 3, fillOpacity: 0.05,
    }).addTo(map);
    layer.on("pm:remove", dropBoundary);
    setBoundary(layer);
    map.fitBounds(layer.getBounds().pad(0.3));
    status.className = "ok";
    status.textContent = "Контур загружен. " + data.note;
  } catch (err) {
    status.className = "err";
    status.textContent = "Ошибка: " + err.message;
  } finally {
    el("dxfload").disabled = !el("dxffile").files.length;
  }
});

/* --- надписи --- */
// параметры видов надписей (мм на листе) приходят с сервера
let kindInfo = {};
fetch("/api/label_kinds").then((r) => r.json()).then((list) => {
  list.forEach((k) => { kindInfo[k.id] = k; });
  const sel = el("newlabelkind");
  list.forEach((k) => {
    const o = document.createElement("option");
    o.value = k.id;
    o.textContent = k.title;
    sel.appendChild(o);
  });
});

/* своя надпись: добавляется в центр рамки (или экрана) */
el("addlabel").addEventListener("click", () => {
  const name = el("newlabeltext").value.trim();
  if (!name) { el("newlabeltext").focus(); return; }
  const center = frameRect ? frameRect.getBounds().getCenter()
                           : map.getCenter();
  const m = addLabelMarker({
    name, lat: center.lat, lon: center.lng,
    angle: 0, kind: el("newlabelkind").value,
  });
  el("newlabeltext").value = "";
  openLabelEditor(m);
});

// область листа под карту, мм (как в docgen)
const PAGE_IMG_W_MM = 165, PAGE_IMG_H_MM = 207;

function labelFontPx(kind) {
  /* размер шрифта на экране такой, каким он будет на листе:
     рамка кадра на экране = ширина картинки на листе */
  const info = kindInfo[kind];
  if (!info || !frameRect) return 14;
  const b = frameRect.getBounds();
  const p1 = map.latLngToContainerPoint(b.getNorthWest());
  const p2 = map.latLngToContainerPoint(b.getSouthEast());
  const wPx = Math.abs(p2.x - p1.x), hPx = Math.abs(p2.y - p1.y);
  if (!wPx) return 14;
  const dispWmm = Math.min(PAGE_IMG_W_MM, PAGE_IMG_H_MM * (wPx / hPx));
  const pxPerMm = wPx / dispWmm;
  const scale = parseFloat(el("labelscale").value) || 1;
  return Math.max(6, info.mm * scale * pxPerMm);
}

function refreshLabelSizes() {
  labelMarkers.forEach((m) => {
    const span = m.getElement() && m.getElement().querySelector("span");
    if (span) span.style.fontSize = labelFontPx(m._label.kind).toFixed(1) + "px";
  });
}

function clearLabels() {
  labelMarkers.forEach((m) => map.removeLayer(m));
  labelMarkers = [];
}

function makeLabelIcon(lab) {
  // подпись центрируется на точке — ровно как при отрисовке на сервере
  return L.divIcon({
    className: "",
    html:
      '<span class="map-label k-' + lab.kind +
      '" style="position:absolute;left:0;top:0;' +
      "font-size:" + labelFontPx(lab.kind).toFixed(1) + "px;" +
      "transform:translate(-50%,-50%) rotate(" + (-lab.angle) + 'deg)">' +
      lab.name.replace(/&/g, "&amp;").replace(/</g, "&lt;") + "</span>",
    iconSize: null,
  });
}

function removeLabelMarker(m) {
  map.closePopup();
  map.removeLayer(m);
  labelMarkers = labelMarkers.filter((x) => x !== m);
}

/* редактор надписи: текст, поворот, категория, удаление */
function openLabelEditor(m) {
  const lab = m._label;
  const box = document.createElement("div");
  box.className = "label-editor";

  const txt = document.createElement("input");
  txt.type = "text";
  txt.value = lab.name;
  txt.addEventListener("input", () => {
    lab.name = txt.value;
    m.setIcon(makeLabelIcon(lab));
  });

  const angleRow = document.createElement("div");
  angleRow.className = "angle-row";
  const angleVal = document.createElement("span");
  angleVal.textContent = lab.angle + "°";
  const rng = document.createElement("input");
  rng.type = "range";
  rng.min = -90; rng.max = 90; rng.step = 1;
  rng.value = lab.angle;
  rng.addEventListener("input", () => {
    lab.angle = parseFloat(rng.value);
    angleVal.textContent = lab.angle + "°";
    m.setIcon(makeLabelIcon(lab));
  });
  angleRow.append("Поворот:", rng, angleVal);

  const kindSel = document.createElement("select");
  Object.values(kindInfo).forEach((k) => {
    const o = document.createElement("option");
    o.value = k.id;
    o.textContent = k.title;
    if (k.id === lab.kind) o.selected = true;
    kindSel.appendChild(o);
  });
  kindSel.addEventListener("change", () => {
    lab.kind = kindSel.value;
    m.setIcon(makeLabelIcon(lab));
  });

  const del = document.createElement("button");
  del.className = "del";
  del.textContent = "Удалить надпись";
  del.addEventListener("click", () => {
    map.closePopup();
    removeLabelMarker(m);
  });

  box.append(txt, angleRow, kindSel, del);
  L.popup({ closeButton: true, autoClose: true, offset: [0, -10] })
    .setLatLng(m.getLatLng())
    .setContent(box)
    .openOn(map);
}

function addLabelMarker(lab) {
  const m = L.marker([lab.lat, lab.lon], {
    icon: makeLabelIcon(lab), draggable: true, zIndexOffset: 1000,
  }).addTo(map);
  m._label = lab;
  m.on("click", () => openLabelEditor(m));
  m.on("dblclick", () => removeLabelMarker(m));
  labelMarkers.push(m);
  return m;
}

map.on("zoomend", refreshLabelSizes);
el("labelscale").addEventListener("input", () => {
  el("labelscaleval").textContent =
    parseFloat(el("labelscale").value).toFixed(1);
  refreshLabelSizes();
});

el("loadlabels").addEventListener("click", async () => {
  if (!boundary) return;
  const kinds = [...document.querySelectorAll("#labelkinds input:checked")]
    .map((c) => c.value);
  const status = el("status");
  status.className = "";
  status.textContent = "Запрашиваю надписи (OSM/Overpass)…";
  el("loadlabels").disabled = true;
  try {
    const coords = boundary.getLatLngs()[0].map((p) => [p.lng, p.lat]);
    const resp = await fetch("/api/labels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ coords, kinds, frame: frameBBox() }),
    });
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
    clearLabels();
    const labs = await resp.json();
    labs.forEach(addLabelMarker);
    status.className = "ok";
    status.textContent = "Надписей: " + labs.length +
      ". Перетащите как нужно, лишние — двойной клик.";
  } catch (err) {
    status.className = "err";
    status.textContent = "Ошибка: " + err.message;
  } finally {
    el("loadlabels").disabled = !boundary;
  }
});

function dropBoundary() {
  boundary = null;
  el("generate").disabled = true;
  el("loadlabels").disabled = true;
  updateFrame();
}

map.on("pm:create", (e) => {
  setBoundary(e.layer);
  e.layer.on("pm:remove", dropBoundary);
});
map.on("pm:remove", (e) => {
  if (e.layer === boundary) dropBoundary();
  // надпись удалили «корзиной» — выкидываем её и из списка
  if (labelMarkers.includes(e.layer)) {
    labelMarkers = labelMarkers.filter((x) => x !== e.layer);
  }
  // рамку случайно удалили «корзиной» — восстанавливаем автоматическую
  if (e.layer === frameRect) {
    frameRect = null;
    manualFrame = false;
    el("manualframe").checked = false;
    updateFrame();
  }
});

/* только надписи, реально присутствующие на карте */
function activeLabels() {
  labelMarkers = labelMarkers.filter((m) => map.hasLayer(m));
  return labelMarkers;
}

/* --- генерация --- */
function triggerDownload(file) {
  // скачиваем сразу после генерации (файл уже сохранён на сервере)
  const a = document.createElement("a");
  a.href = "/api/download/" + encodeURIComponent(file);
  a.download = file;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

el("generate").addEventListener("click", async () => {
  if (!boundary) return;
  const latlngs = boundary.getLatLngs()[0];
  const coords = latlngs.map((p) => [p.lng, p.lat]);
  const status = el("status");
  const btn = el("generate");
  const btnText = btn.textContent;
  status.className = "busy";
  status.textContent = "Формирую документ…";
  btn.textContent = "Формирую…";
  btn.disabled = true;
  try {
    const resp = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        coords,
        basemap: el("basemap").value,
        territory: el("territory").value.trim(),
        annex_no: el("annex").value.trim(),
        open_word: el("openword").checked,
        object_type: el("objtype").value,
        north_arrow: el("northarrow").checked,
        frame: frameBBox(),
        label_scale: parseFloat(el("labelscale").value) || 1,
        labels: activeLabels().map((m) => ({
          name: m._label.name,
          lat: m.getLatLng().lat,
          lon: m.getLatLng().lng,
          angle: m._label.angle,
          kind: m._label.kind,
        })),
      }),
    });
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
    const data = await resp.json();
    triggerDownload(data.file);
    status.className = "ok";
    status.innerHTML =
      "✓ Готово — документ скачан. " +
      "<a href=\"/api/download/" + encodeURIComponent(data.file) +
      "\" download>скачать ещё раз</a>";
  } catch (err) {
    status.className = "err";
    status.textContent = "Ошибка: " + err.message;
  } finally {
    btn.textContent = btnText;
    btn.disabled = !boundary;
  }
});
