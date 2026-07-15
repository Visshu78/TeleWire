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
