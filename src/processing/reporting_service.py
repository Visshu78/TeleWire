import datetime


def compile_intelligence_brief(case_details: dict) -> str:
    """
    Compile a beautifully formatted Markdown executive brief summarizing the case metrics and details.
    """
    title = case_details.get("title", "Unnamed Case")
    desc = case_details.get("description", "No description provided.")
    created = case_details.get("created_at", "Unknown")
    items = case_details.get("items", [])
    
    # Aggregated Stats
    total_items = len(items)
    messages_count = sum(1 for i in items if i["item_type"] == "message")
    wallets_count = sum(1 for i in items if i["item_type"] == "wallet")
    actors_count = sum(1 for i in items if i["item_type"] == "actor")
    
    # Calculate average / max risk of messages in case
    risk_scores = []
    for i in items:
        if i["item_type"] == "message" and "message_details" in i:
            score = i["message_details"].get("risk_score")
            if score is not None:
                risk_scores.append(score)
    
    avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0.0
    max_risk = max(risk_scores) if risk_scores else 0.0
    
    # Risk Assessment Level
    if avg_risk >= 80:
        overall_risk = "CRITICAL"
    elif avg_risk >= 60:
        overall_risk = "HIGH"
    elif avg_risk >= 30:
        overall_risk = "MEDIUM"
    else:
        overall_risk = "LOW"
        
    brief = f"""# Executive Intelligence Brief: {title}

**Generated At:** {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}
**Case Established:** {created}
**Overall Case Risk Assessment:** `{overall_risk}` (Average Message Threat Score: {avg_risk:.1f}/100, Peak: {max_risk:.1f}/100)

---

## 1. Executive Summary
{desc}

---

## 2. Item Inventory Statistics
- **Total Case Items:** {total_items}
- **Ingested Threat Messages:** {messages_count}
- **Tracked Crypto Wallet Addresses:** {wallets_count}
- **Monitored Threat Actor Handles:** {actors_count}

---

## 3. Case Details

"""

    # Group items by type
    messages = [i for i in items if i["item_type"] == "message"]
    wallets = [i for i in items if i["item_type"] == "wallet"]
    actors = [i for i in items if i["item_type"] == "actor"]
    
    if messages:
        brief += "### Ingested Threat Messages\n"
        for m in messages:
            md = m.get("message_details") or {}
            sender = md.get("sender_name") or "Unknown"
            grp = md.get("group_name") or "Unknown"
            ts = md.get("timestamp", "—")
            score = md.get("risk_score", 0.0)
            text = md.get("text", "[No text content]")
            brief += f"- **[{ts}] {sender} inside {grp} (Risk Score: {score:.0f}):**\n"
            brief += f"  > {text}\n\n"
            
    if wallets:
        brief += "### Tracked Crypto Wallet Addresses\n"
        for w in wallets:
            brief += f"- **Address:** `{w['item_value']}` (Added: {w['added_at']})\n"
        brief += "\n"
        
    if actors:
        brief += "### Monitored Threat Actor Handles\n"
        for a in actors:
            brief += f"- **Actor Handle:** `{a['item_value']}` (Added: {a['added_at']})\n"
        brief += "\n"
        
    brief += """
---
*Confidentiality Notice: This report contains compiled intelligence profiles intended solely for authorized personnel.*
"""
    return brief


