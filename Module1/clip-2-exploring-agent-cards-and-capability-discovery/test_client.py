"""A2A Test Client for the Contract Review Agent.

Run with:
    python test_client.py
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


SAMPLE_CONTRACT = """
MASTER SERVICES AGREEMENT

Section 4.2 - Non-Compete
During the term of this Agreement and for a period of twenty-four (24) months
following termination, the Contractor shall not engage in any business that
directly competes with the Company within the designated territory.

Section 7.1 - Indemnification
The Contractor agrees to indemnify and hold harmless the Company from any
claims, damages, or expenses arising from the Contractor's performance of
services under this Agreement.

Section 9.3 - Termination for Convenience
Either party may terminate this Agreement at any time, for any reason, upon
thirty (30) days written notice to the other party.

Section 11.5 - Auto-Renewal
This Agreement shall automatically renew for successive one-year terms unless
either party provides written notice of non-renewal at least sixty (60) days
prior to the end of the current term.

Section 12.1 - Intellectual Property
All work product, inventions, and materials created by the Contractor in the
course of performing services under this Agreement shall be the sole and
exclusive property of the Company.
"""


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    base_url = "http://localhost:9999"

    async with httpx.AsyncClient() as httpx_client:

        # Step 1: Fetch the agent card
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=base_url,
        )

        logger.info("Fetching agent card from %s", base_url)
        card = await resolver.get_agent_card()
        logger.info("Agent: %s", card.name)
        logger.info("Skills: %s", [s.name for s in card.skills])

        # Step 2: Create a non-streaming client
        client_factory = ClientFactory(config=ClientConfig(streaming=False))
        client = client_factory.create(card)

        # Step 3: Build and send the message
        parts = [Part(text=SAMPLE_CONTRACT)]
        message = Message(
            role=Role.user,
            parts=parts,
            message_id=uuid4().hex,
        )

        print("\n--- Sending contract for review ---")
        response = client.send_message(message)

        async for chunk in response:
            task, _ = chunk
            print("\nResponse:")
            print(task)

        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
