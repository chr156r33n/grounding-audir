from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelChoice:
    value: str
    label: str
    note: str | None = None


@dataclass(frozen=True)
class ModelCatalog:
    default: str
    documentation_url: str
    documentation_checked: str
    choices: tuple[ModelChoice, ...]

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(choice.value for choice in self.choices)

    def help_text(self) -> str:
        return (
            f"Documented deployment/model IDs (checked {self.documentation_checked}). "
            f"See {self.documentation_url}"
        )


OPENAI_WEB_SEARCH = ModelCatalog(
    default="gpt-5.5",
    documentation_url="https://developers.openai.com/api/docs/guides/tools-web-search",
    documentation_checked="2026-09-06",
    choices=(
        ModelChoice("gpt-5.5", "gpt-5.5", "Recommended for Responses API web_search"),
        ModelChoice("gpt-5.4", "gpt-5.4"),
        ModelChoice("gpt-5.4-mini", "gpt-5.4-mini"),
        ModelChoice("gpt-5.4-nano", "gpt-5.4-nano"),
        ModelChoice("gpt-4.1", "gpt-4.1"),
        ModelChoice("gpt-4.1-mini", "gpt-4.1-mini"),
    ),
)

DEEPSEEK_WEB_SEARCH = ModelCatalog(
    default="deepseek-v4-flash",
    documentation_url="https://api-docs.deepseek.com/api/create-response/",
    documentation_checked="2026-09-07",
    choices=(
        ModelChoice(
            "deepseek-v4-flash",
            "deepseek-v4-flash",
            "Fast default for Responses API web_search",
        ),
        ModelChoice("deepseek-v4-pro", "deepseek-v4-pro", "Higher-quality web search"),
    ),
)

GEMINI_GOOGLE_SEARCH = ModelCatalog(
    default="gemini-3.6-flash",
    documentation_url="https://ai.google.dev/gemini-api/docs/google-search",
    documentation_checked="2026-09-06",
    choices=(
        ModelChoice("gemini-3.8-flash", "gemini-3.8-flash"),
        ModelChoice("gemini-3.7-flash", "gemini-3.7-flash"),
        ModelChoice("gemini-3.6-flash", "gemini-3.6-flash", "Default in Interactions examples"),
        ModelChoice("gemini-3.5-flash", "gemini-3.5-flash"),
        ModelChoice("gemini-3.5-flash-lite", "gemini-3.5-flash-lite"),
        ModelChoice("gemini-3.1-pro-preview", "gemini-3.1-pro-preview"),
        ModelChoice("gemini-3.1-flash-lite", "gemini-3.1-flash-lite"),
        ModelChoice("gemini-3-flash-preview", "gemini-3-flash-preview"),
        ModelChoice("gemini-2.5-pro", "gemini-2.5-pro"),
        ModelChoice("gemini-2.5-flash", "gemini-2.5-flash"),
        ModelChoice("gemini-2.5-flash-lite", "gemini-2.5-flash-lite"),
        ModelChoice("gemini-2.0-flash", "gemini-2.0-flash"),
    ),
)

MICROSOFT_FOUNDRY_WEB_SEARCH = ModelCatalog(
    default="gpt-5.5",
    documentation_url="https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/web-search",
    documentation_checked="2026-09-06",
    choices=(
        ModelChoice("gpt-5.6-sol", "gpt-5.6-sol", "Use your Foundry deployment name"),
        ModelChoice("gpt-5.6-terra", "gpt-5.6-terra"),
        ModelChoice("gpt-5.6-luna", "gpt-5.6-luna"),
        ModelChoice("gpt-5.5", "gpt-5.5", "Recommended for agentic web search"),
        ModelChoice("gpt-5.4", "gpt-5.4"),
        ModelChoice("gpt-5.4-mini", "gpt-5.4-mini"),
        ModelChoice("gpt-5.4-nano", "gpt-5.4-nano"),
        ModelChoice("gpt-5.4-pro", "gpt-5.4-pro"),
        ModelChoice("gpt-5.1", "gpt-5.1"),
        ModelChoice("gpt-5-mini", "gpt-5-mini"),
        ModelChoice("gpt-4.1", "gpt-4.1"),
        ModelChoice("gpt-4.1-mini", "gpt-4.1-mini"),
        ModelChoice("gpt-4.1-nano", "gpt-4.1-nano"),
        ModelChoice(
            "o3-deep-research",
            "o3-deep-research",
            "Deep research mode; long-running",
        ),
    ),
)

MICROSOFT_BING_GROUNDING = ModelCatalog(
    default="gpt-4.1-mini",
    documentation_url="https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools",
    documentation_checked="2026-09-06",
    choices=(
        ModelChoice("gpt-4.1-mini", "gpt-4.1-mini", "Common in Bing grounding examples"),
        ModelChoice("gpt-4.1", "gpt-4.1"),
        ModelChoice("gpt-4.1-nano", "gpt-4.1-nano"),
        ModelChoice("gpt-5-mini", "gpt-5-mini"),
        ModelChoice("gpt-5.5", "gpt-5.5"),
        ModelChoice("gpt-5.4-mini", "gpt-5.4-mini"),
        ModelChoice("gpt-5.4", "gpt-5.4"),
    ),
)


_AZURE_TOKEN_HELP = (
    "Leave empty to use DefaultAzureCredential on the machine running Streamlit "
    "(requires `az login` in that same environment). Otherwise paste a fresh Foundry token "
    "from Azure Cloud Shell using: "
    "az account get-access-token --scope https://ai.azure.com/.default "
    "--query accessToken -o tsv. Paste only the token string, not the JSON wrapper."
)


@dataclass(frozen=True)
class AzureTokenField:
    help: str = _AZURE_TOKEN_HELP


azure_token_field = AzureTokenField()


def deployment_field(catalog: ModelCatalog, *, label: str = "Model deployment") -> "ProviderField":
    from core.models import ProviderField

    return ProviderField(
        key="model",
        label=label,
        required=True,
        default=catalog.default,
        help=(
            "Enter the exact deployment name from your Foundry project "
            "(Models + endpoints → Deployments). Documented web-search-capable "
            f"models checked {catalog.documentation_checked}: "
            f"{', '.join(catalog.values)}. See {catalog.documentation_url}"
        ),
    )


def model_field(catalog: ModelCatalog, *, label: str = "Model") -> "ProviderField":
    from core.models import ProviderField

    return ProviderField(
        key="model",
        label=label,
        required=True,
        default=catalog.default,
        choices=catalog.values,
        help=catalog.help_text(),
    )
