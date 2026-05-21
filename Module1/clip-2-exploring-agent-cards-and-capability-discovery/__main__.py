"""A2A Server for the Contract Review Agent.
Run with:
    python __main__.py
"""

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)

from agent_executor import ContractReviewAgentExecutor

HOST = "0.0.0.0"
PORT = 9999


if __name__ == "__main__":

    skill = AgentSkill(
        id="contract-analysis",
        name="Contract Analysis",
        description=(
            "Analyzes contract text for risk clauses including non-compete, "
            "indemnification, termination, auto-renewal, liability limitation, "
            "confidentiality, and intellectual property terms. Returns a "
            "structured risk assessment with flagged clauses and a severity rating."
        ),
        tags=["contract", "legal", "risk", "review", "compliance"],
        examples=[
            "Review this NDA for non-compete clauses",
            "Analyze the following vendor agreement for liability risks",
            "Flag any auto-renewal or termination clauses in this contract",
        ],
    )

    agent_card = AgentCard(
        name="ContractReviewAgent",
        description=(
            "Analyzes contracts and flags risk clauses. Accepts plain text "
            "contract content and returns a structured risk assessment."
        ),
        url=f"http://localhost:{PORT}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(
                transport="JSONRPC",
                url=f"http://localhost:{PORT}",
            )
        ],
        skills=[skill],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=ContractReviewAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    uvicorn.run(server.build(), host=HOST, port=PORT)
