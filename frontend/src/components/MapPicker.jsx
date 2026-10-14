import { useEffect, useRef } from "react";
import L from "leaflet";
import { themeFor } from "../theme.js";

/** Click to drop a point (point mode) or click two opposite corners (box mode). */
export default function MapPicker({ region, onPoint, onBox, hazard = "heatwave" }) {
  const el = useRef(null), map = useRef(null), layer = useRef(null), corner = useRef(null);
  const modeRef = useRef(region.mode), cb = useRef({ onPoint, onBox });
  modeRef.current = region.mode;
  cb.current = { onPoint, onBox };
  // Pin and box outlines follow the hazard accent. Refs hold the map objects so the
  // setup effect (empty deps) is not re-run just because the hazard changed.
  const accent = themeFor(hazard).accent;
  const accentRef = useRef(accent);
  accentRef.current = accent;

  useEffect(() => {
    map.current = L.map(el.current, { center: [22, 79], zoom: 4, worldCopyJump: false, minZoom: 2 });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 12, attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    map.current.on("click", (e) => {
      const lat = +e.latlng.lat.toFixed(3), lon = +((((e.latlng.lng + 180) % 360) + 360) % 360 - 180).toFixed(3);
      if (modeRef.current === "point") { cb.current.onPoint(lat, lon); return; }
      if (!corner.current) { corner.current = [lat, lon]; layer.current.clearLayers(); L.circleMarker([lat, lon], { radius: 5, color: accentRef.current }).addTo(layer.current); return; }
      const [a, b] = [corner.current, [lat, lon]];
      corner.current = null;
      cb.current.onBox(Math.min(a[0], b[0]), Math.max(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[1], b[1]));
    });
    return () => { map.current.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    corner.current = null;
  }, [region.mode]);

  useEffect(() => {
    if (!map.current) return;
    layer.current.clearLayers();
    const n = (v) => (v === "" || v == null ? NaN : Number(v));
    const c = accentRef.current;
    if (region.mode === "point") {
      const lat = n(region.lat), lon = n(region.lon);
      if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
        L.circleMarker([lat, lon], { radius: 8, color: "#fff", weight: 2, fillColor: c, fillOpacity: 1 }).addTo(layer.current);
        map.current.setView([lat, lon], Math.max(map.current.getZoom(), 6));
      }
    } else {
      const v = [n(region.minLat), n(region.maxLat), n(region.minLon), n(region.maxLon)];
      if (v.every(Number.isFinite) && v[0] < v[1] && v[2] < v[3]) {
        const r = L.rectangle([[v[0], v[2]], [v[1], v[3]]], { color: c, weight: 2, fillOpacity: 0.12 }).addTo(layer.current);
        map.current.fitBounds(r.getBounds(), { maxZoom: 8, padding: [20, 20] });
      }
    }
  }, [region, accent]);   // accent repaints the marker when the hazard changes

  return <div ref={el} className="map" role="application" aria-label="Map: click to choose a location" />;
}
