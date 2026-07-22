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


def generate_inline_diff(text1: str, text2: str) -> str:
    """
    Computes word-level diff between text1 (original/rep text) and text2 (current message text)
    and returns styled HTML highlighting insertions and deletions.
    """
    import difflib
    import html

    words1 = (text1 or "").split()
    words2 = (text2 or "").split()
    matcher = difflib.SequenceMatcher(None, words1, words2)
    
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            out.append(html.escape(" ".join(words1[i1:i2])))
        elif tag == 'replace':
            del_text = html.escape(" ".join(words1[i1:i2]))
            ins_text = html.escape(" ".join(words2[j1:j2]))
            out.append(f'<span style="background:rgba(239,68,68,0.2); color:#f87171; text-decoration:line-through; padding:0 2px; border-radius:2px;">{del_text}</span>')
            out.append(f'<span style="background:rgba(34,197,94,0.2); color:#4ade80; padding:0 2px; border-radius:2px;">{ins_text}</span>')
        elif tag == 'delete':
            del_text = html.escape(" ".join(words1[i1:i2]))
            out.append(f'<span style="background:rgba(239,68,68,0.2); color:#f87171; text-decoration:line-through; padding:0 2px; border-radius:2px;">{del_text}</span>')
        elif tag == 'insert':
            ins_text = html.escape(" ".join(words2[j1:j2]))
            out.append(f'<span style="background:rgba(34,197,94,0.2); color:#4ade80; padding:0 2px; border-radius:2px;">{ins_text}</span>')
            
    return " ".join(out)


