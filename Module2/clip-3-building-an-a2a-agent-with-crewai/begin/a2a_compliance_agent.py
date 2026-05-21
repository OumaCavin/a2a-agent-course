"""A2A Server for the Compliance Checker Agent (CrewAI).

Port: 9997

Aligned with the official a2a-samples/helloworld pattern.
"""

import asyncio

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
from crewai import Agent, Crew, Task
from dotenv import load_dotenv


# -- CrewAI agent definition --------------------------------------------------

load_dotenv()

compliance_analyst = Agent(
    role="Compliance Analyst",
    goal="Evaluate documents against regulatory and policy requirements.",
    backstory=(
       
        #TODO: Addy backstory

    ),
    llm="openai/gpt-5.4-nano",
    verbose=False,
)


def run_compliance_check(document_text: str) -> str:
    """Run the CrewAI compliance check synchronously."""
    task = Task(
        description=(
            f"Review the following document for compliance issues. "
            f"Check for regulatory adherence, policy violations, and missing "
            f"required disclosures. Provide a compliance status (COMPLIANT, "
            f"NON-COMPLIANT, or NEEDS REVIEW) and list any findings.\n\n"
            f"Document:\n{document_text}"
        ),
        expected_output=(
            "A compliance assessment with a status rating and a list of "
            "findings with recommended corrective actions."
        ),
        agent=compliance_analyst,
    )

    crew = Crew(
        agents=[compliance_analyst],
        tasks=[task],
        verbose=False,
    )

    result = crew.kickoff()
    return result.raw


# -- A2A executor --------------------------------------------------------------

class ComplianceAgentExecutor(AgentExecutor):

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
                    message=new_agent_text_message("Running compliance check..."),
                ),
            )
        )

        prompt = context.get_user_input()
        # CrewAI kickoff is synchronous; run in a thread to avoid blocking
        result = await asyncio.to_thread(run_compliance_check, prompt)

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                artifact=new_text_artifact(name="compliance_report", text=result),
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
    load_dotenv()
    print("Running A2A Compliance Checker Agent (CrewAI)")

    HOST = "0.0.0.0"
    PORT = 9997

    skill = AgentSkill(
        id="compliance-check",
        name="Compliance Check",
        description=(
            "Reviews documents for regulatory compliance, policy adherence, "
            "and required disclosures. Returns a compliance status and "
            "findings with recommended corrective actions."
        ),
        tags=["compliance", "regulatory", "audit", "policy"],
        examples=[
            "Check this financial disclosure for SEC filing requirements.",
            "Review this vendor agreement for GDPR data handling compliance.",
        ],
    )

    agent_card = AgentCard(
        name="ComplianceCheckerAgent",
        description=(
            "Checks documents against regulatory and policy requirements. "
            "Built with CrewAI."
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
        agent_executor=ComplianceAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    uvicorn.run(server.build(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
