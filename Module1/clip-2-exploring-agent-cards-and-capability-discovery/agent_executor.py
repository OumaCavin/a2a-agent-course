"""Contract Review Agent Executor

Uses the full task lifecycle with protobuf types:
  1. Create/get the task
  2. Status update: WORKING
  3. Process the request
  4. Artifact update with the result
  5. Status update: COMPLETED
"""

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.artifact import new_text_artifact
from a2a.utils.message import new_agent_text_message
from a2a.utils.task import new_task


RISK_KEYWORDS = {
    "non-compete": "Non-compete clause detected. Review scope and duration.",
    "indemnification": "Indemnification clause detected. Verify liability caps.",
    "termination for convenience": "Unilateral termination clause detected. Assess exposure.",
    "auto-renewal": "Auto-renewal clause detected. Confirm notice period.",
    "limitation of liability": "Liability limitation detected. Check if cap is acceptable.",
    "confidentiality": "Confidentiality clause detected. Verify survival period.",
    "intellectual property": "IP assignment clause detected. Confirm ownership terms.",
}


class ContractReviewAgent:
    """Scans contract text for common risk clauses."""

    async def invoke(self, contract_text: str) -> str:
        text_lower = contract_text.lower()
        findings = []

        for keyword, finding in RISK_KEYWORDS.items():
            if keyword in text_lower:
                findings.append(finding)

        if not findings:
            return (
                "Risk Assessment Complete\n"
                "Status: LOW RISK\n"
                "No common risk clauses detected in the provided text. "
                "A full legal review is still recommended before signing."
            )

        result_lines = [
            "Risk Assessment Complete",
            f"Status: {'HIGH RISK' if len(findings) >= 3 else 'MEDIUM RISK'}",
            f"Clauses Flagged: {len(findings)}",
            "",
        ]
        for i, finding in enumerate(findings, 1):
            result_lines.append(f"  {i}. {finding}")

        result_lines.append("")
        result_lines.append(
            "Recommendation: Route to legal for detailed review of flagged clauses."
        )
        return "\n".join(result_lines)


class ContractReviewAgentExecutor(AgentExecutor):
    """Bridges the A2A protocol and the contract review logic."""

    def __init__(self) -> None:
        self.agent = ContractReviewAgent()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        # Step 1: Create or retrieve the task
        task = context.current_task or new_task(context.message)
        await event_queue.enqueue_event(task)

        # Step 2: Signal that processing has started
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=False,
                status=TaskStatus(
                    state=TaskState.working,
                    message=new_agent_text_message("Reviewing contract..."),
                ),
            )
        )

        # Step 3: Process the request
        prompt = context.get_user_input()
        if not prompt:
            result = "No contract text provided. Please send the contract content for review."
        else:
            result = await self.agent.invoke(prompt)

        # Step 4: Return the result as an artifact
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                artifact=new_text_artifact(name="risk_assessment", text=result),
            )
        )

        # Step 5: Mark the task as completed
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=True,
                status=TaskStatus(state=TaskState.completed),
            )
        )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        raise Exception("cancel not supported")
