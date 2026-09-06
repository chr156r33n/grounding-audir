from .base import GroundingProvider
from .gemini import GeminiProvider
from .microsoft_bing import MicrosoftBingProvider
from .microsoft_web import MicrosoftWebProvider
from .microsoft_web_iq import MicrosoftWebIQProvider
from .openai_web import OpenAIWebProvider


PROVIDERS: dict[str, GroundingProvider] = {
    provider.id: provider
    for provider in (
        GeminiProvider(),
        MicrosoftWebProvider(),
        MicrosoftWebIQProvider(),
        MicrosoftBingProvider(),
        OpenAIWebProvider(),
    )
}
