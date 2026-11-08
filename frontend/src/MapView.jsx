import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";
import { layers, namedFlavor } from "@protomaps/basemaps";
import { patientName } from "./Schedule.jsx";
// MapLibre draws in a Web Worker, its own file; ?url has Vite copy it into the build and give its address.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

// The map of the day: the streets come from this computer (the planner serves data/map), never from the
// internet, so where the nurse's patients are is never sent anywhere. nyc.pmtiles holds the streets of
// Brooklyn and Manhattan; MapLibre reads it a piece at a time through the pmtiles:// protocol.
maplibregl.setWorkerUrl(workerUrl);
maplibregl.addProtocol("pmtiles", new Protocol().tile);

const BROOKLYN = [-73.95, 40.65];
const dark = window.matchMedia("(prefers-color-scheme: dark)");

function style(flavor) {
  const here = window.location.origin;
  return {
    version: 8,
    glyphs: `${here}/map-data/fonts/{fontstack}/{range}.pbf`,
    sprite: `${here}/map-data/sprites/v4/${flavor}`,
    sources: {
      protomaps: {
        type: "vector",
        url: `pmtiles://${here}/map-data/nyc.pmtiles`,
        attribution: '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap</a>',
      },
    },
    layers: layers("protomaps", namedFlavor(flavor), { lang: "en" }),
  };
}

const flavor = () => (dark.matches ? "dark" : "light");
const ROUTE_COLOR = { light: "#0f766e", dark: "#2dd4bf" };

// The route along the streets, one line per leg, drawn over the streets (again after the style changes).
// By subway and bus, one line per segment: walking dashed, each train or bus in its route's colour.
function features(plan) {
  if (plan.transit) {
    return plan.transit.flatMap((trip, leg) =>
      trip.filter((part) => part.line.length > 1).map((part) => ({
        type: "Feature",
        properties: { leg, mode: part.mode, color: part.color ?? null },
        geometry: { type: "LineString", coordinates: part.line },
      })),
    );
  }
  return plan.route.map((line, leg) => ({
    type: "Feature",
    properties: { leg, mode: "street" },
    geometry: { type: "LineString", coordinates: line },
  }));
}

function drawRoute(map, plan) {
  for (const id of ["route-ride", "route-walk", "route-line", "route-casing"]) if (map.getLayer(id)) map.removeLayer(id);
  if (map.getSource("route")) map.removeSource("route");
  if (!plan?.route.length) return;
  map.addSource("route", { type: "geojson", data: { type: "FeatureCollection", features: features(plan) } });
  const lineJoin = { "line-join": "round", "line-cap": "round" };
  const walk = ["==", ["get", "mode"], "walk"];
  map.addLayer({
    id: "route-casing", type: "line", source: "route", layout: lineJoin, filter: ["!", walk],
    paint: { "line-color": flavor() === "dark" ? "#0b0f14" : "#ffffff", "line-width": 8, "line-opacity": 0.9 },
  });
  map.addLayer({
    id: "route-line", type: "line", source: "route", layout: lineJoin, filter: ["==", ["get", "mode"], "street"],
    paint: { "line-color": ROUTE_COLOR[flavor()], "line-width": 4.5 },
  });
  map.addLayer({
    id: "route-walk", type: "line", source: "route", filter: walk,
    layout: { "line-join": "round" },
    paint: { "line-color": flavor() === "dark" ? "#c8ced8" : "#5d6778", "line-width": 3, "line-dasharray": [1, 1.5] },
  });
  map.addLayer({
    id: "route-ride", type: "line", source: "route", layout: lineJoin,
    filter: ["all", ["!", walk], ["!=", ["get", "mode"], "street"]],
    paint: { "line-color": ["coalesce", ["get", "color"], ROUTE_COLOR[flavor()]], "line-width": 5 },
  });
}

// A popup's lines, as text: names and addresses come from the nurse's list, so they are never read as HTML.
function popup(lines) {
  const box = document.createElement("div");
  lines.forEach((text, i) => {
    const line = document.createElement(i === 0 ? "strong" : "div");
    line.textContent = text;
    box.append(line);
  });
  return new maplibregl.Popup({ offset: 16, closeButton: false }).setDOMContent(box);
}

function marker(className, text, place, lines) {
  const element = document.createElement("div");
  element.className = `marker ${className}`;
  element.textContent = text;
  return new maplibregl.Marker({ element }).setLngLat([place.lon, place.lat]).setPopup(popup(lines));
}

// The markers for a plan: home, each visit numbered in order, and the patients not visited, in grey.
function markersFor(plan) {
  const markers = [];
  const byId = Object.fromEntries(plan.patients.map((patient) => [patient.id, patient]));
  const stops = Object.fromEntries((plan.schedule?.stops ?? []).map((stop) => [stop.patient, stop]));
  for (const patient of plan.patients) {
    if (!patient.place || plan.order.includes(patient.id)) continue;
    markers.push(marker("skipped", "", patient.place, [patientName(patient), patient.place.address, "Not visited tomorrow"]));
  }
  plan.order.forEach((id, i) => {
    const patient = byId[id];
    if (!patient?.place) return;
    const stop = stops[id];
    const when = stop ? `${stop.start}–${stop.finish}${stop.late ? " (late)" : ""}` : "";
    markers.push(marker(stop?.late ? "visit late" : "visit", String(i + 1), patient.place,
                        [`${i + 1}. ${patientName(patient)}`, patient.place.address, when, patient.place.note].filter(Boolean)));
  });
  if (plan.home) {
    const times = plan.schedule ? `Leave ${plan.schedule.leave}, back ${plan.schedule.back}` : "";
    markers.push(marker("home", "⌂", plan.home, ["Home", plan.home.address, times]));
  }
  return markers;
}

export default function MapView({ plan }) {
  const container = useRef(null);
  const map = useRef(null);
  const planRef = useRef(plan); // the plan to draw again when the style changes

  useEffect(() => {
    const m = new maplibregl.Map({
      container: container.current,
      style: style(flavor()),
      center: BROOKLYN,
      zoom: 11,
      maxBounds: [[-74.3, 40.45], [-73.6, 41.0]], // a little beyond the streets the map holds
      attributionControl: { compact: true },
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("style.load", () => drawRoute(m, planRef.current));
    const followTheme = () => m.setStyle(style(flavor()));
    dark.addEventListener("change", followTheme);
    map.current = m;
    return () => {
      dark.removeEventListener("change", followTheme);
      m.remove();
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    planRef.current = plan;
    if (!m) return;
    if (m.isStyleLoaded()) drawRoute(m, plan); // no plan: takes the last route away
    if (!plan) return;
    const markers = markersFor(plan);
    markers.forEach((each) => each.addTo(m));
    // Show the whole day: home, every patient found, and the route.
    const points = [
      ...plan.route.flat(),
      ...[plan.home, ...plan.patients.map((patient) => patient.place)].filter(Boolean).map((p) => [p.lon, p.lat]),
    ];
    if (points.length) {
      const bounds = points.reduce((box, point) => box.extend(point), new maplibregl.LngLatBounds(points[0], points[0]));
      m.fitBounds(bounds, { padding: 60, maxZoom: 16, duration: 600 });
    }
    return () => markers.forEach((each) => each.remove());
  }, [plan]);

  return <div ref={container} className="map" />;
}
