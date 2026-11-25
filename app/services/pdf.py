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


def _tbl(rows, widths, size=8.5):
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8ECF1")), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                           ("FONTSIZE", (0, 0), (-1, -1), size), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def company_report(res: dict, company_name: str = "") -> bytes:
    """Board-ready summary of one company screen. Built from the in-memory analysis; nothing is saved."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch, topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            title="Supply exposure screen", author="Critical Material Supply Exposure Index (CMSEI)")
    st = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=st["Heading1"], fontSize=17, spaceAfter=3)
    h2 = ParagraphStyle("h2", parent=st["Heading2"], fontSize=11.5, spaceBefore=9, spaceAfter=3)
    body = ParagraphStyle("b", parent=st["BodyText"], fontSize=9.2, leading=12.5)
    small = ParagraphStyle("s", parent=st["BodyText"], fontSize=7.8, leading=10, textColor=colors.HexColor("#444444"))
    cell = ParagraphStyle("c", parent=body, fontSize=8.2, leading=10)
    s = res["summary"]
    P = lambda t, style=cell: Paragraph(_esc(t), style)
    money = lambda v: f"${v:,.0f}"
    els = [Paragraph("Supply exposure screen" + (f": {_esc(company_name)}" if company_name else ""), h1),
           Paragraph(f"Scores as of data vintage {_esc(res['as_of'])}. Generated {_esc(__import__('datetime').date.today().isoformat())}. "
                     f"Status: preview. Market-level scores applied to your parts list.", small)]
    if s["headline"]:
        els += [Spacer(1, 6), Paragraph("<b>" + _esc(s["headline"]) + "</b>", body)]
    els.append(Paragraph(f"{s['mapped_rows']} of {s['rows']} parts matched to a tracked material across {s['products']} products and {s['suppliers']} suppliers."
                         + (f" Spend on matched parts {money(s['spend_mapped'])} of {money(s['spend_total'])}." if s["has_spend"] else ""), body))
    if res["indicative_materials"]:
        els.append(Paragraph("Indicative data (grade C) behind: " + _esc(", ".join(res["indicative_materials"])) + ". Treat these as screening only.", small))
    els.append(Paragraph("Most exposed products", h2))
    rows = [["Product", "Score", "Tier", "Driver", "Parts", "Spend in High/Critical"]]
    for p in res["products"][:10]:
        rows.append([P(p["name"]), p["score"], p["tier"], P(p["driver_name"]), f"{p['high_parts']}/{p['dependent_parts']}",
                     "" if p["spend_high_share"] is None else f"{p['spend_high_share'] * 100:.0f}%"])
    els.append(_tbl(rows, [2.0 * inch, 0.5 * inch, 0.8 * inch, 1.5 * inch, 0.6 * inch, 1.1 * inch]))
    els.append(Paragraph("Suppliers carrying the most exposure", h2))
    rows = [["Supplier", "Score", "Tier", "Driver", "Parts", "Spend"]]
    for p in res["suppliers"][:10]:
        rows.append([P(p["name"]), p["score"], p["tier"], P(p["driver_name"]), p["dependent_parts"], money(p["spend"]) if p["spend"] else ""])
    els.append(_tbl(rows, [2.0 * inch, 0.5 * inch, 0.8 * inch, 1.5 * inch, 0.6 * inch, 1.1 * inch]))
    els.append(Paragraph("Materials in your parts list", h2))
    rows = [["Material", "Market score", "Tier", "Parts", "Origin declared dominant / other / not declared"]]
    for m in res["materials"]:
        rows.append([P(m["name"]), m["score"], m["tier"], m["parts"], f"{m['declared_dominant']} / {m['declared_other']} / {m['undeclared']}"])
    els.append(_tbl(rows, [1.9 * inch, 0.9 * inch, 0.8 * inch, 0.6 * inch, 2.3 * inch]))
    if res["compliance"]:
        els.append(Paragraph("Compliance screening (not legal advice)", h2))
        for c in res["compliance"]:
            cn = c["counts"]
            line = (f"<b>{_esc(c['title'])}</b> ({_esc(c['regime'])}). Applies to you: {_esc(c['applies'])}. {c['parts_in_scope']} parts in scope; "
                    f"declared in a covered country: {cn['declared_covered']}; country not declared: {cn['undeclared']}.")
            els.append(Paragraph(line, body))
            for u in c["upcoming"]:
                els.append(Paragraph(f"Date to know: {_esc(u['date'])} ({u['days']} days). {_esc(u['what'])}", small))
    sc_ = res.get("scenario")
    if sc_:
        els.append(Paragraph(f"What-if: {_esc(sc_['material_name'])} supply cut" + (f" ({_esc(sc_['country'])})" if sc_["country"] else ""), h2))
        els.append(Paragraph(f"Market score {sc_['market_before']['score']} ({sc_['market_before']['tier']}) becomes {sc_['market_after']['score']} ({sc_['market_after']['tier']}). "
                             f"Parts directly affected: {sc_['parts']['direct']}; origin not declared: {sc_['parts']['unknown']}; declared elsewhere: {sc_['parts']['other']}.", body))
        if sc_["cost"]:
            c = sc_["cost"]
            els.append(Paragraph(f"With your assumed price rise of {c['price_shock_pct']:g}%: {money(c['low'])} to {money(c['high'])} a year. {_esc(c['note'])}", body))
        els.append(Paragraph(_esc(sc_["note"]), small))
    els.append(Paragraph("How to read this", h2))
    els.append(Paragraph(_esc(res["method"]) + " The market scores are not validated as predictors; the back-test is published on the Validation page. "
                         f"Maintainer: {_esc(settings.maintainer_name)}.", small))
    els.append(Spacer(1, 4))
    els.append(Paragraph(DISCLAIMER, small))
    doc.build(els)
    return buf.getvalue()
