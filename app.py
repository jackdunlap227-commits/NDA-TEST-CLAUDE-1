"""Web server for the Teams NDA agent. Azure Bot Service posts to /api/messages.

    python app.py            # listens on 0.0.0.0:$PORT (default 3978)
"""

from __future__ import annotations

import logging
import os

from aiohttp import web
from dotenv import load_dotenv
from microsoft_agents.activity import load_configuration_from_env
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter, jwt_authorization_decorator, start_agent_process
from microsoft_agents.hosting.core import AgentApplication, Authorization, MemoryStorage, TurnState

from nda_agent.config import Settings
from nda_agent.pipeline import NDAPipeline
from nda_agent.teams_bot import register_handlers


def create_app() -> web.Application:
    load_dotenv()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

    sdk_config = load_configuration_from_env(os.environ)
    storage = MemoryStorage()
    connection_manager = MsalConnectionManager(**sdk_config)
    adapter = CloudAdapter(connection_manager=connection_manager)
    authorization = Authorization(storage, connection_manager, **sdk_config)
    agent_app = AgentApplication[TurnState](storage=storage, authorization=authorization, **sdk_config)

    settings = Settings.from_env()
    register_handlers(agent_app, NDAPipeline(settings), settings.max_upload_mb)

    @jwt_authorization_decorator
    async def messages(request: web.Request) -> web.Response:
        return await start_agent_process(request, agent_app, adapter)

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    app = web.Application()
    app["agent_configuration"] = connection_manager.get_default_connection_configuration()
    app.router.add_post("/api/messages", messages)
    app.router.add_get("/healthz", health)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=int(os.getenv("PORT", "3978")))
