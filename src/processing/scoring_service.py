import os
import logging
import requests

logger = logging.getLogger(__name__)


def calculate_risk_score(data: dict) -> float:
    """
    Calculate a composite threat risk score from 0 to 100.
    """
    score = 0.0
    
    # 1. Sanctioned wallet addresses (+40 points per wallet)
    entities = data.get("entities", [])
    if entities:
        for ent in entities:
            if ent.get("is_sanctioned") == 1:
                score += 40.0

    # 2. Threat category (+20 to +30 points)
    threat = data.get("threat_category", "Benign")
    if threat in ["Drugs", "Weapons/Violent Extremism", "Drug Trafficking"]:
        score += 30.0
    elif threat in ["Cybersecurity/Hacking", "Hacking"]:
        score += 25.0
    elif threat in ["Money Mule", "Financial Crimes/Money Mule", "Scam", "Scam/Fraud"]:
        score += 20.0

    # 3. Fuzzy match keyword threshold proximity (up to +15 points)
    if data.get("is_matched"):
        fuzzy = data.get("fuzzy_score", 0.0)
        score += (fuzzy / 100.0) * 15.0

    # 4. Campaign clustering (+10 points)
    if data.get("campaign_id"):
        score += 10.0

    # 5. Urgency heuristics (+10 points)
    text = (data.get("text", "") or "").lower()
    ocr = (data.get("ocr_text", "") or "").lower()
    combined = f"{text}\n{ocr}"
    urgency_terms = ["urgent", "immediately", "right now", "asap", "hurry", "action required", "release lock", "release package"]
    if any(term in combined for term in urgency_terms):
        score += 10.0

    return min(100.0, score)


def dispatch_alerts(data: dict, score: float) -> None:
    """
    Dispatch real-time alerts if threat score crosses the threshold.
    """
    try:
        threshold = float(os.getenv("ALERT_THRESHOLD", "70.0"))
    except ValueError:
        threshold = 70.0

    if score < threshold:
        return

    logger.warning("CRITICAL THREAT ALERT [Score %.1f]: Message %d (Group: %s) exceeded threshold!", score, data.get("message_id", 0), data.get("group_name", ""))

    # 1. Webhook Alert
    webhook_url = os.getenv("ALERT_WEBHOOK_URL")
    if webhook_url:
        payload = {
            "event": "threat_alert",
            "score": score,
            "message_id": data.get("message_id"),
            "group_id": data.get("group_id"),
            "group_name": data.get("group_name"),
            "sender_name": data.get("sender_name"),
            "text": data.get("text"),
            "threat_category": data.get("threat_category"),
            "media_path": data.get("media_path"),
            "ocr_text": data.get("ocr_text"),
            "qr_codes": data.get("qr_codes")
        }
        try:
            requests.post(webhook_url, json=payload, timeout=5)
            logger.info("Webhook alert dispatched successfully to %s", webhook_url)
        except Exception as exc:
            logger.error("Failed to dispatch Webhook alert: %s", exc)

    # 2. Telegram Bot Alert
    tg_token = os.getenv("ALERT_TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.getenv("ALERT_TELEGRAM_CHAT_ID")
    if tg_token and tg_chat_id:
        alert_text = f"*⚠️ CRITICAL THREAT ALERT [Score {score:.1f}]*\n\n" \
                     f"*Group:* {data.get('group_name')} (`{data.get('group_id')}`)\n" \
                     f"*Sender:* {data.get('sender_name') or 'Unknown'}\n" \
                     f"*Category:* {data.get('threat_category') or 'Benign'}\n" \
                     f"*Text:* {data.get('text') or '[No text]'}\n"
        if data.get("ocr_text"):
            alert_text += f"*OCR:* {data.get('ocr_text')}\n"
        
        url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        payload = {
            "chat_id": tg_chat_id,
            "text": alert_text,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, json=payload, timeout=5)
            logger.info("Telegram Bot alert dispatched successfully to chat %s", tg_chat_id)
        except Exception as exc:
            logger.error("Failed to dispatch Telegram Bot alert: %s", exc)
