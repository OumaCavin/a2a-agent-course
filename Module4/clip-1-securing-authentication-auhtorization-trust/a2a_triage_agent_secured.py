"""A2A Triage Agent with Authentication and Audit Logging.

Port: 9999

Adds three security layers to the Module 2 triage agent:
  1. Auth scheme declared on the agent card
  2. Token validation middleware on incoming requests
  3. Audit logging of every A2A interaction
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    SecurityScheme,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.artifact import new_text_artifact
from a2a.utils.message import new_agent_text_message
from a2a.utils.task import new_task
from dotenv import load_dotenv
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from triage_agent import classify


# -- Configuration -------------------------------------------------------------

# In production, load from a secrets manager or environment variable
VALID_TOKENS = {
    os.getenv("A2A_BEARER_TOKEN", "demo-token-2026"),
}

# Paths that do not require authentication
PUBLIC_PATHS = {
    "/.well-known/agent-card.json",
}


# -- Audit logging -------------------------------------------------------------

audit_logger = logging.getLogger("audit")


def audit_log(
    action: str,
    client_ip: str,
    detail: str = "",
    status: str = "ok",
) -> None:
    """Write a structured audit log entry."""
    timestamp = datetime.now(timezone.utc).isoformat()
    audit_logger.info(
        "timestamp=%s action=%s client=%s status=%s detail=%s",
        timestamp,
        action,
        client_ip,
        status,
        detail,
    )


# -- Auth middleware ------------------------------------------------------------

class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Validates bearer tokens on incoming A2A requests."""

    async def dispatch(self, request: Request, call_next):
        # Allow public endpoints without auth
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Check for Authorization header
        auth_header = request.headers.get("Authorization", "")
        client_ip = request.client.host if request.client else "unknown"

        if not auth_header.startswith("Bearer "):
            audit_log("auth_failed", client_ip, "missing bearer token", "denied")
            return JSONResponse(
                status_code=401,
                content={"error": "Missing or invalid Authorization header"},
            )

        token = auth_header[7:]  # Strip "Bearer "
        if token not in VALID_TOKENS:
            audit_log("auth_failed", client_ip, "invalid token", "denied")
            return JSONResponse(
                status_code=403,
                content={"error": "Invalid bearer token"},
            )

        audit_log("auth_success", client_ip)
        return await call_next(request)


# -- Agent executor (same as Module 2, with audit logging) ---------------------

class SecuredTriageAgentExecutor(AgentExecutor):

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        task = context.current_task or new_task(context.message)
        await event_queue.enqueue_event(task)

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=False,
                status=TaskStatus(
                    state=TaskState.working,
                    message=new_agent_text_message("Classifying document..."),
                ),
            )
        )

        prompt = context.get_user_input()
        audit_log("task_started", "internal", f"task_id={context.task_id}")

        result = await classify(prompt)

        audit_log(
            "task_completed",
            "internal",
            f"task_id={context.task_id} result={result}",
        )

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                artifact=new_text_artifact(name="classification", text=result),
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=True,
                status=TaskStatus(state=TaskState.completed),
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass


# -- Server setup --------------------------------------------------------------

def main() -> None:
    load_dotenv(Path(__file__).parent / ".env")

    # Configure audit logging to file and console
    logging.basicConfig(level=logging.INFO)
    file_handler = logging.FileHandler("audit.log")
    file_handler.setLevel(logging.INFO)
    audit_logger.addHandler(file_handler)

    print("Running A2A Document Triage Agent (Secured)")

    HOST = "0.0.0.0"
    PORT = 9999

    skill = AgentSkill(
        id="document-triage",
        name="Document Triage",
        description=(
            "Classifies a document description into one of three categories: "
            "contract, invoice, or compliance."
        ),
        tags=["document", "classification", "triage"],
        examples=[
            "This is a vendor services agreement with payment terms and an SLA.",
            "Monthly billing statement for cloud infrastructure services.",
        ],
    )

    agent_card = AgentCard(
        name="DocumentTriageAgent",
        description=(
            "Classifies documents as contract, invoice, or compliance. "
            "Requires bearer token authentication."
        ),
        url=f"http://localhost:{PORT}/",
        version="2.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(transport="JSONRPC", url=f"http://localhost:{PORT}")
        ],
        security_schemes={
            "bearer": SecurityScheme(
                type="http",
                scheme="bearer",
            ),
        },
        security=[{"bearer": []}],
        skills=[skill],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=SecuredTriageAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    # Build the Starlette app and add auth middleware
    app = server.build()
    app.add_middleware(BearerAuthMiddleware)

    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
