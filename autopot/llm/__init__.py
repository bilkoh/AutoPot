"""
Lightweight LLM client wrapper supporting OpenAI-compatible endpoints and Google Gemini.
Refactored to provide BaseLLMClient to centralize simulate/generate logic.
"""
from typing import Protocol, Any, Dict, Optional, List
import os
import json
import jsonschema
import logging

from autopot.env import load_env

logger = logging.getLogger(__name__)
load_env()

SIMULATE_PROMPT_TEMPLATE = """You are a Linux terminal emulator. Given the filesystem JSON, a short bash history, and a command, pretend you executed the command on a real machine and return a JSON object ONLY (no commentary) with the following fields:
- stdout: string (what would be printed to stdout)
- stderr: string (what would be printed to stderr)
- exit_code: integer (0 for success, non-zero for failure)
- explanation: short string explaining any assumptions or notable details

Filesystem JSON:
{fs}

Bash history (most recent last):
{bash_history}

Command:
{command}

Return JSON only.
"""

GENERATE_FS_PROMPT_TEMPLATE = """You will generate a JSON filesystem tree rooted at "{target_dir}". Produce a single JSON object only (no commentary) describing the tree. Use this schema:
- type: "dir" or "file"
- name: basename (string)
- children: array of nodes (for dirs only)
- size: integer bytes (for files; optional)
- content_summary: short string describing interesting contents (optional)

Constraints:
- Only include entries under "{target_dir}"
- Keep total files <= {max_files}, max depth <= {max_depth}
- Make the filesystem interesting for a honeypot: include config files, ssh keys, scripts, README files, suspicious binaries, and a mix of typical user files.
- Use the provided seed={seed} for determinism if given.

Return JSON only.
"""

SIMULATE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "exit_code": {"type": "integer"},
        "explanation": {"type": "string"},
    },
    "required": ["stdout", "exit_code"],
    "additionalProperties": False,
}

FS_NODE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["dir", "file"]},
        "name": {"type": "string"},
        "children": {
            "type": "array",
            "items": {"$ref": "#"},
        },
        "size": {"type": "integer"},
        "content_summary": {"type": "string"},
    },
    "required": ["type", "name"],
    "additionalProperties": False,
}

FS_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "filesystem.schema.json",
    **FS_NODE_SCHEMA,
}

class LLMClient(Protocol):
    def generate(self, *args, **kwargs) -> str: ...
    def simulate_command(self, command: str, fs: Dict[str, Any], bash_history: List[str], *, model: Optional[str] = None) -> Dict[str, Any]: ...
    def generate_random_filesystem(self, seed: Optional[int] = None, max_files: int = 200, max_depth: int = 4, target_dir: str = "/home/user") -> Dict[str, Any]: ...

def _validate_and_parse_json(text: str, schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not text or not text.strip():
        return None
    try:
        obj = json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            logger.debug("No JSON object found in text")
            return None
        try:
            obj = json.loads(text[start : end + 1])
        except Exception as e:
            logger.debug("Failed to parse extracted JSON: %s", e)
            return None
    try:
        jsonschema.validate(instance=obj, schema=schema)
    except Exception as e:
        logger.debug("JSON schema validation failed: %s", e)
        return None
    return obj

class BaseLLMClient:
    """
    Common implementation for higher-level ops that are provider-agnostic.
    Providers must implement _raw_generate(prompt, model, **kwargs) -> str.
    """

    model: Optional[str] = None

    def _raw_generate(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        raise NotImplementedError

    def simulate_command(self, command: str, fs: Dict[str, Any], bash_history: List[str], *, model: Optional[str] = None) -> Dict[str, Any]:
        prompt = SIMULATE_PROMPT_TEMPLATE.format(fs=json.dumps(fs), bash_history=json.dumps(bash_history), command=command)
        text = self._raw_generate(prompt, model=model)
        parsed = _validate_and_parse_json(text, SIMULATE_SCHEMA)
        if parsed is None:
            logger.warning("simulate_command: failed to parse/validate LLM response; returning safe fallback")
            return {"stdout": "", "stderr": "llm-parse-error", "exit_code": 1, "explanation": "failed to parse LLM output"}
        # Normalize fields so callers can rely on keys existing.
        # Use conservative defaults: empty stdout/stderr, non-zero exit_code if uncertain.
        parsed.setdefault("stdout", "")
        parsed.setdefault("stderr", "")
        parsed.setdefault("exit_code", 1)
        parsed.setdefault("explanation", "")
        return parsed

    def generate_random_filesystem(self, seed: Optional[int] = None, max_files: int = 200, max_depth: int = 4, target_dir: str = "/home/user") -> Dict[str, Any]:
        prompt = GENERATE_FS_PROMPT_TEMPLATE.format(target_dir=target_dir, max_files=max_files, max_depth=max_depth, seed=seed)
        text = self._raw_generate(prompt, model=self.model)
        parsed = _validate_and_parse_json(text, FS_SCHEMA)
        if parsed is None:
            logger.warning("generate_random_filesystem: failed to parse/validate LLM response; returning empty root")
            return {"type": "dir", "name": target_dir.rstrip("/"), "children": []}
        return parsed

class OpenAICompatClient(BaseLLMClient):
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None):
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL")
        try:
            from openai import OpenAI
        except Exception as e:
            raise RuntimeError("openai package required for OpenAICompatClient") from e
        self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    def _raw_generate(self, prompt: str, model: Optional[str] = None, temperature: float = 0.0) -> str:
        model = model or self.model
        if not model:
            raise ValueError("model must be provided")
        resp = self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        try:
            return resp.choices[0].message.content
        except Exception:
            return getattr(resp, "text", str(resp))

    def generate(self, messages: List[Dict[str, str]], temperature: float = 0.0, model: Optional[str] = None) -> str:
        model = model or self.model
        if not model:
            raise ValueError("model must be provided")
        resp = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        try:
            return resp.choices[0].message.content
        except Exception:
            return getattr(resp, "text", str(resp))

class GeminiClient(BaseLLMClient):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL")
        try:
            from google import genai
        except Exception as e:
            raise RuntimeError("google-genai package required for GeminiClient") from e
        self._client = genai.Client(api_key=self.api_key) if self.api_key else genai.Client()

    def _raw_generate(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        model = model or self.model or "gemini-1.0"
        resp = self._client.models.generate_content(model=model, contents=prompt, **kwargs)
        return getattr(resp, "text", str(resp))

    def generate(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        model = model or self.model or "gemini-1.0"
        resp = self._client.models.generate_content(
            model=model, contents=prompt, **kwargs
        )
        return getattr(resp, "text", str(resp))

def create_llm_client(kind: str, **kwargs) -> LLMClient:
    kind = kind.lower()
    if kind in ("openai", "openai-compat", "anyscale"):
        return OpenAICompatClient(**kwargs)
    if kind in ("gemini", "google", "google-gemini"):
        return GeminiClient(**kwargs)
    raise ValueError(f"unknown llm client kind: {kind}")
