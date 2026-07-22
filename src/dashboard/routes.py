"""
src/dashboard/routes.py
-------------------------------------------------------------
All Flask routes: API + page + export endpoints.

Changes vs v1:
  - datetime_from / datetime_to replace date_from / date_to everywhere.
    Accepts both 'YYYY-MM-DD' and 'YYYY-MM-DDTHH:MM' formats so the
    UI time-range picker can send full precision.
  - /api/pipeline/health endpoint for dashboard health panel.
  - Backward-compatible: old 'date_from' / 'date_to' params still work
    (the UI sends 'datetime_from' / 'datetime_to', but old clients are safe).
-------------------------------------------------------------
"""

import os
import logging
import asyncio
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request, send_file, render_template, send_from_directory

from .exporter import export_csv, export_excel
from src.processing.network_service import NetworkAnalyzer

logger = logging.getLogger(__name__)
bp = Blueprint("main", __name__)


def _db():
    return current_app.config["DB_HANDLER"]

def _group_cache():
    return current_app.config.get("GROUP_CACHE")

def _get_dt_param(name: str, legacy_name: str = None) -> str | None:
    """Read a datetime param, falling back to legacy name if needed."""
    v = request.args.get(name) or None
    if v is None and legacy_name:
        v = request.args.get(legacy_name) or None
    return v


def _parse_list_params():
    """Parse comma-separated or multiple keyword/group_id parameters."""
    keyword_param = request.args.getlist("keyword")
    if not keyword_param:
        kw_val = request.args.get("keyword")
        keyword_param = [kw_val] if kw_val else []
    keywords = []
    for k in keyword_param:
        if k:
            keywords.extend([x.strip() for x in k.split(",") if x.strip()])
    keyword = keywords if keywords else None

    group_id_param = request.args.getlist("group_id")
    if not group_id_param:
        grp_val = request.args.get("group_id")
        group_id_param = [grp_val] if grp_val else []
    group_ids = []
    for g in group_id_param:
        if g:
            for x in g.split(","):
                try:
                    group_ids.append(int(x.strip()))
                except ValueError:
                    pass
    group_id = group_ids if group_ids else None
    
    return keyword, group_id


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

@bp.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Messages API
# ---------------------------------------------------------------------------

@bp.route("/api/messages")
def api_messages():
    db = _db()
    keyword, group_id = _parse_list_params()
    dow_val = request.args.get("dow")
    hour_val = request.args.get("hour")
    request_dow = int(dow_val) if (dow_val is not None and dow_val != "") else None
    request_hour = int(hour_val) if (hour_val is not None and hour_val != "") else None

    result = db.get_messages(
        keyword=keyword,
        group_id=group_id,
        datetime_from=_get_dt_param("datetime_from", "date_from"),
        datetime_to=_get_dt_param("datetime_to", "date_to"),
        matched_only=request.args.get("matched_only", "false").lower() == "true",
        page=request.args.get("page", 1, type=int),
        page_size=request.args.get("page_size", 50, type=int),
        sender_name=request.args.get("sender_name") or None,
        fetched_by=request.args.get("fetched_by") or None,
        request_dow=request_dow,
        request_hour=request_hour,
        q=request.args.get("q") or None,
    )

    # Attach entities for each message
    for msg in result["messages"]:
        msg["entities"] = db.get_message_entities(msg["id"])
    return jsonify(result)

@bp.route("/api/messages/<int:msg_id>/translate")
def api_translate_message(msg_id):
    db = _db()
    msg = db.get_message_by_row_id(msg_id)
    if not msg:
        return jsonify({"error": "Message not found"}), 404
    text = msg.get("text", "")
    if not text:
        return jsonify({"translated_text": ""})
    try:
        from deep_translator import GoogleTranslator
        translated = GoogleTranslator(source='auto', target='en').translate(text)
        return jsonify({"translated_text": translated})
    except Exception as exc:
        logger.error("Translation failed for message %d: %s", msg_id, exc)
@bp.route("/api/messages/detail/<int:msg_id>")
def api_message_detail(msg_id):
    db = _db()
    msg = db.get_message_by_row_id(msg_id)
    if not msg:
        return jsonify({"error": "Message not found"}), 404
    msg["entities"] = db.get_message_entities(msg_id)
    return jsonify(msg)


@bp.route("/api/messages/<int:msg_id>/similar")
def api_similar_messages(msg_id):
    db = _db()
    msg = db.get_message_by_row_id(msg_id)
    if not msg or not msg.get("text"):
        return jsonify([])
    try:
        from src.processing.semantic_service import SemanticProcessor
        proc = SemanticProcessor(db_handler=db)
        results = proc.search_similar_messages(msg["text"], limit=10)
        return jsonify(results)
    except Exception as exc:
        logger.error("api_similar_messages failed for %d: %s", msg_id, exc)
        return jsonify([])


