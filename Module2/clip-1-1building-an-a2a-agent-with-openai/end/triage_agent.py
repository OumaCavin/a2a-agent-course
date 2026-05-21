"""Document Triage Agent - OpenAI Agents SDK.

Classifies a document description as one of: contract, invoice, or compliance.
"""
from agents import Agent, Runner
from dotenv import load_dotenv

load_dotenv()

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
