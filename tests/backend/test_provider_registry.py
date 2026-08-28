"""Independent voice and agent provider registry tests."""

from backend.config import AgentProvider, Settings, VoiceProvider
from backend.deep_work.deterministic import DeterministicDeepWorker
from backend.providers.agent import create_agent_worker
from backend.providers.voice.disabled import DisabledVoiceSessionBroker
from backend.providers.voice.factory import create_voice_broker


def test_default_registries_select_credential_free_adapters() -> None:
    settings = Settings(
        agent_provider=AgentProvider.DETERMINISTIC,
        voice_provider=VoiceProvider.OFF,
    )
    assert isinstance(create_agent_worker(settings), DeterministicDeepWorker)
    assert isinstance(create_voice_broker(settings), DisabledVoiceSessionBroker)


def test_agent_and_voice_selection_are_independent() -> None:
    settings = Settings(
        agent_provider=AgentProvider.DETERMINISTIC,
        voice_provider=VoiceProvider.AZURE_VOICE_LIVE,
        azure_token_credentials="AzureCliCredential",
        azure_tenant_id="00000000-0000-4000-8000-000000000001",
        voice_endpoint="https://example.invalid",
        voice_model="synthetic-model",
    )
    assert isinstance(create_agent_worker(settings), DeterministicDeepWorker)
    assert create_voice_broker(settings).available is True