@bp.route("/api/messages/<int:msg_id>/diff")
def api_message_diff(msg_id):
    db = _db()
    msg = db.get_message_by_row_id(msg_id)
    if not msg or not msg.get("campaign_id") or not msg.get("text"):
        return jsonify({"has_diff": False, "diff_html": ""})
    try:
        from src.storage.database import get_db
        with get_db(db.db_path) as conn:
            camp = conn.execute("SELECT representative_text FROM campaigns WHERE campaign_id = ?", (msg["campaign_id"],)).fetchone()
            if not camp or not camp["representative_text"]:
                return jsonify({"has_diff": False, "diff_html": ""})
            
            rep_text = camp["representative_text"]
            msg_text = msg["text"]
            if rep_text.strip() == msg_text.strip():
                return jsonify({"has_diff": False, "diff_html": ""})
            
            from src.processing.reporting_service import generate_inline_diff
            diff_html = generate_inline_diff(rep_text, msg_text)
            return jsonify({"has_diff": True, "diff_html": diff_html, "rep_text": rep_text})
    except Exception as exc:
        logger.error("api_message_diff failed for %d: %s", msg_id, exc)
        return jsonify({"has_diff": False, "diff_html": ""})




@bp.route("/api/wallets/<address>/enrichment")
def api_wallet_enrichment(address):
    enrichment = _db().get_wallet_enrichment(address)
    if enrichment:
        return jsonify(enrichment)
    return jsonify({"error": "No enrichment data available"}), 404


@bp.route("/api/phones/<phone_value>/enrichment")
def api_phone_enrichment(phone_value):
    db = _db()
    enrichment = db.get_phone_enrichment(phone_value)
    if not enrichment:
        # Try to resolve/enrich synchronously on demand if not in DB yet
        try:
            from src.storage.database import get_db
            with get_db(db.db_path) as conn:
                row = conn.execute("SELECT id FROM entities WHERE entity_value = ?", (phone_value.strip(),)).fetchone()
            if row:
                db._enrich_phone_number_obj(row["id"], phone_value)
                enrichment = db.get_phone_enrichment(phone_value)
        except Exception:
            pass
    if enrichment:
        return jsonify(enrichment)
    return jsonify({"error": "No enrichment data available"}), 404


# ---------------------------------------------------------------------------
# Network & Behavioral Intelligence API
# ---------------------------------------------------------------------------

@bp.route("/api/network/graph")
def api_network_graph():
    fetched_by = request.args.get("fetched_by") or None
    mode = request.args.get("mode") or "forwards"
    analyzer = NetworkAnalyzer(_db())
    if mode == "entity_connection":
        graph = analyzer.get_entity_connection_graph(fetched_by=fetched_by)
    else:
        graph = analyzer.get_cytoscape_graph(fetched_by=fetched_by)
    return jsonify(graph)


@bp.route("/api/network/node-details")
def api_network_node_details():
    node_id = request.args.get("id") or ""
    node_type = request.args.get("type") or ""
    db = _db()
    
    if node_type == "actor":
        key = node_id.replace("actor_", "", 1)
        details = db.get_actor_node_details(key)
        return jsonify(details)
    elif node_type == "entity":
        ent_str = node_id.replace("entity_", "", 1)
        try:
            ent_id = int(ent_str)
        except ValueError:
            return jsonify({"error": "Invalid entity ID"}), 400
        details = db.get_entity_node_details(ent_id)
        return jsonify(details)
    else:
        return jsonify({"error": "Unsupported node type for detailed fetch"}), 400


@bp.route("/api/settings", methods=["GET", "POST"])

def api_settings():
    db = _db()
    if request.method == "POST":
        data = request.get_json() or {}
        db.set_setting("alert_threshold", data.get("alert_threshold", "70.0"))
        db.set_setting("alert_webhook_url", data.get("alert_webhook_url", ""))
        db.set_setting("alert_telegram_bot_token", data.get("alert_telegram_bot_token", ""))
        db.set_setting("alert_telegram_chat_id", data.get("alert_telegram_chat_id", ""))
        db.set_setting("weight_scam", data.get("weight_scam", "1.0"))
        db.set_setting("weight_violence", data.get("weight_violence", "1.0"))
        db.set_setting("weight_cyber", data.get("weight_cyber", "1.0"))
        db.set_setting("bonus_crypto_presence", data.get("bonus_crypto_presence", "15.0"))
        return jsonify({"status": "success", "message": "Alert settings saved successfully."})
    else:
        settings = {
            "alert_threshold": db.get_setting("alert_threshold", "70.0"),
            "alert_webhook_url": db.get_setting("alert_webhook_url", ""),
            "alert_telegram_bot_token": db.get_setting("alert_telegram_bot_token", ""),
            "alert_telegram_chat_id": db.get_setting("alert_telegram_chat_id", ""),
            "weight_scam": db.get_setting("weight_scam", "1.0"),
            "weight_violence": db.get_setting("weight_violence", "1.0"),
            "weight_cyber": db.get_setting("weight_cyber", "1.0"),
            "bonus_crypto_presence": db.get_setting("bonus_crypto_presence", "15.0")
        }
        return jsonify(settings)


@bp.route("/api/settings/test-alert", methods=["POST"])
def api_settings_test_alert():
    db = _db()
    from src.processing.scoring_service import dispatch_alerts
    dummy_data = {
        "message_id": 12345,
        "group_id": 99999,
        "group_name": "TeleWire Test Channel",
        "sender_name": "Test Analyst Bot (Unique ID: 8888)",
        "text": "🚨 CRITICAL ALARM INTEGRATION TEST: TeleWire threat detection system webhook and Telegram bot alarms verified successfully. Live connection check active.",
        "threat_category": "Cybersecurity/Hacking"
    }
    dispatch_alerts(dummy_data, score=95.0, db=db)
    return jsonify({"status": "success", "message": "Test alert dispatched to active channels."})