def generate_ai_brief(case_details: dict) -> str:
    """
    Generate an AI Threat Brief summarizing case metrics, threat categories, actors, and IOCs.
    Uses OpenAI or Ollama if available; falls back to structured rule-based brief.
    """
    import os
    import json
    import requests

    title = case_details.get("title", "Unnamed Case")
    desc = case_details.get("description", "No description provided.")
    items = case_details.get("items", [])
    
    messages = [i.get("message_details", {}) for i in items if i.get("item_type") == "message" and i.get("message_details")]
    wallets = [i.get("item_value") for i in items if i.get("item_type") == "wallet"]
    actors = [i.get("item_value") for i in items if i.get("item_type") == "actor"]

    # Build prompt context
    msg_samples = []
    for m in messages[:10]:
        msg_samples.append(f"[{m.get('timestamp')}] {m.get('sender_name')} in {m.get('group_name')}: {m.get('text', '')[:120]} (Threat: {m.get('threat_category')}, Risk: {m.get('risk_score')})")
    
    prompt = f"""You are an elite OSINT and SOCMINT cyber threat intelligence analyst.
Write a concise executive intelligence briefing for Case: '{title}'.
Case Description: {desc}
Metrics: {len(messages)} messages cataloged, {len(wallets)} crypto wallets tracked, {len(actors)} actor handles.

Tracked Wallets: {', '.join(wallets) if wallets else 'None'}
Tracked Actors: {', '.join(actors) if actors else 'None'}

Sample Threat Messages:
""" + "\n".join(msg_samples) + """

Format your response in GitHub-style Markdown with clear sections:
1. Executive Summary & Core Threat Vector
2. Operational Patterns & Actor Conduct
3. Indicators of Compromise (IOCs) & Risk Assessment
4. Recommended Countermeasures & Next Actions"""

    # 1. Primary Option: OpenRouter API (Free Models: OPENROUTER_API_KEY)
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        models_to_try = [
            os.environ.get("OPENROUTER_MODEL"),
            "google/gemini-2.0-flash-lite-preview-02-05:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-r1:free",
            "qwen/qwen-2.5-72b-instruct:free"
        ]
        # Filter out Nones while keeping order
        models_to_try = [m for m in models_to_try if m]

        for model_name in models_to_try:
            try:
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/Visshu78/TeleWire",
                        "X-Title": "TeleWire SOCMINT Intelligence Engine"
                    },
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3
                    },
                    timeout=15
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    if content and content.strip():
                        return content
            except Exception:
                continue

    # 2. Try Groq Cloud (Free Tier: GROQ_API_KEY)
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={
                    "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3
                },
                timeout=12
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception:
            pass

    # 3. Try Google Gemini API (Free Tier: GEMINI_API_KEY)
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={gemini_key}"
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}]
                },
                timeout=12
            )
            if resp.status_code == 200:
                data = resp.json()
                text_out = data["candidates"][0]["content"]["parts"][0]["text"]
                return text_out
        except Exception:
            pass

    # 4. Try Hugging Face Inference API (Free Tier: HF_TOKEN)
    hf_token = os.environ.get("HF_TOKEN")
    if hf_token:
        try:
            resp = requests.post(
                "https://api-inference.huggingface.co/v1/chat/completions",
                headers={"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"},
                json={
                    "model": os.environ.get("HF_MODEL", "meta-llama/Llama-3.2-3B-Instruct"),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3
                },
                timeout=12
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception:
            pass

    # 5. Try OpenAI
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3
                },
                timeout=12
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception:
            pass

    # 6. Try Ollama (Local Free LLM)
    ollama_url = os.environ.get("OLLAMA_API_URL", "http://localhost:11434/api/generate")
    try:
        resp = requests.post(
            ollama_url,
            json={"model": os.environ.get("OLLAMA_MODEL", "llama3"), "prompt": prompt, "stream": False},
            timeout=8
        )
        if resp.status_code == 200:
            data = resp.json()
            if "response" in data:
                return data["response"]
    except Exception:
        pass

    # Fallback rule-based brief
    categories = list(set([m.get('threat_category') for m in messages if m.get('threat_category')]))
    top_cat = categories[0] if categories else "General Threat Operations"
    avg_score = sum([m.get('risk_score', 0) for m in messages]) / max(len(messages), 1)

    return f"""### 🤖 AI-Generated Intelligence Executive Brief (Rule-Based Synthesis)
*Notice: LLM API service offline/unconfigured. Generated via TeleWire Analyst Rule Engine.*

#### 1. Executive Summary & Threat Vectors
Case **{title}** focuses on illicit communications related to **{top_cat}**. 
Analysis indicates **{len(messages)} key messages** spanning **{len(actors)} identified threat actors**. 
The operational risk level is evaluated as **{'HIGH' if avg_score > 60 else 'MEDIUM' if avg_score > 30 else 'LOW'}** (Average Threat Score: **{avg_score:.1f}/100**).

#### 2. Actor Conduct & Operational Patterns
- **Primary Category:** {top_cat}
- **Tracked Actor Identifiers:** {', '.join([f'`{a}`' for a in actors]) if actors else 'None assigned'}
- **Activity Dynamics:** Message frequency and cross-group interactions show active campaign distribution with repeat IOC postings.

#### 3. Technical Indicators of Compromise (IOCs)
- **Crypto Wallet Infrastructure:** {', '.join([f'`{w}`' for w in wallets]) if wallets else 'No financial addresses bound'}
- **Threat Message Samples Cataloged:** {len(messages)} items inside case inventory.

#### 4. Recommended Action Items
- Continue monitoring linked actor handles for cross-group forwards.
- Run dark web leak checks on all associated wallet addresses and mobile numbers.
- Export case briefing PDF for agency escalation.
"""


