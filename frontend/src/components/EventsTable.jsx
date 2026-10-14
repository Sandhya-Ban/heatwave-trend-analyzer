import { useState } from "react";

const fmt = (v, d) => (v == null ? "" : typeof v === "number" && d != null ? v.toFixed(d) : String(v));

/** Columns, sort key and title come from the backend so every hazard renders correctly. */
export default function EventsTable({ events, columns, sortKey }) {
  const [all, setAll] = useState(false);
  if (!events.length) return <p className="muted">No events met the definition in this period.</p>;
  const sorted = [...events].sort((a, b) => (b[sortKey] ?? 0) - (a[sortKey] ?? 0) || String(b.start).localeCompare(String(a.start)));
  const rows = all ? sorted : sorted.slice(0, 10);
  return (
    <>
      <div className="table-scroll">
        <table>
          <thead><tr>{columns.map((c) => <th key={c.key} className={c.digits != null ? "n" : ""}>{c.label}</th>)}</tr></thead>
          <tbody>
            {rows.map((e, i) => (
              <tr key={`${e.start}-${i}`}>{columns.map((c) => <td key={c.key} className={c.digits != null ? "n" : ""}>{fmt(e[c.key], c.digits)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      {sorted.length > 10 && <button className="link" onClick={() => setAll(!all)}>{all ? "Show the top 10" : `Show all ${sorted.length}`}</button>}
    </>
  );
}