@bp.route("/api/network/cadence")
def api_network_cadence():
    group_id = request.args.get("group_id", type=int)
    fetched_by = request.args.get("fetched_by") or None
    cadence = _db().get_temporal_distribution(group_id, fetched_by=fetched_by)
    return jsonify(cadence)


# ---------------------------------------------------------------------------
# Campaigns API (Phase 2)
# ---------------------------------------------------------------------------

@bp.route("/api/campaigns")
def api_campaigns():
    campaigns = _db().get_campaigns()
    return jsonify(campaigns)


@bp.route("/api/campaigns/<campaign_id>")
def api_campaign_details(campaign_id):
    db = _db()
    messages = db.get_campaign_messages(campaign_id)
    # Attach entities for campaign messages too
    for msg in messages:
        msg["entities"] = db.get_message_entities(msg["id"])
    return jsonify({
        "campaign_id": campaign_id,
        "messages": messages
    })


# ---------------------------------------------------------------------------
# Multimodal Ingestion API (Phase 4)
# ---------------------------------------------------------------------------

@bp.route("/media/<path:filename>")
def serve_media(filename):
    """Securely serve media files from 'data/media/' directory."""
    return send_from_directory(os.path.abspath("data/media"), filename)


@bp.route("/api/media/similar")
def api_similar_images():
    """Find messages with visually similar images by comparing pHash hamming distance."""
    phash = request.args.get("phash")
    if not phash:
        return jsonify({"error": "Missing phash parameter"}), 400
    # Search with default distance threshold 10
    results = _db().get_similar_images(phash, max_distance=10)
    return jsonify(results)


# ---------------------------------------------------------------------------
# Threat Scoring & Alerting API (Phase 5)
# ---------------------------------------------------------------------------

@bp.route("/api/actors/high-risk")
def api_high_risk_actors():
    """Retrieve top malicious actor profiles sorted by cumulative risk score."""
    db = _db()
    limit = request.args.get("limit", default=30, type=int)
    fetched_by = request.args.get("fetched_by") or None
    actors = db.get_high_risk_actors(limit, fetched_by=fetched_by)
    return jsonify(actors)


@bp.route("/api/actors/behavior")
def api_actor_behavior():
    """Retrieve behavioral analysis and fingerprinting stats for a specific actor."""
    actor_id = request.args.get("id", "").strip()
    if not actor_id:
        return jsonify({"error": "Missing actor id"}), 400
    db = _db()
    behavior = db.get_actor_behavior(actor_id)
    return jsonify(behavior)


async def _fetch_telegram_user_profile(client, sender_id: str) -> dict:
    """
    Use Telethon GetFullUserRequest to pull available profile data.
    Only fetches what Telegram exposes given the target's privacy settings.
    Returns a dict with whatever was resolved — empty fields are None.
    """
    from telethon.tl.functions.users import GetFullUserRequest
    from telethon.tl.types import UserStatusOnline, UserStatusOffline, UserStatusRecently
    import os

    profile = {
        "tg_user_id": None,
        "username": None,
        "first_name": None,
        "last_name": None,
        "phone": None,
        "bio": None,
        "is_bot": False,
        "is_verified": False,
        "is_restricted": False,
        "photo_available": False,
        "status": "Unknown",
        "privacy_note": None,
    }

    try:
        # sender_id may be numeric or a username — try numeric first
        try:
            entity_id = int(sender_id)
        except ValueError:
            entity_id = sender_id

        full = await client(GetFullUserRequest(entity_id))
        user = full.users[0] if full.users else None

        if user:
            profile["tg_user_id"] = user.id
            profile["username"] = getattr(user, "username", None)
            profile["first_name"] = getattr(user, "first_name", None)
            profile["last_name"] = getattr(user, "last_name", None)
            profile["is_bot"] = bool(getattr(user, "bot", False))
            profile["is_verified"] = bool(getattr(user, "verified", False))
            profile["is_restricted"] = bool(getattr(user, "restricted", False))
            profile["photo_available"] = user.photo is not None

            # Phone number — only visible if privacy settings allow
            raw_phone = getattr(user, "phone", None)
            if raw_phone:
                profile["phone"] = f"+{raw_phone}" if not str(raw_phone).startswith("+") else raw_phone
            else:
                profile["privacy_note"] = "Phone number hidden by privacy settings"

            # Bio / About text
            if hasattr(full, "full_user") and full.full_user:
                profile["bio"] = getattr(full.full_user, "about", None) or None

            # Online status
            status = getattr(user, "status", None)
            if isinstance(status, UserStatusOnline):
                profile["status"] = "Online"
            elif isinstance(status, UserStatusRecently):
                profile["status"] = "Recently Active"
            elif isinstance(status, UserStatusOffline):
                last = getattr(status, "was_online", None)
                profile["status"] = f"Last seen {last.strftime('%Y-%m-%d %H:%M UTC')}" if last else "Offline"
            else:
                profile["status"] = "Hidden (Long Inactive or Privacy Restricted)"

    except Exception as exc:
        logger.warning("Telethon GetFullUser failed for %s: %s", sender_id, exc)
        profile["privacy_note"] = f"Could not resolve Telegram profile: {exc}"

    return profile


