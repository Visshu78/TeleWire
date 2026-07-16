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
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/wallets/<address>/enrichment")
def api_wallet_enrichment(address):
    enrichment = _db().get_wallet_enrichment(address)
    if enrichment:
        return jsonify(enrichment)
    return jsonify({"error": "No enrichment data available"}), 404


# ---------------------------------------------------------------------------
# Network & Behavioral Intelligence API
# ---------------------------------------------------------------------------

@bp.route("/api/network/graph")
def api_network_graph():
    fetched_by = request.args.get("fetched_by") or None
    analyzer = NetworkAnalyzer(_db())
    graph = analyzer.get_cytoscape_graph(fetched_by=fetched_by)
    return jsonify(graph)


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
    return report_html, 200, {"Content-Type": "text/html; charset=utf-8"}


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