def compile_case_briefing_html(case_details: dict) -> str:
    """
    Compile a beautifully styled HTML intelligence dossier for printing/saving as PDF.
    Auto-triggers the system print dialog in the client browser.
    """
    import html
    title = html.escape(case_details.get("title", "Unnamed Case"))
    desc = html.escape(case_details.get("description", "No description provided."))
    created = html.escape(case_details.get("created_at", "Unknown"))
    items = case_details.get("items", [])

    total_items = len(items)
    messages = [i for i in items if i["item_type"] == "message"]
    wallets = [i for i in items if i["item_type"] == "wallet"]
    actors = [i for i in items if i["item_type"] == "actor"]

    # Calculate risk statistics
    risk_scores = []
    for m in messages:
        md = m.get("message_details") or {}
        score = md.get("risk_score")
        if score is not None:
            risk_scores.append(score)

    avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0.0
    max_risk = max(risk_scores) if risk_scores else 0.0

    if avg_risk >= 80:
        overall_risk, risk_color = "CRITICAL", "#ef4444"
    elif avg_risk >= 60:
        overall_risk, risk_color = "HIGH", "#f97316"
    elif avg_risk >= 30:
        overall_risk, risk_color = "MEDIUM", "#eab308"
    else:
        overall_risk, risk_color = "LOW", "#22c55e"

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Render threat messages rows
    msg_rows = ""
    for m in messages:
        md = m.get("message_details") or {}
        sender = html.escape(md.get("sender_name") or "Unknown")
        grp = html.escape(md.get("group_name") or "Unknown")
        ts = html.escape(md.get("timestamp", "—"))
        score = md.get("risk_score", 0.0)
        category = html.escape(md.get("threat_category") or "—")
        text = html.escape(md.get("text" or ""))
        
        # Color score
        score_cls = "risk-high" if score >= 70 else "risk-medium" if score >= 40 else "risk-low"
        
        msg_rows += f"""
        <tr>
            <td style="white-space:nowrap;">{ts}</td>
            <td><strong>{sender}</strong></td>
            <td>{grp}</td>
            <td><span class="badge-pill">{category}</span></td>
            <td><span class="{score_cls}">{score:.0f}</span></td>
            <td class="msg-text-cell">{text}</td>
        </tr>
        """

    # Render wallet rows
    wallet_rows = ""
    for w in wallets:
        addr = html.escape(w['item_value'])
        added = html.escape(w['added_at'])
        wallet_rows += f"""
        <tr>
            <td style="font-family: monospace; font-size:12px; font-weight:600;">{addr}</td>
            <td>{added}</td>
        </tr>
        """

    # Render actor rows
    actor_rows = ""
    for a in actors:
        handle = html.escape(a['item_value'])
        added = html.escape(a['added_at'])
        actor_rows += f"""
        <tr>
            <td style="font-family: monospace; font-size:12px; color: #8b5cf6; font-weight:600;">{handle}</td>
            <td>{added}</td>
        </tr>
        """

    html_out = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Case Briefing - {title}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        body {{
            font-family: 'Inter', sans-serif;
            color: #334155;
            background: #fff;
            margin: 0;
            padding: 40px;
            line-height: 1.5;
            font-size: 14px;
        }}
        .report-container {{
            max-width: 900px;
            margin: 0 auto;
        }}
        .header {{
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .title {{
            font-size: 28px;
            font-weight: 800;
            color: #0f172a;
            margin: 0;
            letter-spacing: -0.5px;
        }}
        .meta-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-top: 15px;
            font-size: 12px;
            color: #64748b;
        }}
        .meta-val {{
            color: #334155;
            font-weight: 500;
        }}
        .risk-badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            color: #fff;
            font-weight: 700;
            font-size: 11px;
            background: {risk_color};
            text-transform: uppercase;
        }}
        .summary-box {{
            background: #f8fafc;
            border-left: 4px solid #8b5cf6;
            padding: 15px;
            border-radius: 0 8px 8px 0;
            margin-bottom: 30px;
        }}
        .summary-box h3 {{
            margin-top: 0;
            margin-bottom: 6px;
            font-size: 14px;
            color: #0f172a;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 35px;
        }}
        .stat-card {{
            background: #f1f5f9;
            padding: 12px;
            border-radius: 6px;
            text-align: center;
        }}
        .stat-val {{
            font-size: 20px;
            font-weight: 700;
            color: #0f172a;
        }}
        .stat-label {{
            font-size: 11px;
            color: #64748b;
            text-transform: uppercase;
        }}
        h2 {{
            font-size: 18px;
            color: #0f172a;
            margin-top: 30px;
            margin-bottom: 12px;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 6px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 25px;
            font-size: 13px;
        }}
        th {{
            background: #f8fafc;
            text-align: left;
            padding: 8px 12px;
            color: #475569;
            font-weight: 600;
            border-bottom: 1px solid #cbd5e1;
        }}
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid #f1f5f9;
            vertical-align: top;
        }}
        .risk-high {{ color: #ef4444; font-weight: 700; }}
        .risk-medium {{ color: #f97316; font-weight: 700; }}
        .risk-low {{ color: #22c55e; font-weight: 700; }}
        .badge-pill {{
            background: #f3e8ff;
            color: #6b21a8;
            padding: 1px 6px;
            border-radius: 12px;
            font-size: 10px;
            font-weight: 600;
        }}
        .msg-text-cell {{
            font-family: inherit;
            color: #475569;
            white-space: pre-wrap;
            max-width: 350px;
            word-break: break-all;
        }}
        .notice {{
            margin-top: 50px;
            font-size: 11px;
            color: #94a3b8;
            text-align: center;
            border-top: 1px dashed #cbd5e1;
            padding-top: 15px;
            font-style: italic;
        }}
        @media print {{
            body {{ padding: 20px; }}
            .summary-box {{ background: #f8fafc !important; -webkit-print-color-adjust: exact; }}
            .stat-card {{ background: #f1f5f9 !important; -webkit-print-color-adjust: exact; }}
            th {{ background: #f8fafc !important; -webkit-print-color-adjust: exact; }}
            .badge-pill {{ background: #f3e8ff !important; -webkit-print-color-adjust: exact; }}
            .notice {{ page-break-after: avoid; }}
        }}
    </style>
</head>
<body>
    <div class="report-container">
        <div class="header">
            <div class="title">📄 TeleWire Intelligence Dossier</div>
            <div class="meta-grid">
                <div>Case Title: <span class="meta-val">{title}</span></div>
                <div>Generated: <span class="meta-val">{now_str}</span></div>
                <div>Case Established: <span class="meta-val">{created}</span></div>
                <div>Risk Assessment: <span class="risk-badge">{overall_risk}</span></div>
            </div>
        </div>

        <div class="summary-box">
            <h3>Executive Summary</h3>
            {desc}
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-val">{total_items}</div>
                <div class="stat-label">Total Items</div>
            </div>
            <div class="stat-card">
                <div class="stat-val">{len(messages)}</div>
                <div class="stat-label">Messages</div>
            </div>
            <div class="stat-card">
                <div class="stat-val">{len(wallets)}</div>
                <div class="stat-label">Crypto Wallets</div>
            </div>
            <div class="stat-card">
                <div class="stat-val">{len(actors)}</div>
                <div class="stat-label">Monitored Senders</div>
            </div>
        </div>

        {"<h2>Ingested Threat Messages</h2>" if messages else ""}
        {"<table><thead><tr><th>Time</th><th>Sender</th><th>Group</th><th>Threat Class</th><th>Risk</th><th>Message Text</th></tr></thead><tbody>" if messages else ""}
        {msg_rows}
        {"</tbody></table>" if messages else ""}

        {"<h2>Tracked Crypto Wallets</h2>" if wallets else ""}
        {"<table><thead><tr><th>Wallet Address</th><th>Added To Case At</th></tr></thead><tbody>" if wallets else ""}
        {wallet_rows}
        {"</tbody></table>" if wallets else ""}

        {"<h2>Monitored Senders</h2>" if actors else ""}
        {"<table><thead><tr><th>Actor Handle / ID</th><th>Added To Case At</th></tr></thead><tbody>" if actors else ""}
        {actor_rows}
        {"</tbody></table>" if actors else ""}

        <div class="notice">
            Confidentiality Notice: This document contains compiled intelligence logs harvested from encrypted networks. Restricted solely for law enforcement and authorized agency operations.
        </div>
    </div>

    <script>
        window.onload = function() {{
            setTimeout(function() {{
                window.print();
            }}, 500);
        }};
    </script>
</body>
</html>
"""
    return html_out