@bp.route("/api/actors/dossier")
def api_actor_dossier():
    """
    On-demand OSINT dossier for a specific actor.
    Combines Telegram GetFullUserRequest profile with all DB-stored IOC intelligence.
    Only runs when explicitly called by the analyst.
    """
    actor_id = request.args.get("id", "").strip()
    if not actor_id:
        return jsonify({"error": "Missing actor id"}), 400
    db = _db()
    sender_name = request.args.get("name", "")


    # Step 1: Pull all internal DB intel
    db_intel = db.get_actor_dossier_db(sender_id=actor_id, sender_name=sender_name)

    # Step 2: Attempt live Telethon profile lookup
    tg_profile = {}
    try:
        manager = current_app.config.get("PIPELINE_MANAGER")
        client = manager.get_first_client() if manager else None
        if client and client.is_connected():
            tg_profile = _run_async(_fetch_telegram_user_profile(client, actor_id))
        else:
            tg_profile = {"privacy_note": "Telegram client not connected — live profile unavailable."}
    except Exception as exc:
        logger.warning("Dossier live profile fetch failed: %s", exc)
        tg_profile = {"privacy_note": f"Live profile lookup error: {exc}"}

    # Step 3: Generate OSINT pivot search URLs (no automated scraping — analyst clicks manually)
    osint_pivots = []
    search_terms = []
    if tg_profile.get("username"):
        search_terms.append(f"@{tg_profile['username']}")
    if sender_name:
        search_terms.append(sender_name)

    for term in search_terms:
        import urllib.parse
        q = urllib.parse.quote_plus(term)
        osint_pivots.extend([
            {"label": f"Google: {term}", "url": f"https://www.google.com/search?q={q}"},
            {"label": f"Twitter/X: {term}", "url": f"https://twitter.com/search?q={q}"},
            {"label": f"Telegram Web: {term}", "url": f"https://t.me/{tg_profile.get('username', '')}"},
        ])
    for phone in db_intel.get("phones_posted", []):
        q = urllib.parse.quote_plus(phone)
        osint_pivots.append({"label": f"Google Phone: {phone}", "url": f"https://www.google.com/search?q={q}"})

    return jsonify({
        "telegram_profile": tg_profile,
        "db_intel": db_intel,
        "osint_pivots": osint_pivots,
    })


@bp.route("/api/map/threat-points")
def api_map_threat_points():
    """
    Returns all geocoded phone and IP entities found in threat messages.
    Queries cached coordinates in a single JOIN (<10ms), geocodes newly discovered
    ones concurrently via thread pool, and saves updates.
    """
    from src.processing.geocoding_service import GeocodingService
    from concurrent.futures import ThreadPoolExecutor
    db = _db()
    geocoder = GeocodingService(db)
    
    points = []
    try:
        # Step 1: Load all already cached/resolved geocode points via single JOIN query
        cached_rows = db.get_cached_threat_points()
        for r in cached_rows:
            risk = r["risk_score"] or 0.0
            threat_level = "Low"
            if risk >= 80:
                threat_level = "Critical"
            elif risk >= 60:
                threat_level = "High"
            elif risk >= 30:
                threat_level = "Medium"
                
            points.append({
                "id": r["id"],
                "type": r["entity_type"],
                "value": r["entity_value"],
                "lat": r["latitude"],
                "lng": r["longitude"],
                "label": f"{r['country'] or 'Unknown'} ({r['city'] or 'Unknown'})" if r['city'] or r['country'] else r['entity_value'],
                "sender_name": r["sender_name"],
                "group_name": r["group_name"],
                "threat_level": threat_level,
                "risk_score": risk
            })
            
        # Step 2: Load any newly discovered, ungeocoded threat points
        ungeocoded = db.get_ungeocoded_threat_points()
        if ungeocoded:
            # Geocode them in parallel using a thread pool (max 10 workers)
            def geocode_worker(r):
                eid = r["id"]
                etype = r["entity_type"]
                evalue = r["entity_value"]
                coords = geocoder.geocode_entity(eid, etype, evalue)
                if coords:
                    lat, lng, country, city = coords
                    risk = r["risk_score"] or 0.0
                    threat_level = "Low"
                    if risk >= 80:
                        threat_level = "Critical"
                    elif risk >= 60:
                        threat_level = "High"
                    elif risk >= 30:
                        threat_level = "Medium"
                    return {
                        "id": eid,
                        "type": etype,
                        "value": evalue,
                        "lat": lat,
                        "lng": lng,
                        "label": f"{country or 'Unknown'} ({city or 'Unknown'})" if city or country else evalue,
                        "sender_name": r["sender_name"],
                        "group_name": r["group_name"],
                        "threat_level": threat_level,
                        "risk_score": risk
                    }
                return None

            with ThreadPoolExecutor(max_workers=10) as executor:
                resolved_results = list(executor.map(geocode_worker, ungeocoded))
                
            # Filter out Nones and append
            for res in resolved_results:
                if res:
                    points.append(res)
                    
    except Exception as exc:
        logger.error("Failed to compile threat points: %s", exc)
        return jsonify({"error": str(exc)}), 500
        
    return jsonify(points)


