"""A2A Server for the Contract Review Agent (LangGraph).

Port: 9998

Uses langgraph-a2a-server to bridge LangGraph and A2A.
"""

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)
from dotenv import load_dotenv
from langgraph_a2a_server import A2AServer

#TODO: Import contract_review_graph


def main() -> None:
    load_dotenv()
    print("Running A2A Contract Review Agent (LangGraph)")

    HOST = "0.0.0.0"
    PORT = 9998

    skill = AgentSkill(
        id="contract-analysis",
        name="Contract Analysis",
        description=(
            "Analyzes contract text for risk clauses. Extracts key terms, "
            "flags risk areas, and returns a structured risk assessment "
            "with a severity rating and recommendations."
        ),
        tags=["contract", "legal", "risk", "review"],
        examples=[
            "Review this NDA for non-compete clauses and liability risks.",
            "Analyze the following vendor agreement for termination and IP terms.",
        ],
    )

    agent_card = AgentCard(
        name="ContractReviewAgent",
        description=(
            "Analyzes contracts and flags risk clauses. "
            "Built with LangGraph."
        ),
        url=f"http://localhost:{PORT}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(transport="JSONRPC", url=f"http://localhost:{PORT}")
        ],
        skills=[skill],
    )

    server = A2AServer(
        graph=contract_review_graph,
        agent_card=agent_card,
        host=HOST,
        port=PORT,
    )

    server.serve(app_type="starlette")


if __name__ == "__main__":
    main()
