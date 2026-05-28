"""A2A Orchestrator Agent - Decomposes, delegates, aggregates, retries.

Port: 9996

Evolves the Module 2 Client Agent into a full orchestrator:
  1. Decomposes complex requests into subtasks using an LLM
  2. Delegates each subtask to the best remote agent
  3. Aggregates results into a single response
  4. Retries failed calls with exponential backoff
  5. Degrades gracefully when agents are unavailable
"""

import asyncio
import json
import logging
from pathlib import Path
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


logger = logging.getLogger(__name__)


# -- Remote agent registry -----------------------------------------------------

REMOTE_AGENT_URLS = [
    "http://localhost:9999",  # Triage Agent
    "http://localhost:9998",  # Contract Review Agent
    "http://localhost:9997",  # Compliance Checker Agent
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


def build_decomposition_prompt(remote_agents: list[dict]) -> str:
    """Build a system prompt for the decomposer LLM."""
    lines = [
        "You are a task decomposition agent. Given a user request, break it "
        "into one or more subtasks. Each subtask should be handled by one "
        "of the available agents.\n",
        "Available agents:",
    ]
    for i, agent in enumerate(remote_agents):
        card = agent["card"]
        skill_text = "; ".join(s.description for s in card.skills if s.description)
        lines.append(f"  {i}. {card.name}: {skill_text}")

    lines.append(
        "\nIMPORTANT: Each subtask MUST include the full original document text "
        "from the user request. Do not summarize or paraphrase. Copy the document "
        "content verbatim into each subtask that needs it."
    )

    lines.append(
        "\nRespond with ONLY a JSON array of objects. Each object has two fields:"
        '\n  "agent_index": the number of the agent to use'
        '\n  "subtask": the text to send to that agent'
        "\n\nIf the request maps to a single agent, return an array with one object."
        "\nIf it needs multiple agents, return multiple objects."
        "\nNo explanation. Only the JSON array."
    )
    return "\n".join(lines)

# -- Retry helper --------------------------------------------------------------

MAX_RETRIES = 3
BACKOFF_BASE = 1.0  # seconds


async def call_remote_agent(
    url: str,
    card,
    user_text: str,
) -> str:
    """Send a request to a remote agent with retry and exponential backoff."""
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=120.0) as httpx_client:
                resolver = A2ACardResolver(
                    httpx_client=httpx_client,
                    base_url=url,
                )
                remote_card = await resolver.get_agent_card()

                client_factory = ClientFactory(
                    config=ClientConfig(streaming=False, httpx_client=httpx_client)
                )
                client = client_factory.create(remote_card)

                parts = [Part(text=user_text)]
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
            last_error = e
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "Attempt %d/%d failed for %s: %s. Retrying in %.1fs...",
                    attempt, MAX_RETRIES, url, e, wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "All %d attempts failed for %s: %s",
                    MAX_RETRIES, url, last_error,
                )

    raise ConnectionError(
        f"Agent at {url} unavailable after {MAX_RETRIES} attempts: {last_error}"
    )


# -- Orchestrator executor -----------------------------------------------------

class OrchestratorAgentExecutor(AgentExecutor):

    def __init__(self, remote_agents: list[dict], decomposition_prompt: str) -> None:
        self.remote_agents = remote_agents
        self.decomposer = Agent(
            name="Decomposer",
            model="gpt-5.4-nano",
            instructions=decomposition_prompt,
        )

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        a2a_task = context.current_task or new_task(context.message)
        await event_queue.enqueue_event(a2a_task)

        user_input = context.get_user_input()

        # Step 1: Decompose
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=False,
                status=TaskStatus(
                    state=TaskState.working,
                    message=new_agent_text_message("Decomposing request..."),
                ),
            )
        )

        decompose_result = await Runner.run(self.decomposer, user_input)
        raw_plan = decompose_result.final_output.strip()

        # Parse the JSON plan
        try:
            # Strip markdown code fences if present
            if raw_plan.startswith("```"):
                raw_plan = raw_plan.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            plan = json.loads(raw_plan)
        except json.JSONDecodeError:
            # Fallback: send the whole request to agent 0
            plan = [{"agent_index": 0, "subtask": user_input}]

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=False,
                status=TaskStatus(
                    state=TaskState.working,
                    message=new_agent_text_message(
                        f"Delegating {len(plan)} subtask(s)..."
                    ),
                ),
            )
        )

        # Step 2: Delegate each subtask
        results = []
        for item in plan:
            agent_index = item.get("agent_index", 0)
            subtask_text = item.get("subtask", user_input)

            if agent_index < 0 or agent_index >= len(self.remote_agents):
                agent_index = 0

            selected = self.remote_agents[agent_index]
            agent_name = selected["card"].name
            agent_url = selected["url"]

            try:
                result_text = await call_remote_agent(
                    agent_url, selected["card"], subtask_text
                )
                results.append(f"[{agent_name}]\n{result_text}")
            except ConnectionError as e:
                results.append(
                    f"[{agent_name}]: unavailable after {MAX_RETRIES} attempts"
                )

        # Step 3: Aggregate
        combined = "\n\n---\n\n".join(results)

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                artifact=new_text_artifact(name="result", text=combined),
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
    print("Starting A2A Orchestrator Agent")
    print("Discovering remote agents...")

    remote_agents = asyncio.run(discover_remote_agents())

    if not remote_agents:
        print("No remote agents found. Start the remote agents first.")
        return

    print(f"Discovered {len(remote_agents)} remote agent(s)\n")

    decomposition_prompt = build_decomposition_prompt(remote_agents)

    HOST = "0.0.0.0"
    PORT = 9996

    skill = AgentSkill(
        id="document-processing",
        name="Document Processing",
        description=(
            "Orchestrates document-related requests across specialist agents. "
            "Decomposes complex requests into subtasks, delegates to the right "
            "agents, and aggregates the results."
        ),
        tags=["orchestration", "documents", "routing"],
        examples=[
            "Review this contract for risk clauses and check it for GDPR compliance.",
            "Classify this document and run a compliance check.",
        ],
    )

    agent_card = AgentCard(
        name="DocumentOrchestratorAgent",
        description=(
            "Orchestrates document processing across specialist agents. "
            "Decomposes complex requests, delegates subtasks, and aggregates results."
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
        agent_executor=OrchestratorAgentExecutor(remote_agents, decomposition_prompt),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    uvicorn.run(server.build(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