@bp.route("/api/actors/aliases")
def api_actor_aliases():
    """
    Returns a list of potential aliases for a given threat actor sender name.
    """
    actor_name = request.args.get("id", "").strip()
    if not actor_name:
        return jsonify([])
    db = _db()
    aliases = db.get_actor_aliases(actor_name)
    return jsonify(aliases)


@bp.route("/api/actors/ioc-timeline")
def api_actor_ioc_timeline():
    """
    Returns a chronological sequence of all IOC entities posted by the actor.
    """
    actor_name = request.args.get("id", "").strip()
    if not actor_name:
        return jsonify([])
    db = _db()
    timeline = db.get_actor_ioc_timeline(actor_name)
    return jsonify(timeline)


@bp.route("/api/entities/leak-check")
def api_entities_leak_check():
    """
    Checks if a given entity value hits the Dark Web leak registry catalog.
    """
    val = request.args.get("value", "").strip()
    if not val:
        return jsonify(None)
    db = _db()
    hit = db.lookup_leak_entity(val)
    return jsonify(hit)


@bp.route("/api/war-room/updates")
def api_war_room_updates():
    """
    Retrieves new threat messages since a specific message row ID.
    Used for the real-time SOC War Room console update loop.
    """
    try:
        last_id = int(request.args.get("last_id", "0"))
    except ValueError:
        last_id = 0
    db = _db()
    new_msgs = db.get_messages_since_id(last_id)
    return jsonify(new_msgs)


@bp.route("/api/actors/export-dossier")
def api_export_actor_dossier():
    """
    Renders a print-ready, clean white HTML page of the threat actor's dossier.
    Combines live Telegram metadata and SQLite threat intelligence with dynamic Chart.js rendering.
    """
    actor_id = request.args.get("id", "").strip()
    sender_name = request.args.get("name", "").strip()
    if not actor_id:
        return "Missing threat actor id parameter", 400

    db = _db()
    behavior = db.get_actor_behavior(sender_name if sender_name else actor_id)
    db_intel = db.get_actor_dossier_db(sender_id=actor_id, sender_name=sender_name)

    tg_profile = {}
    try:
        manager = current_app.config.get("PIPELINE_MANAGER")
        client = manager.get_first_client() if manager else None
        if client and client.is_connected():
            tg_profile = _run_async(_fetch_telegram_user_profile(client, actor_id))
        else:
            tg_profile = {"privacy_note": "Telegram client not connected — live profile unavailable."}
    except Exception as exc:
        tg_profile = {"privacy_note": f"Live profile lookup error: {exc}"}

    fullname = [tg_profile.get("first_name"), tg_profile.get("last_name")]
    fullname = " ".join([f for f in fullname if f]) or sender_name or actor_id

    acct_flags = []
    if tg_profile.get("is_bot"):
        acct_flags.append("Bot")
    else:
        acct_flags.append("Human")
    if tg_profile.get("is_verified"):
        acct_flags.append("Verified")
    if tg_profile.get("is_restricted"):
        acct_flags.append("Restricted")
    acct_flags_str = " · ".join(acct_flags)

    risk_tier = db.get_actor_risk_tier(actor_id)


    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return render_template(
        "dossier_print.html",
        actor_id=actor_id,
        resolved_at=now_str,
        risk_tier=risk_tier,
        username=tg_profile.get("username"),
        tg_user_id=tg_profile.get("tg_user_id"),
        phone=tg_profile.get("phone"),
        fullname=fullname,
        status=tg_profile.get("status"),
        acct_flags=acct_flags_str,
        bio=tg_profile.get("bio"),
        privacy_note=tg_profile.get("privacy_note"),
        op_mode=behavior.get("op_mode", "Human Operator"),
        group_count=behavior.get("group_count", 0),
        urgency_bias=f"{behavior.get('urgency_bias', 0.0):.1f}%",
        media_ratio=f"{behavior.get('media_ratio', 0.0):.1f}%",
        timezone_inference=behavior.get("timezone_inference", "Unknown"),
        hour_distribution=behavior.get("hour_distribution", [0]*24),
        categories=behavior.get("categories", {}),
        phones_posted=db_intel.get("phones_posted", []),
        upi_posted=db_intel.get("upi_posted", []),
        emails_posted=db_intel.get("emails_posted", []),
        crypto_posted=db_intel.get("crypto_posted", []),
        groups=db_intel.get("groups", [])
    )



# ---------------------------------------------------------------------------
# Stats API
# ---------------------------------------------------------------------------

@bp.route("/api/stats")
def api_stats():
    fetched_by = request.args.get("fetched_by") or None
    stats = _db().get_stats(
        datetime_from=_get_dt_param("datetime_from", "date_from"),
        datetime_to=_get_dt_param("datetime_to", "date_to"),
        fetched_by=fetched_by,
    )
    return jsonify(stats)


@bp.route("/api/stats/heatmap")
def api_stats_heatmap():
    """Return message counts and avg risk bucketed by day_of_week x hour_of_day."""
    db = _db()
    keyword, group_id = _parse_list_params()
    fetched_by = request.args.get("fetched_by") or None
    try:
        data = db.get_heatmap_data(
            keyword=keyword,
            group_id=group_id,
            datetime_from=_get_dt_param("datetime_from", "date_from"),
            datetime_to=_get_dt_param("datetime_to", "date_to"),
            fetched_by=fetched_by,
        )
        return jsonify(data)
    except Exception as exc:
        logger.error("Heatmap error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/ioc/pivot")
