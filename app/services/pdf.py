"""One-page PDF report for a material (reportlab). Carries the snapshot id and hash so it can be checked later."""
from __future__ import annotations
import io
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from ..engine import scoring as sc
from ..config import settings

DISCLAIMER = ("CMSEI (Critical Material Supply Exposure Index) is an informational, market-level screening view built from public data. "
              "It does not describe any company, supplier or individual, and it is not sourcing, legal, financial or investment advice. "
              "Scores are estimates that depend on published data of varying age and quality, and on modeling choices described on the "
              "Methodology page. Do not rely on a score alone to make a purchasing or compliance decision.")


def _esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def material_report(m: dict, snap: dict, recs: list | None = None, scenario_label: str | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch, topMargin=0.7 * inch,
                            bottomMargin=0.7 * inch, title=f"Exposure report: {m['name']}", author="Critical Material Supply Exposure Index (CMSEI)")
    st = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=st["Heading1"], fontSize=18, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=st["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=st["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=st["BodyText"], fontSize=8, leading=10.5, textColor=colors.HexColor("#444444"))
    u = snap["uncertainty"]
    els = [Paragraph(_esc(m["name"]) + " — supply exposure", h1),
           Paragraph("Market-level index, identical for every user. Preview data; see status below.", small), Spacer(1, 6)]
    els.append(Paragraph(f"<b>Score {snap['score']} / 100 — {snap['tier']}</b> (range {u['range_low']} to {u['range_high']})", ParagraphStyle(
        "big", parent=body, fontSize=14, leading=18)))
    if u.get("provisional_sources"):
        els.append(Paragraph(f"No other producer has been verified as an alternate source, so none earns credit. If all "
                             f"{u['provisional_sources']} listed producers were credited the score would be "
                             f"{u['provisional_credit_composite']} ({u['provisional_credit_tier']}).", body))
    rows = [["Measure", "Value"],
            ["Concentration", f"{snap['components']['concentration']} / 100"],
            ["Processing-stage risk", f"{snap['components']['processing_risk']} / 100"],
            ["Substitution difficulty", f"{snap['components']['substitution_difficulty']} / 100"],
            ["Geopolitical condition", f"{snap['components']['geopolitical_multiplier']}x"],
            ["Data grade", f"{snap['data_grade']} ({'Indicative' if snap['data_grade'] == 'C' else 'reviewed source'})"]]
    t = Table(rows, colWidths=[2.6 * inch, 3.8 * inch])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8ECF1")), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                           ("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    els += [Spacer(1, 6), t]
    els.append(Paragraph("Largest producers (world production, 2023)", h2))
    prod = ", ".join(f"{_esc(x['country'])} {x['share']:.0f}%" for x in m["production"]["shares"][:5])
    els.append(Paragraph(prod, body))
    els.append(Paragraph("Main US import sources (2019-22)", h2))
    imp = ", ".join(f"{_esc(x['country'])} {x['share']:.0f}%" for x in m["import"]["shares"])
    els.append(Paragraph(imp + f" (other {m['import']['other_share']:.0f}%)", body))
    if recs:
        els.append(Paragraph("Suggested next steps" + (f" ({_esc(scenario_label)})" if scenario_label else ""), h2))
        for r in recs:
            els.append(Paragraph("• " + _esc(r["text"]) + f" <i>[Rule {r['rule_id']}. {_esc(r['guidance_basis'])}]</i>", body))
    els.append(Paragraph("Sources", h2))
    for c in snap["citations"]:
        els.append(Paragraph("• " + _esc(c["label"]) + " — " + _esc(c.get("url") or ""), small))
    els.append(Paragraph("Reproducibility", h2))
    els.append(Paragraph(f"Snapshot {snap['snapshot_id']}, formula v{snap['formula_version']}, taxonomy {_esc(snap['taxonomy_version'])}, "
                         f"data {_esc(snap['data_as_of'])}, published {snap['published_at']}. Payload hash {snap['payload_hash']}. "
                         f"Verify at {_esc(settings.base_url)}/api/v1/snapshots/{snap['snapshot_id']}/verify", small))
    els.append(Paragraph("Status: preview. Figures were transcribed from USGS tables through a page reader and have not been checked against the PDFs by a person. "
                         "The backtests published with this project found the index does not beat world-production concentration alone.", small))
    els.append(Spacer(1, 6))
    els.append(Paragraph(DISCLAIMER, small))
    doc.build(els)
    return buf.getvalue()
