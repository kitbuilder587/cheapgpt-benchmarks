from pathlib import Path

DEFAULT_BASE_URL = "https://api.aiproductiv.ru/v1"
DEFAULT_TIMEOUT_SECONDS = 180.0
RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
