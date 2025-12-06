"""
Utilities for loading environment variables from the project .env file.
"""
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


@lru_cache(maxsize=1)
def load_env() -> Path:
    """
    Load environment variables from the repository-level .env file once.
    Returns the path to the .env that was attempted.
    """
    root = Path(__file__).resolve().parents[1]
    dotenv_path = root / ".env"
    # override=True so the .env file wins over any existing environment
    load_dotenv(dotenv_path=dotenv_path, override=True)
    return dotenv_path