def api_ioc_pivot():
    """Return all messages that contain the given IOC value."""
    db = _db()
    ioc_type  = request.args.get("type")   or None
    ioc_value = request.args.get("value")  or None
    if not ioc_value:
        return jsonify({"error": "Missing value parameter"}), 400
    try:
        results = db.get_ioc_pivot(ioc_type, ioc_value)
        return jsonify(results)
    except Exception as exc:
        logger.error("IOC pivot error: %s", exc)
        return jsonify({"error": str(exc)}), 500



# ---------------------------------------------------------------------------
# Groups API
# ---------------------------------------------------------------------------

@bp.route("/api/groups")
def api_groups():
    return jsonify(_db().get_all_groups())


@bp.route("/api/groups/<int:group_id>/toggle", methods=["POST"])
def api_toggle_group(group_id: int):
    db = _db()
    new_state = db.toggle_group(group_id)
    cache = _group_cache()
    if cache:
        cache.set_active(group_id, new_state)
    return jsonify({"group_id": group_id, "is_active": new_state})


# ---------------------------------------------------------------------------
# Keywords API
# ---------------------------------------------------------------------------

@bp.route("/api/keywords")
def api_keywords():
    return jsonify(_db().get_keywords())


@bp.route("/api/keywords/effectiveness")
def api_keyword_effectiveness():
    return jsonify(_db().get_keyword_effectiveness())


@bp.route("/api/keywords", methods=["POST"])
def api_add_keyword():
    data = request.get_json(force=True, silent=True) or {}
    keyword = (data.get("keyword") or "").strip()
    if not keyword:
        return jsonify({"error": "keyword is required"}), 400
    ok = _db().add_keyword(keyword, source="dashboard")
    return jsonify({"keyword": keyword, "added": ok})


@bp.route("/api/keywords/<path:keyword>", methods=["DELETE"])
def api_delete_keyword(keyword: str):
    ok = _db().delete_keyword(keyword)
    return jsonify({"keyword": keyword, "deleted": ok})


# ---------------------------------------------------------------------------
# Pipeline health API
# ---------------------------------------------------------------------------

@bp.route("/api/pipeline/health")
def api_pipeline_health():
    days = request.args.get("days", 1, type=int)
    health = _db().get_pipeline_health(days=days)
    return jsonify(health)


# ---------------------------------------------------------------------------
# Export (now with datetime precision)
# ---------------------------------------------------------------------------

def _build_filters() -> dict:
    keyword, group_id = _parse_list_params()
    return {
        "keyword":       keyword,
        "group_id":      group_id,
        "datetime_from": _get_dt_param("datetime_from", "date_from"),
        "datetime_to":   _get_dt_param("datetime_to",   "date_to"),
        "matched_only":  request.args.get("matched_only", "false").lower() == "true",
        "fetched_by":    request.args.get("fetched_by") or None,
    }


@bp.route("/export/csv")
def export_csv_route():
    buf = export_csv(_db(), _build_filters())
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    return send_file(buf, mimetype="text/csv", as_attachment=True,
                     download_name=f"telegram_intel_{ts}.csv")


@bp.route("/export/excel")
def export_excel_route():
    buf = export_excel(_db(), _build_filters())
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"telegram_intel_{ts}.xlsx",
    )


# ---------------------------------------------------------------------------
# Cases & Watchlists API (Phase 6)
# ---------------------------------------------------------------------------

@bp.route("/api/cases", methods=["GET", "POST"])
def api_cases():
    db = _db()
    if request.method == "POST":
        data = request.get_json() or {}
        cid = data.get("id")
        title = data.get("title")
        desc = data.get("description", "")
        if not cid or not title:
            return jsonify({"error": "Missing case ID or title"}), 400
        created = datetime.now(timezone.utc).isoformat()
        db.create_case(cid, title, desc, created)
        return jsonify({"status": "created", "id": cid}), 201
    else:
        cases = db.get_cases()
        return jsonify(cases)


@bp.route("/api/cases/<case_id>", methods=["DELETE", "GET"])
def api_case_detail(case_id):
    db = _db()
    if request.method == "DELETE":
        db.delete_case(case_id)
        return jsonify({"status": "deleted"})
    else:
        details = db.get_case_details(case_id)
        if not details:
            return jsonify({"error": "Case not found"}), 404
        return jsonify(details)


@bp.route("/api/cases/<case_id>/items", methods=["POST"])
def api_case_add_item(case_id):
    db = _db()
    data = request.get_json() or {}
    itype = data.get("item_type")
    ivalue = data.get("item_value")
    if not itype or not ivalue:
        return jsonify({"error": "Missing item_type or item_value"}), 400
    added = datetime.now(timezone.utc).isoformat()
    db.add_item_to_case(case_id, itype, str(ivalue), added)
    return jsonify({"status": "item_added"})


@bp.route("/api/cases/items/<int:item_id>", methods=["DELETE"])
def api_case_remove_item(item_id):
    db = _db()
    db.remove_item_from_case(item_id)
    return jsonify({"status": "item_removed"})


@bp.route("/api/cases/<case_id>/report", methods=["GET"])
def api_case_report(case_id):
    db = _db()
    details = db.get_case_details(case_id)
    if not details:
        return jsonify({"error": "Case not found"}), 404
    from src.processing.reporting_service import compile_case_briefing_html
    report_html = compile_case_briefing_html(details)
