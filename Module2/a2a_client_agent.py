"""A2A Client Agent - Discovers remote agents and routes requests.

Port: 9996

This is the "Client Agent" from the official A2A architecture:
  User -> Client Agent -> A2A -> Remote Agents

It runs as an A2A server (full task lifecycle with protobuf types)
and internally acts as an A2A client to the three remote agents.
"""

from pathlib import Path

import asyncio
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
from agents import Agent, Runner
from dotenv import load_dotenv


# -- Remote agent registry -----------------------------------------------------

REMOTE_AGENT_URLS = [
    "http://localhost:9999",  # Triage Agent (OpenAI Agents SDK)
    "http://localhost:9998",  # Contract Review Agent (LangGraph)
    "http://localhost:9997",  # Compliance Checker Agent (CrewAI)
]


async def discover_remote_agents() -> list[dict]:
    """Fetch agent cards from all remote agents at startup."""
    agents = []
    async with httpx.AsyncClient(timeout=10.0) as httpx_client:
        for url in REMOTE_AGENT_URLS:
            try:
                resolver = A2ACardResolver(
                    httpx_client=httpx_client,
                    base_url=url,
                )
                card = await resolver.get_agent_card()
                agents.append({"url": url, "card": card})
                print(f"  Discovered: {card.name} at {url}")
            except Exception as e:
                print(f"  Failed to discover agent at {url}: {e}")
    return agents


def build_routing_prompt(remote_agents: list[dict]) -> str:
    """Build a system prompt listing all available agents and their skills."""
    lines = [
        "You are a routing agent. Given a user request, decide which remote "
        "agent should handle it. Here are the available agents:\n"
    ]
    for i, agent in enumerate(remote_agents):
        card = agent["card"]
        skill_text = "; ".join(s.description for s in card.skills if s.description)
        lines.append(f"{i}. {card.name}: {skill_text}")

    lines.append(
        "\nRespond with ONLY the number (0, 1, 2, etc.) of the best agent "
        "for the request. No explanation."
    )
    return "\n".join(lines)


# -- Client Agent executor -----------------------------------------------------

class ClientAgentExecutor(AgentExecutor):
    """Receives user requests, routes to the best remote agent, returns the result."""

    def __init__(self, remote_agents: list[dict], routing_prompt: str) -> None:
        self.remote_agents = remote_agents
        self.router = Agent(
            name="Router",
            model="gpt-5.4-nano",
            instructions=routing_prompt,
        )

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        # Task lifecycle: create/get the task
        a2a_task = context.current_task or new_task(context.message)
        await event_queue.enqueue_event(a2a_task)

        user_input = context.get_user_input()

        # Task lifecycle: WORKING
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=False,
                status=TaskStatus(
                    state=TaskState.working,
                    message=new_agent_text_message("Routing request..."),
                ),
            )
        )

        # Step 1: Route - ask the LLM which agent should handle this
        route_result = await Runner.run(self.router, user_input)
        try:
            agent_index = int(route_result.final_output.strip())
        except (ValueError, IndexError):
            agent_index = 0

        if agent_index < 0 or agent_index >= len(self.remote_agents):
            agent_index = 0

        selected = self.remote_agents[agent_index]
        selected_name = selected["card"].name
        selected_url = selected["url"]

        # Update status with routing decision
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=False,
                status=TaskStatus(
                    state=TaskState.working,
                    message=new_agent_text_message(
                        f"Delegating to {selected_name}..."
                    ),
                ),
            )
        )

        # Step 2: Delegate - send the request to the selected remote agent
        result_text = ""
        async with httpx.AsyncClient(timeout=120.0) as httpx_client:
            resolver = A2ACardResolver(
                httpx_client=httpx_client,
                base_url=selected_url,
            )
            remote_card = await resolver.get_agent_card()

            client_factory = ClientFactory(config=ClientConfig(streaming=False, httpx_client=httpx_client))
            client = client_factory.create(remote_card)

            parts = [Part(text=user_input)]
            message = Message(
                role=Role.user,
                parts=parts,
                message_id=uuid4().hex,
            )

            response = client.send_message(message)

            # Step 3: Collect the response
            async for chunk in response:
                remote_task, _ = chunk
                # Extract text from artifacts
                if remote_task.artifacts:
                    for artifact in remote_task.artifacts:
                        for part in artifact.parts:
                            if getattr(getattr(part, 'root', None), 'text', None):
                                result_text = part.root.text

            await client.close()

        # Task lifecycle: return the result as an artifact
        final_text = f"[Routed to {selected_name}]\n\n{result_text}"
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                artifact=new_text_artifact(name="result", text=final_text),
            )
        )

        # Task lifecycle: COMPLETED
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
    print("Starting A2A Client Agent")
    print("Discovering remote agents...")

    remote_agents = asyncio.run(discover_remote_agents())

    if not remote_agents:
        print("No remote agents found. Start the remote agents first.")
        return

    print(f"Discovered {len(remote_agents)} remote agent(s)\n")

    routing_prompt = build_routing_prompt(remote_agents)

    HOST = "0.0.0.0"
    PORT = 9996

    skill = AgentSkill(
        id="document-processing",
        name="Document Processing",
        description=(
            "Routes document-related requests to the appropriate specialist agent. "
            "Handles document triage, contract review, and compliance checking "
            "by delegating to specialized remote agents."
        ),
        tags=["routing", "documents", "orchestration"],
        examples=[
            "Classify this document: vendor services agreement with SLA terms.",
            "Review this contract for risk clauses.",
            "Check this data processing agreement for GDPR compliance.",
        ],
    )

    agent_card = AgentCard(
        name="DocumentProcessingClientAgent",
        description=(
            "A client agent that receives document-related requests and routes "
            "them to the best specialist agent. Discovers remote agents at startup "
            "and delegates based on capability matching."
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

    request_handler = DefaultRequestHandler(
        agent_executor=ClientAgentExecutor(remote_agents, routing_prompt),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    uvicorn.run(server.build(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
