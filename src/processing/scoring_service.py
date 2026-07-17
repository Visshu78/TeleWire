import os
import logging
import requests

logger = logging.getLogger(__name__)


def calculate_risk_score(data: dict, db=None) -> float:
    """
    Calculate a composite threat risk score from 0 to 100.
    """
    score = 0.0
    
    # Load settings coefficients if database is provided
    w_scam = 1.0
    w_violence = 1.0
    w_cyber = 1.0
    b_crypto = 15.0
    
    if db:
        try:
            w_scam = float(db.get_setting("weight_scam", "1.0"))
            w_violence = float(db.get_setting("weight_violence", "1.0"))
            w_cyber = float(db.get_setting("weight_cyber", "1.0"))
            b_crypto = float(db.get_setting("bonus_crypto_presence", "15.0"))
        except Exception:
            pass

    # 1. Sanctioned wallet addresses (+40 points per wallet)
    entities = data.get("entities", [])
    has_crypto = False
    if entities:
        for ent in entities:
            if ent.get("is_sanctioned") == 1:
                score += 40.0
            if ent.get("type", "").startswith("crypto_") or ent.get("entity_type", "").startswith("crypto_"):
                has_crypto = True

    # 1b. Crypto presence bonus
    if has_crypto:
        score += b_crypto

    # 2. Threat category (+20 to +30 points multiplied by category weights)
    threat = data.get("threat_category", "Benign")
    if threat in ["Drugs", "Weapons/Violent Extremism", "Drug Trafficking"]:
        score += 30.0 * w_violence
    elif threat in ["Cybersecurity/Hacking", "Hacking"]:
        score += 25.0 * w_cyber
    elif threat in ["Money Mule", "Financial Crimes/Money Mule", "Scam", "Scam/Fraud"]:
        score += 20.0 * w_scam

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


def dispatch_alerts(data: dict, score: float, db=None) -> None:
    """
    Dispatch real-time alerts if threat score crosses the threshold.
    Queries database settings first, falling back to environment variables.
    """
    threshold_str = None
    webhook_url = None
    tg_token = None
    tg_chat_id = None
    
    if db:
        threshold_str = db.get_setting("alert_threshold")
        webhook_url = db.get_setting("alert_webhook_url")
        tg_token = db.get_setting("alert_telegram_bot_token")
        tg_chat_id = db.get_setting("alert_telegram_chat_id")
        
    if not threshold_str:
        threshold_str = os.getenv("ALERT_THRESHOLD", "70.0")
    if not webhook_url:
        webhook_url = os.getenv("ALERT_WEBHOOK_URL")
    if not tg_token:
        tg_token = os.getenv("ALERT_TELEGRAM_BOT_TOKEN")
    if not tg_chat_id:
        tg_chat_id = os.getenv("ALERT_TELEGRAM_CHAT_ID")

    try:
        threshold = float(threshold_str)
    except (ValueError, TypeError):
        threshold = 70.0

    if score < threshold:
        return

    logger.warning("CRITICAL THREAT ALERT [Score %.1f]: Message %d (Group: %s) exceeded threshold!", score, data.get("message_id", 0), data.get("group_name", ""))

    # 1. Webhook Alert
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

