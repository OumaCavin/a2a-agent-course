"""A2A Contract Review Agent with Hierarchical Delegation.

Port: 9998

Replaces the Module 2 contract review agent. After running the
LangGraph analysis, this agent checks for compliance-related
findings. If found, it autonomously delegates to the Compliance
Agent (port 9997) and combines both assessments.

This agent is a server (to the orchestrator on port 9996) and
a client (to the compliance agent on port 9997).

Uses the A2A SDK AgentExecutor directly (not langgraph-a2a-server)
so we have full control over the executor for hierarchical delegation.
"""

import logging
from uuid import uuid4

import httpx
import uvicorn
from a2a.client import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
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
)
from a2a.types import (
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.artifact import new_text_artifact
from a2a.utils.message import new_agent_text_message
from a2a.utils.task import new_task
from dotenv import load_dotenv
from pathlib import Path
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph


logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent / ".env")

COMPLIANCE_AGENT_URL = "http://localhost:9997"

COMPLIANCE_KEYWORDS = [
    "gdpr", "regulatory", "compliance", "data protection", "privacy",
    "hipaa", "sox", "pci", "sec filing", "disclosure",
]


# -- LangGraph definition (same as Module 2) -----------------------------------

llm = ChatOpenAI(model="gpt-5.4-nano", temperature=0)


def extract_clauses(state: MessagesState) -> dict:
    messages = state["messages"]
    system_msg = {
        "role": "system",
        "content": (
            "You are a contract analyst. Extract and list the key clauses "
            "from the contract text provided. For each clause, state the "
            "clause type and a one-sentence summary. Be concise."
        ),
    }
    response = llm.invoke([system_msg] + messages)
    return {"messages": [response]}


def assess_risk(state: MessagesState) -> dict:
    messages = state["messages"]
    system_msg = {
        "role": "system",
        "content": (
            "You are a contract risk assessor. Based on the clause extraction "
            "above, provide a risk assessment. Rate overall risk as LOW, "
            "MEDIUM, or HIGH. For each flagged clause, explain the risk in "
            "one sentence. End with a recommendation."
        ),
    }
    response = llm.invoke([system_msg] + messages)
    return {"messages": [response]}


graph = StateGraph(MessagesState)
graph.add_node("extract_clauses", extract_clauses)
graph.add_node("assess_risk", assess_risk)
graph.add_edge(START, "extract_clauses")
graph.add_edge("extract_clauses", "assess_risk")
graph.add_edge("assess_risk", END)
contract_review_graph = graph.compile()


# -- Hierarchical delegation helper --------------------------------------------

async def delegate_to_compliance(findings_text: str) -> str | None:
    """Send flagged findings to the compliance agent via A2A."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as httpx_client:
            resolver = A2ACardResolver(
                httpx_client=httpx_client,
                base_url=COMPLIANCE_AGENT_URL,
            )
            card = await resolver.get_agent_card()

            client_factory = ClientFactory(config=ClientConfig(streaming=False, httpx_client=httpx_client))
            client = client_factory.create(card)

            prompt = (
                "Review the following contract risk findings for compliance issues. "
                "Flag any regulatory concerns and recommend corrective actions.\n\n"
                f"{findings_text}"
            )

            parts = [Part(text=prompt)]
            message = Message(
                role=Role.user,
                parts=parts,
                message_id=uuid4().hex,
            )

            response = client.send_message(message)

            result_text = ""
            async for chunk in response:
                remote_task, _ = chunk
                if remote_task.artifacts:
                    for artifact in remote_task.artifacts:
                        for part in artifact.parts:
                            if getattr(getattr(part, 'root', None), 'text', None):
                                result_text = part.root.text

            await client.close()
            return result_text

    except Exception as e:
        logger.warning("Hierarchical delegation to compliance agent failed: %s", e)
        return None


def needs_compliance_review(text: str) -> bool:
    """Check if the risk assessment mentions compliance-related topics."""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in COMPLIANCE_KEYWORDS)


# -- A2A executor --------------------------------------------------------------

class ContractReviewHierarchicalExecutor(AgentExecutor):

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        a2a_task = context.current_task or new_task(context.message)
        await event_queue.enqueue_event(a2a_task)

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=False,
                status=TaskStatus(
                    state=TaskState.working,
                    message=new_agent_text_message("Analyzing contract..."),
                ),
            )
        )

        # Step 1: Run the LangGraph analysis
        user_input = context.get_user_input()
        graph_result = await contract_review_graph.ainvoke(
            {"messages": [{"role": "user", "content": user_input}]}
        )

        # Extract the final message from the graph
        risk_assessment = graph_result["messages"][-1].content

        # Step 2: Check if compliance review is needed
        compliance_findings = None
        if needs_compliance_review(risk_assessment) or needs_compliance_review(user_input):
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    final=False,
                status=TaskStatus(
                        state=TaskState.working,
                        message=new_agent_text_message(
                            "Compliance keywords detected. Delegating to Compliance Agent..."
                        ),
                    ),
                )
            )
            compliance_findings = await delegate_to_compliance(risk_assessment)

        # Step 3: Combine results
        if compliance_findings:
            combined = (
                f"CONTRACT RISK ASSESSMENT\n"
                f"{'=' * 40}\n"
                f"{risk_assessment}\n\n"
                f"COMPLIANCE REVIEW (via hierarchical delegation)\n"
                f"{'=' * 40}\n"
                f"{compliance_findings}"
            )
        else:
            combined = risk_assessment

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                artifact=new_text_artifact(name="risk_assessment", text=combined),
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
    logging.basicConfig(level=logging.INFO)
    print("Running A2A Contract Review Agent (Hierarchical)")

    HOST = "0.0.0.0"
    PORT = 9998

    skill = AgentSkill(
        id="contract-analysis",
        name="Contract Analysis",
        description=(
            "Analyzes contract text for risk clauses. Extracts key terms, "
            "flags risk areas, and returns a risk assessment. Automatically "
            "delegates to a compliance agent when compliance-related clauses "
            "are detected."
        ),
        tags=["contract", "legal", "risk", "review", "compliance"],
        examples=[
            "Review this NDA for non-compete clauses and liability risks.",
            "Analyze this vendor agreement for termination and GDPR terms.",
        ],
    )

    agent_card = AgentCard(
        name="ContractReviewAgent",
        description=(
            "Analyzes contracts and flags risk clauses. Automatically delegates "
            "to a compliance agent for regulatory findings. Built with LangGraph."
        ),
        url=f"http://localhost:{PORT}/",
        version="2.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(transport="JSONRPC", url=f"http://localhost:{PORT}")
        ],
        skills=[skill],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=ContractReviewHierarchicalExecutor(),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    uvicorn.run(server.build(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
