"""User script - Sends requests to the Client Agent.

This plays the "User" role from the official A2A architecture:
  User -> Client Agent -> A2A -> Remote Agents

Aligned with the official a2a-samples/helloworld/test_client.py pattern.

Pre-requisite: All four servers must be running:
  - Triage Agent on port 9999
  - Contract Review Agent on port 9998
  - Compliance Checker Agent on port 9997
  - Client Agent on port 9996

Run with:
    python user.py
"""

import asyncio
import logging
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import (
    Message,
    Part,
    Role,
)


CLIENT_AGENT_URL = "http://localhost:9996"

REQUESTS = [
    #TODO: Add your requests here
    "Classify this document: a vendor services agreement with payment terms, an SLA, and a non-compete clause.",
    (
        "Review this contract for risk:\n\n"
        "Section 4.2 - Non-Compete: The Contractor shall not engage in any "
        "competing business for 24 months after termination.\n\n"
        "Section 7.1 - Indemnification: The Contractor agrees to indemnify "
        "the Company from any claims arising from performance of services."
    ),
    (
        "Check this for GDPR compliance: The vendor will process personal data "
        "of EU residents including names and emails. Data will be stored on "
        "US-based servers. No Data Protection Officer is specified."
    ),
]


async def main() -> None:
    logging.basicConfig(level=logging.WARNING)

    print("=" * 70)
    print("User -> Client Agent -> Remote Agents")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=120.0) as httpx_client:

        # Connect to the Client Agent
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=CLIENT_AGENT_URL,
        )
        card = await resolver.get_agent_card()
        print(f"\nConnected to: {card.name}")
        print(f"Description:  {card.description}")

        client_factory = ClientFactory(config=ClientConfig(streaming=False, httpx_client=httpx_client))
        client = client_factory.create(card)

        for i, request_text in enumerate(REQUESTS, 1):
            print(f"\n{'─' * 70}")
            print(f"Request {i}: {request_text[:80]}...")
            print(f"{'─' * 70}")

            parts = [Part(text=request_text)]
            message = Message(
                role=Role.user,
                parts=parts,
                message_id=uuid4().hex,
            )

            response = client.send_message(message)

            async for chunk in response:
                task, _ = chunk
                # Extract text from artifacts
                if task.artifacts:
                    for artifact in task.artifacts:
                        for part in artifact.parts:
                            if getattr(getattr(part, 'root', None), 'text', None):
                                preview = part.root.text[:600]
                                if len(part.root.text) > 600:
                                    preview += "\n..."
                                print(preview)

        await client.close()

    print(f"\n{'=' * 70}")
    print("Done. Three requests, one Client Agent, three remote agents.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