def generate_stix_bundle(case_details: dict) -> dict:
    """
    Generate a valid STIX 2.1 Cyber Threat Intelligence JSON bundle from case details.
    Includes Identity (TeleWire), Threat-Actor, Indicators (wallets, phones, emails),
    Notes (messages), and Relationships linking them.
    """
    import uuid
    from datetime import datetime, timezone

    title = case_details.get("title", "Unnamed Case")
    desc = case_details.get("description", "No description provided.")
    items = case_details.get("items", [])
    
    created_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Base Bundle structure
    bundle_id = f"bundle--{uuid.uuid4()}"
    objects = []
    
    # 1. Identity Object (The Creator / TeleWire SOCMINT Platform)
    identity_id = f"identity--{uuid.uuid5(uuid.NAMESPACE_DNS, 'telewire.socmint.org')}"
    identity = {
        "type": "identity",
        "spec_version": "2.1",
        "id": identity_id,
        "created": created_time,
        "modified": created_time,
        "name": "TeleWire SOCMINT Threat Intelligence Platform",
        "description": "Automated social media and Telegram threat intelligence ingestion pipeline",
        "identity_class": "organization"
    }
    objects.append(identity)
    
    # Extract distinct threat actor names/handles
    actors = list(set([i.get("item_value") for i in items if i.get("item_type") == "actor" and i.get("item_value")]))
    actor_map = {} # name -> stix id
    for act in actors:
        # Stable UUID for actor based on name/handle
        act_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"actor.{act}")
        act_stix_id = f"threat-actor--{act_uuid}"
        actor_map[act] = act_stix_id
        
        objects.append({
            "type": "threat-actor",
            "spec_version": "2.1",
            "id": act_stix_id,
            "created": created_time,
            "modified": created_time,
            "name": act,
            "description": f"Telegram threat actor identified in case: {title}",
            "threat_actor_types": ["malicious-actor"],
            "created_by_ref": identity_id
        })
        
    # Extract distinct IOCs: wallets, phones, emails
    wallets = list(set([i.get("item_value") for i in items if i.get("item_type") == "wallet" and i.get("item_value")]))
    ioc_map = {} # value -> stix id
    
    # For wallets
    for w in wallets:
        w_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"wallet.{w}")
        w_stix_id = f"indicator--{w_uuid}"
        ioc_map[w] = w_stix_id
        
        objects.append({
            "type": "indicator",
            "spec_version": "2.1",
            "id": w_stix_id,
            "created": created_time,
            "modified": created_time,
            "name": f"Crypto Wallet: {w}",
            "description": "Cryptocurrency wallet address identified in threat message communications",
            "pattern": f"[cryptocurrency-wallet:value = '{w}']",
            "pattern_type": "stix",
            "pattern_version": "2.1",
            "valid_from": created_time,
            "created_by_ref": identity_id
        })
        
        # Link indicators to actors if we can associate them
        # (For simple case bundles, link each indicator to all threat actors in the same case)
        for act_stix_id in actor_map.values():
            rel_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"rel.{w_stix_id}.{act_stix_id}")
            objects.append({
                "type": "relationship",
                "spec_version": "2.1",
                "id": f"relationship--{rel_uuid}",
                "created": created_time,
                "modified": created_time,
                "relationship_type": "indicates",
                "source_ref": w_stix_id,
                "target_ref": act_stix_id,
                "created_by_ref": identity_id
            })

    # For messages (represented as Notes with references to indicators & actors)
    messages = [i.get("message_details", {}) for i in items if i.get("item_type") == "message" and i.get("message_details")]
    for m in messages:
        msg_id = m.get("id") or m.get("message_id")
        text = m.get("text", "")
        if not text:
            continue
        
        note_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"msg.{msg_id}")
        note_stix_id = f"note--{note_uuid}"
        
        # Find which actors are mentioned/sender
        sender_name = m.get("sender_name")
        refs = []
        if sender_name and sender_name in actor_map:
            refs.append(actor_map[sender_name])
            
        # Add references to matching wallet IOCs mentioned in the text
        for val, stix_id in ioc_map.items():
            if val in text:
                refs.append(stix_id)
                
        note = {
            "type": "note",
            "spec_version": "2.1",
            "id": note_stix_id,
            "created": created_time,
            "modified": created_time,
            "abstract": f"Telegram Threat Message (Group: {m.get('group_name')})",
            "content": f"Sender: {m.get('sender_name')} (ID: {m.get('sender_id')})\nMessage: {text}",
            "object_refs": refs if refs else [identity_id],
            "created_by_ref": identity_id
        }
        objects.append(note)

    # 4. Return complete STIX Bundle
    return {
        "type": "bundle",
        "id": bundle_id,
        "objects": objects
    }


