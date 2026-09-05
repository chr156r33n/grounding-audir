from enum import Enum


class ObservationState(str, Enum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "n/a"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class ErrorType(str, Enum):
    AUTH_ERROR = "auth_error"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    UNSUPPORTED_MODEL = "unsupported_model"
    INVALID_CONFIG = "invalid_config"
    PARSER_ERROR = "parser_error"
    SEARCH_NOT_TRIGGERED = "search_not_triggered"
    UNKNOWN_ERROR = "unknown_error"


class MatchMode(str, Enum):
    ROOT_DOMAIN = "root_domain"
    EXACT_HOSTNAME = "exact_hostname"
    URL_PREFIX = "url_prefix"


class ProviderType(str, Enum):
    GROUNDING = "grounding"
    RETRIEVAL = "retrieval"
    SERP = "serp"
