"""A2A Server for the Document Triage Agent (OpenAI Agents SDK).

Port: 9999
"""

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
)
from a2a.types import (
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.artifact import new_text_artifact
from a2a.utils.message import new_agent_text_message
from a2a.utils.task import new_task
from dotenv import load_dotenv

from triage_agent import classify

class TriageAgentExecutor(AgentExecutor):

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
        result = await classify(prompt)

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


def main() -> None:
    load_dotenv()
    print("Running A2A Document Triage Agent (OpenAI Agents SDK)")

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
            "Annual SOC 2 Type II audit report with control findings.",
        ],
    )

    agent_card = AgentCard(
        name="DocumentTriageAgent",
        description=(
            "Classifies documents as contract, invoice, or compliance. "
            "Built with the OpenAI Agents SDK."
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
        agent_executor=TriageAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    uvicorn.run(server.build(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
