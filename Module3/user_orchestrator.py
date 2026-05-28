"""User script for Module 3 - Sends complex requests to the Orchestrator.

These requests are designed to trigger:
  1. Multi-agent decomposition (request 1: needs contract review + compliance)
  2. Single-agent routing (request 2: needs only triage)
  3. A failure scenario when the compliance agent is down (request 3: same as 1)

Pre-requisite: All four servers must be running:
  - Triage Agent on port 9999
  - Contract Review Agent (hierarchical) on port 9998
  - Compliance Checker Agent on port 9997
  - Orchestrator Agent on port 9996

Run with:
    python user_orchestrator.py
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


ORCHESTRATOR_URL = "http://localhost:9996"

REQUESTS = [
    # Request 1: Multi-agent - needs contract review AND compliance
    (
        "Review this contract for risk clauses and check it for GDPR compliance:\n\n"
        "Section 4.2 - Non-Compete: The Contractor shall not engage in any "
        "competing business for 24 months after termination.\n\n"
        "Section 7.1 - Indemnification: The Contractor agrees to indemnify "
        "the Company from any claims arising from performance of services.\n\n"
        "Section 8.3 - Data Processing: The Contractor will process personal "
        "data of EU residents including names, emails, and purchase history. "
        "Data will be stored on US-based servers."
    ),
    # Request 2: Single agent - only needs triage
    (
        "Classify this document: a monthly billing statement from AWS showing "
        "compute and storage charges for the Q2 billing cycle."
    ),
    # Request 3: Multi-agent - needs triage AND contract review
    (
        "I received this document and need to know what type it is and whether "
        "it contains any risky clauses:\n\n"
        "PROFESSIONAL SERVICES AGREEMENT\n\n"
        "Section 3.1 - Exclusivity: The Provider shall be the sole and exclusive "
        "supplier of consulting services to the Client for the duration of this "
        "Agreement and any renewal periods.\n\n"
        "Section 5.4 - Limitation of Liability: The Provider's total liability "
        "under this Agreement shall not exceed the fees paid in the prior 12 months.\n\n"
        "Section 9.2 - Governing Law: This Agreement shall be governed by the "
        "laws of the State of Delaware without regard to conflict of law principles."
    )
]


async def main() -> None:
    logging.basicConfig(level=logging.WARNING)

    print("=" * 70)
    print("User -> Orchestrator -> Remote Agents")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=180.0) as httpx_client:

        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=ORCHESTRATOR_URL,
        )
        card = await resolver.get_agent_card()
        print(f"\nConnected to: {card.name}")

        client_factory = ClientFactory(config=ClientConfig(streaming=False, httpx_client=httpx_client))
        client = client_factory.create(card)

        for i, request_text in enumerate(REQUESTS, 1):
            print(f"\n{'=' * 70}")
            print(f"Request {i}")
            print(f"{'=' * 70}")
            print(f"{request_text[:120]}...")

            parts = [Part(text=request_text)]
            message = Message(
                role=Role.user,
                parts=parts,
                message_id=uuid4().hex,
            )

            print(f"\n--- Response ---")
            response = client.send_message(message)

            async for chunk in response:
                task, _ = chunk
                if task.artifacts:
                    for artifact in task.artifacts:
                        for part in artifact.parts:
                            if getattr(getattr(part, 'root', None), 'text', None):
                                preview = part.root.text[:800]
                                if len(part.root.text) > 800:
                                    preview += "\n..."
                                print(preview)

            if i < len(REQUESTS):
                print("\n[Press Ctrl+C to stop, or wait for next request...]")
                await asyncio.sleep(2)

        await client.close()

    print(f"\n{'=' * 70}")
    print("Done.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
