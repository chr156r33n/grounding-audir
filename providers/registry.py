from .base import GroundingProvider
from .gemini import GeminiProvider
from .microsoft_bing import MicrosoftBingProvider
from .microsoft_web import MicrosoftWebProvider
from .openai_web import OpenAIWebProvider


PROVIDERS: dict[str, GroundingProvider] = {
    provider.id: provider
    for provider in (
        GeminiProvider(),
        MicrosoftWebProvider(),
        MicrosoftBingProvider(),
        OpenAIWebProvider(),
    )
}
