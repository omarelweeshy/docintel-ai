from app.core.config import Settings
from app.providers.interfaces import AIProvider
from app.providers.ollama import OllamaProvider
from app.providers.openai import OpenAIProvider


def create_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "ollama":
        return OllamaProvider(settings)
    return OpenAIProvider(settings)
