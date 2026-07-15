"""
src/dashboard/app.py
────────────────────────────────────────────────────────────
Flask application factory — now wrapped with Flask-SocketIO
so the ingestion listener can push live events to the browser.
────────────────────────────────────────────────────────────
"""

import os
from flask import Flask
from flask_socketio import SocketIO
from .routes import bp

# Module-level SocketIO instance — imported by listener.py to emit events.
socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode="threading",   # safe with Telethon running in asyncio thread
    logger=False,
    engineio_logger=False,
)


def create_app(db_handler, group_cache=None, pipeline_manager=None) -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(
            os.path.dirname(__file__), "..", "..", "static"
        ),
        static_url_path="/static",
    )
    app.config["DB_HANDLER"] = db_handler
    app.config["GROUP_CACHE"] = group_cache
    app.config["PIPELINE_MANAGER"] = pipeline_manager
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "telewire-secret")

    app.register_blueprint(bp)
    socketio.init_app(app)
    return app