@bp.route("/api/cases/<case_id>/ai-brief", methods=["POST"])
def api_case_ai_brief(case_id):
    db = _db()
    details = db.get_case_details(case_id)
    if not details:
        return jsonify({"error": "Case not found"}), 404
    from src.processing.reporting_service import generate_ai_brief
    brief_md = generate_ai_brief(details)
    return jsonify({"ai_brief": brief_md})


@bp.route("/api/keywords/effectiveness", methods=["GET"])
def api_keywords_effectiveness():
    db = _db()
    from src.storage.database import get_db
    try:
        with get_db(db.db_path) as conn:
            kws = conn.execute("SELECT keyword FROM keywords ORDER BY keyword ASC").fetchall()
            results = []
            for kw_row in kws:
                kw = kw_row["keyword"]
                stats = conn.execute('''
                    SELECT 
                        COUNT(*) as total_hits,
                        SUM(CASE WHEN risk_score >= 70 THEN 1 ELSE 0 END) as high_risk_hits,
                        AVG(risk_score) as avg_risk
                    FROM messages
                    WHERE matched_keyword = ?
                ''', (kw,)).fetchone()
                
                total_hits = stats["total_hits"] or 0
                high_risk_hits = stats["high_risk_hits"] or 0
                avg_risk = stats["avg_risk"] or 0.0
                
                results.append({
                    "keyword": kw,
                    "total_hits": total_hits,
                    "high_risk_hits": high_risk_hits,
                    "avg_risk": avg_risk
                })
            return jsonify(results)
    except Exception as exc:
        logger.error("api_keywords_effectiveness failed: %s", exc)
        return jsonify([])


@bp.route("/api/ioc/pivot", methods=["GET"])
def api_ioc_pivot():
    db = _db()
    itype = request.args.get("type")
    val = request.args.get("value")
    if not itype or not val:
        return jsonify({"error": "Missing type or value"}), 400
    
    from src.storage.database import get_db
    try:
        with get_db(db.db_path) as conn:
            rows = conn.execute('''
                SELECT DISTINCT m.id, m.sender_name, m.sender_id, m.group_name, m.timestamp, m.text, m.risk_score, m.threat_category
                FROM messages m
                JOIN message_entities me ON m.id = me.message_id
                JOIN entities e ON me.entity_id = e.id
                WHERE e.entity_type = ? AND e.entity_value = ?
                ORDER BY m.timestamp DESC
                LIMIT 50
            ''', (itype, val)).fetchall()
            
            results = []
            for r in rows:
                results.append({
                    "id": r["id"],
                    "sender_name": r["sender_name"],
                    "sender_id": r["sender_id"],
                    "group_name": r["group_name"],
                    "timestamp": r["timestamp"],
                    "text": r["text"],
                    "risk_score": r["risk_score"],
                    "threat_category": r["threat_category"]
                })
            return jsonify(results)
    except Exception as exc:
        logger.error("api_ioc_pivot failed: %s", exc)
        return jsonify([])




@bp.route("/api/watchlists", methods=["GET", "POST"])
def api_watchlists():
    db = _db()
    if request.method == "POST":
        data = request.get_json() or {}
        wid = data.get("id")
        name = data.get("name")
        params = data.get("query_params")
        if not wid or not name or params is None:
            return jsonify({"error": "Missing watchlist fields"}), 400
        created = datetime.now(timezone.utc).isoformat()
        db.save_watchlist(wid, name, params, created)
        return jsonify({"status": "saved", "id": wid}), 201
    else:
        watchlists = db.get_watchlists()
        return jsonify(watchlists)


@bp.route("/api/watchlists/<watchlist_id>", methods=["DELETE"])
def api_watchlist_delete(watchlist_id):
    db = _db()
    db.delete_watchlist(watchlist_id)
    return jsonify({"status": "deleted"})


# ---------------------------------------------------------------------------
# Health & Pipeline Setup
# ---------------------------------------------------------------------------

def _run_async(coro):
    manager = current_app.config.get("PIPELINE_MANAGER")
    if not manager or not hasattr(manager, "loop"):
        raise RuntimeError("PipelineManager event loop not initialized")
    fut = asyncio.run_coroutine_threadsafe(coro, manager.loop)
    return fut.result()

@bp.route("/api/pipeline/status", methods=["GET"])
def api_pipeline_status():
    manager = current_app.config.get("PIPELINE_MANAGER")
    if not manager:
        return jsonify({"error": "PipelineManager not configured"}), 500
    return jsonify(manager.get_status())

@bp.route("/api/pipeline/toggle", methods=["POST"])
def api_pipeline_toggle():
    manager = current_app.config.get("PIPELINE_MANAGER")
    if not manager:
        return jsonify({"error": "PipelineManager not configured"}), 500
    data = request.get_json() or {}
    enabled = data.get("enabled", True)
    try:
        _run_async(manager.toggle_fetching(enabled))
        return jsonify({"status": "ok", "is_fetching": enabled})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@bp.route("/api/pipeline/accounts", methods=["POST"])
