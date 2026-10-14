"""CSV / PDF exports built from a stored analysis document."""
from __future__ import annotations

import csv
import io
from xml.sax.saxutils import escape

def _cell(v):
    if v is None:
        return ""
    if isinstance(v, str) and v[:1] in "=+-@\t\r":   # CSV/formula-injection guard (our fields are numeric/ISO dates)
        return "'" + v
    return v


def to_csv(doc: dict, kind: str) -> str:
    cols, rows = ([c["key"] for c in doc["event_columns"]], doc["events"]) if kind == "events" else (doc["yearly_columns"], doc["yearly"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([_cell(r.get(c)) for c in cols])
    return buf.getvalue()


def to_pdf(doc: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    st = getSampleStyleSheet()
    reg, pr = doc.get("region", {}), doc["params"]
    out = io.BytesIO()
    pdf = SimpleDocTemplate(out, pagesize=A4, title=f"{doc['hazard_label']} trend report", leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    el = [Paragraph(f"{doc['hazard_label']} trend report", st["Title"]),
          Paragraph(escape(f"Location: {reg.get('lat')}, {reg.get('lon')}  |  Years {pr['start_year']}-{pr['end_year']}  |  {doc['definition']}"), st["Normal"]),
          Paragraph(escape(f"Source: {doc['meta']['source']}"), st["Normal"]), Spacer(1, 10), Paragraph("Insights", st["Heading2"])]
    for ins in doc["insights"]:
        el.append(Paragraph(escape(ins["text"]), st["BodyText"]))
    el += [Spacer(1, 8), Paragraph("Yearly summary", st["Heading2"])]
    mk = doc["main_metric"]
    hdr = ["Year", "Events", doc["main_label"], "Coverage", "Used in trend"]
    data = [hdr] + [[r["year"], r["events"], r[mk], f"{r['coverage']:.0%}", "yes" if r["reliable"] else "no"]
                    for r in doc["yearly"]]
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("ALIGN", (1, 1), (-1, -1), "RIGHT")]))
    el.append(t)
    pdf.build(el)
    return out.getvalue()
