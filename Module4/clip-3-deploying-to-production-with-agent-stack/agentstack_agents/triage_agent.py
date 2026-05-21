"""Document Triage Agent - Agent Stack deployment.

Wraps the OpenAI Agents SDK triage logic with the Agent Stack Server
pattern for production deployment.

The agent logic (classification) stays the same as Module 2.
The Agent Stack SDK adds the platform plumbing: server wrapper,
LLM extension for platform-managed credentials, and A2A compatibility.
"""

import os
from typing import Annotated

from a2a.types import Message
from a2a.utils.message import get_message_text
from agents import Agent, Runner
from agentstack_sdk.a2a.extensions import (
    LLMServiceExtensionServer,
    LLMServiceExtensionSpec,
)
from agentstack_sdk.a2a.types import AgentMessage
from agentstack_sdk.server import Server
from agentstack_sdk.server.context import RunContext


# -- Agent logic (same as Module 2, unchanged) ---------------------------------

triage_agent = Agent(
    name="DocumentTriageAgent",
    model="gpt-5.4-nano",
    instructions=(
        "You are a document classification agent. Given a description of a document, "
        "classify it into exactly one of these categories: contract, invoice, or compliance. "
        "Respond with only the category name in lowercase. No explanation."
    ),
)


async def classify(description: str) -> str:
    """Classify a document description into a category."""
    result = await Runner.run(triage_agent, description)
    return result.final_output


# -- Agent Stack server wrapper ------------------------------------------------

server = Server()


@server.agent(
    name="TriageAgent",
)
async def triage_agent_wrapper(
    input: Message,
    context: RunContext,
    llm: Annotated[
        LLMServiceExtensionServer,
        LLMServiceExtensionSpec.single_demand(suggested=("openai:gpt-5.4-nano",)),
    ],
):
    """Classifies documents as contract, invoice, or compliance."""
    prompt = get_message_text(input)

    if not prompt:
        yield AgentMessage(text="No document description provided.")
        return

    result = await classify(prompt)
    yield AgentMessage(text=result)


def run() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))
    server.run(host=host, port=port)


if __name__ == "__main__":
    run()
