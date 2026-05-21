"""Test client for the hierarchical contract review agent (port 9998)."""

import asyncio
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import Message, Part, Role


async def main():
    async with httpx.AsyncClient(timeout=120.0) as httpx_client:
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url="http://localhost:9998",
        )
        card = await resolver.get_agent_card()
        print(f"Connected to: {card.name}")
        print(f"URL: http://localhost:9998")

        client_factory = ClientFactory(
            config=ClientConfig(streaming=False, httpx_client=httpx_client)
        )
        client = client_factory.create(card)

        request_text = (
            "Review this contract for risk clauses and check for GDPR compliance:\n\n"
            "Section 4.2 - Non-Compete: The Contractor shall not engage in any "
            "competing business for 24 months after termination.\n\n"
            "Section 7.1 - Indemnification: The Contractor agrees to indemnify "
            "the Company from any claims arising from performance of services.\n\n"
            "Section 8.3 - Data Processing: The Contractor will process personal "
            "data of EU residents including names, emails, and purchase history. "
            "Data will be stored on US-based servers."
            #TODO - Add additional request text
        )

        print(f"\n{'=' * 60}")
        print("Sending request to ContractReviewAgent (port 9998)")
        print(f"{'=' * 60}")
        print(f"{request_text[:80]}...\n")

        message = Message(
            role=Role.user,
            parts=[Part(text=request_text)],
            message_id=uuid4().hex,
        )

        response = client.send_message(message)
        async for chunk in response:
            task, _ = chunk

            # Show status updates (shows when delegation happens)
            if task.status and task.status.message:
                msg = task.status.message
                for part in msg.parts:
                    text = getattr(getattr(part, "root", None), "text", None)
                    if text:
                        print(f"  [{task.status.state}] {text}")

            # Show final artifacts
            if task.artifacts:
                for artifact in task.artifacts:
                    for part in artifact.parts:
                        text = getattr(getattr(part, "root", None), "text", None)
                        if text:
                            print(f"\n{'=' * 60}")
                            print("Final response")
                            print(f"{'=' * 60}")
                            print(text)

        await client.close()


if __name__ == "__main__":
    asyncio.run(main())