def api_pipeline_accounts_add():
    manager = current_app.config.get("PIPELINE_MANAGER")
    if not manager:
        return jsonify({"error": "PipelineManager not configured"}), 500
    data = request.get_json() or {}
    phone = data.get("phone")
    api_id = data.get("api_id")
    api_hash = data.get("api_hash")
    if not phone or not api_id or not api_hash:
        return jsonify({"error": "Missing phone, api_id, or api_hash parameters"}), 400
    try:
        res = _run_async(manager.add_account(phone, int(api_id), api_hash))
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@bp.route("/api/pipeline/accounts/verify", methods=["POST"])
def api_pipeline_accounts_verify():
    manager = current_app.config.get("PIPELINE_MANAGER")
    if not manager:
        return jsonify({"error": "PipelineManager not configured"}), 500
    data = request.get_json() or {}
    phone = data.get("phone")
    code = data.get("code")
    if not phone or not code:
        return jsonify({"error": "Missing phone or code parameters"}), 400
    try:
        res = _run_async(manager.verify_otp(phone, code))
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@bp.route("/api/pipeline/accounts/toggle", methods=["POST"])
def api_pipeline_accounts_toggle_active():
    manager = current_app.config.get("PIPELINE_MANAGER")
    if not manager:
        return jsonify({"error": "PipelineManager not configured"}), 500
    data = request.get_json() or {}
    phone = data.get("phone")
    is_active = data.get("is_active")
    if not phone or is_active is None:
        return jsonify({"error": "Missing phone or is_active parameters"}), 400
    try:
        res = _run_async(manager.toggle_account_active(phone, int(is_active)))
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@bp.route("/api/pipeline/accounts/<phone>", methods=["DELETE"])
def api_pipeline_accounts_delete(phone):
    manager = current_app.config.get("PIPELINE_MANAGER")
    if not manager:
        return jsonify({"error": "PipelineManager not configured"}), 500
    try:
        success = _run_async(manager.remove_account(phone))
        return jsonify({"status": "deleted" if success else "failed"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@bp.route("/api/groups/join", methods=["POST"])
def api_groups_join():
    manager = current_app.config.get("PIPELINE_MANAGER")
    if not manager:
        return jsonify({"error": "PipelineManager not configured"}), 500
    data = request.get_json() or {}
    link = data.get("link")
    phone = data.get("phone") or None
    if not link:
        return jsonify({"error": "Missing link parameter"}), 400
    try:
        res = _run_async(manager.join_group(link, phone))
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/groups/<int:group_id>/leave", methods=["POST"])
def api_groups_leave(group_id: int):
    """Leave a Telegram group and stop monitoring it."""
    manager = current_app.config.get("PIPELINE_MANAGER")
    db = _db()
    phone = (request.get_json() or {}).get("phone") or None
    try:
        if manager:
            res = _run_async(manager.leave_group(group_id, phone))
        else:
            # No pipeline manager — just mark inactive in DB
            db.remove_group(group_id)
            res = {"status": "partial", "message": "Marked inactive (no Telethon client)."}
        return jsonify(res)
    except Exception as exc:
        logger.error("leave_group route error: %s", exc)
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/groups/search", methods=["GET"])
def api_groups_search():
    manager = current_app.config.get("PIPELINE_MANAGER")
    if not manager:
        return jsonify({"error": "PipelineManager not configured"}), 500
    query = request.args.get("q")
    phone = request.args.get("phone") or None
    if not query:
        return jsonify({"error": "Missing search query"}), 400
    try:
        res = _run_async(manager.search_public_groups(query, phone))
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})


# ---------------------------------------------------------------------------
# Group Discovery API
# ---------------------------------------------------------------------------

@bp.route("/api/discovery/pending", methods=["GET"])
def api_discovery_pending():
    """Return all pending discovered groups for analyst review."""
    db = _db()
    groups = db.get_pending_groups(status="pending")
    return jsonify({"groups": groups, "count": len(groups)})


@bp.route("/api/discovery/count", methods=["GET"])
def api_discovery_count():
    """Return count of unreviewed pending discoveries (used for nav badge)."""
    db = _db()
    count = db.get_pending_groups_count()
    return jsonify({"count": count})


@bp.route("/api/discovery/<int:pending_id>/approve", methods=["POST"])
def api_discovery_approve(pending_id: int):
    """
    Approve a pending group: join it via PipelineManager (if invite_link)
    or add it to monitored groups (if group_id/username), then set status='approved'.
    """
    db = _db()
    manager = current_app.config.get("PIPELINE_MANAGER")

    pending = db.get_pending_groups(status="pending")
    item = next((g for g in pending if g["id"] == pending_id), None)
    if not item:
        return jsonify({"error": "Pending group not found"}), 404

    join_result = {"status": "queued"}
    link = item.get("invite_link") or item.get("group_username")
    if link and manager:
        try:
            join_result = _run_async(manager.join_group(link))
        except Exception as exc:
            logger.warning("auto-join during approve failed: %s", exc)
            join_result = {"status": "join_failed", "error": str(exc)}

    db.update_pending_group_status(pending_id, "approved")
    return jsonify({"success": True, "join": join_result, "group": item})


@bp.route("/api/discovery/<int:pending_id>/dismiss", methods=["POST"])
def api_discovery_dismiss(pending_id: int):
    """Dismiss a pending group — it will be ignored in future scans."""
    db = _db()
    db.update_pending_group_status(pending_id, "dismissed")
    return jsonify({"success": True})
