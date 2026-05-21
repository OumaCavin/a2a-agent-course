"""Protocol-level tests for A2A agents.

Run with:
    pytest test_protocol.py -v

NOT: python test_protocol.py (produces no output)

Pre-requisite: An agent server running on port 9999 (the Module 2 triage agent).
"""

import asyncio
from uuid import uuid4

import httpx
import pytest
from a2a.client import A2ACardResolver
from a2a.client.client import ClientConfig
from a2a.client.client_factory import ClientFactory
from a2a.types import (
    Message,
    Part,
    Role,
)


BASE_URL = "http://localhost:9999"


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# -- Helper --------------------------------------------------------------------

async def get_card():
    """Fetch the agent card from the running server."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resolver = A2ACardResolver(httpx_client=client, base_url=BASE_URL)
        return await resolver.get_agent_card()


async def send_message(text: str):
    """Send a message and return the final task."""
    async with httpx.AsyncClient(timeout=120.0) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=BASE_URL)
        card = await resolver.get_agent_card()
        client_factory = ClientFactory(config=ClientConfig(streaming=False, httpx_client=httpx_client))
        client = client_factory.create(card)

        parts = [Part(text=text)]
        message = Message(
            role=Role.user,
            parts=parts,
            message_id=uuid4().hex,
        )

        response = client.send_message(message)
        final_task = None
        async for chunk in response:
            final_task, _ = chunk

        await client.close()
        return final_task


# -- Tests ---------------------------------------------------------------------

class TestAgentCardConformance:
    """Verify the agent card has all required fields."""

    def test_card_has_name(self):
        card = asyncio.get_event_loop().run_until_complete(get_card())
        assert card.name, "Agent card must have a name"

    def test_card_has_version(self):
        card = asyncio.get_event_loop().run_until_complete(get_card())
        assert card.version, "Agent card must have a version"

    def test_card_has_skills(self):
        card = asyncio.get_event_loop().run_until_complete(get_card())
        assert len(card.skills) > 0, "Agent card must declare at least one skill"

    def test_skill_has_description(self):
        card = asyncio.get_event_loop().run_until_complete(get_card())
        for skill in card.skills:
            assert skill.description, f"Skill '{skill.name}' must have a description"

    def test_card_has_url(self):
        """On SDK 0.3.25, the agent card has a url field (not supported_interfaces)."""
        card = asyncio.get_event_loop().run_until_complete(get_card())
        assert card.url, "Agent card must have a url"

    def test_card_has_transport(self):
        """On SDK 0.3.25, transport is declared via preferred_transport."""
        card = asyncio.get_event_loop().run_until_complete(get_card())
        assert card.preferred_transport, "Agent card must declare a preferred transport"


class TestTaskLifecycle:
    """Verify the agent handles tasks correctly."""

    def test_send_message_returns_task(self):
        task = asyncio.get_event_loop().run_until_complete(
            send_message("This is a vendor services agreement with an SLA.")
        )
        assert task is not None, "Agent must return a task"

    def test_task_has_artifacts(self):
        task = asyncio.get_event_loop().run_until_complete(
            send_message("Monthly billing statement for cloud services.")
        )
        assert task.artifacts and len(task.artifacts) > 0, (
            "Completed task must have at least one artifact"
        )

    def test_artifact_has_text(self):
        task = asyncio.get_event_loop().run_until_complete(
            send_message("Annual SOC 2 Type II audit report.")
        )
        artifact = task.artifacts[0]
        # On SDK 0.3.25, Part is a RootModel. Text lives at part.root.text.
        text_parts = [
            p for p in artifact.parts
            if getattr(getattr(p, "root", None), "text", None)
        ]
        assert len(text_parts) > 0, "Artifact must contain text content"


class TestErrorHandling:
    """Verify the agent handles edge cases gracefully."""

    def test_minimal_input_does_not_crash(self):
        """Agent should handle minimal input without throwing an exception.
        Note: SDK 0.3.25 rejects truly empty strings with 'TextPart content
        cannot be empty', so we send a single character instead."""
        task = asyncio.get_event_loop().run_until_complete(send_message("."))
        assert task is not None, "Agent must handle minimal input gracefully"

    def test_very_long_input(self):
        """Agent should handle unusually long input."""
        long_text = "This is a contract. " * 500
        task = asyncio.get_event_loop().run_until_complete(send_message(long_text))
        assert task is not None, "Agent must handle long input gracefully"
