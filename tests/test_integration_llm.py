import os
import pytest

from autopot.env import load_env
from autopot.llm import create_llm_client

# Edit these flags to True to enable integration tests that call real LLMs.
RUN_OPENAI_INTEG = False
RUN_GEMINI_INTEG = False


@pytest.mark.skipif(
    not RUN_OPENAI_INTEG,
    reason="Enable by setting RUN_OPENAI_INTEG = True in this file",
)
def test_integration_openai_compat():
    load_env()
    base_url = os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not (base_url and api_key and model):
        pytest.skip("OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL not set in .env")
    client = create_llm_client(
        "openai-compat", base_url=base_url, api_key=api_key, model=model
    )
    fs = {
        "type": "dir",
        "name": "/",
        "children": [{"type": "file", "name": "README", "size": 10}],
    }
    res = client.simulate_command("echo hello", fs=fs, bash_history=[])
    assert isinstance(res, dict)
    assert "stdout" in res and "exit_code" in res
    assert isinstance(res["stdout"], str)
    assert isinstance(res["exit_code"], int)


@pytest.mark.skipif(
    not RUN_GEMINI_INTEG,
    reason="Enable by setting RUN_GEMINI_INTEG = True in this file",
)
def test_integration_gemini():
    load_env()
    # Accept either GOOGLE_API_KEY (used by some environments) or GEMINI_API_KEY (.env example)
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL")
    if not (api_key and model):
        pytest.skip("GOOGLE_API_KEY / GEMINI_API_KEY and GEMINI_MODEL not set in .env")
    client = create_llm_client("gemini", api_key=api_key, model=model)
    fs = {
        "type": "dir",
        "name": "/",
        "children": [{"type": "file", "name": "README", "size": 10}],
    }
    res = client.simulate_command("echo hello", fs=fs, bash_history=[])
    print(res)
    assert isinstance(res, dict)
    assert "stdout" in res and "exit_code" in res
    assert isinstance(res["stdout"], str)
    assert isinstance(res["exit_code"], int)
