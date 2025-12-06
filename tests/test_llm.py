import json
import pytest
from autopot.llm import BaseLLMClient

class DummyGoodSim(BaseLLMClient):
    def _raw_generate(self, prompt, model=None, **kwargs):
        return json.dumps({"stdout":"ok","stderr":"","exit_code":0,"explanation":"ok"})

def test_simulate_command_success():
    client = DummyGoodSim()
    res = client.simulate_command("ls", fs={"type":"dir","name":"/","children":[]}, bash_history=["pwd"])
    assert res["stdout"] == "ok"
    assert res["exit_code"] == 0

class DummyBad(BaseLLMClient):
    def _raw_generate(self, prompt, model=None, **kwargs):
        return "no json here"

def test_simulate_command_parse_failure():
    client = DummyBad()
    res = client.simulate_command("ls", fs={"type":"dir","name":"/","children":[]}, bash_history=[])
    assert res["exit_code"] == 1
    assert "llm-parse-error" in res["stderr"]

class DummyGoodFS(BaseLLMClient):
    def _raw_generate(self, prompt, model=None, **kwargs):
        return json.dumps({
            "type":"dir",
            "name":"home",
            "children":[
                {"type":"dir","name":"user","children":[
                    {"type":"file","name":"README","size":100,"content_summary":"notes"}
                ]}
            ]
        })

def test_generate_random_filesystem_success():
    client = DummyGoodFS()
    fs = client.generate_random_filesystem(target_dir="/home/user")
    assert fs["type"] == "dir"
    assert "children" in fs

class DummyScenarioFS(BaseLLMClient):
    def _raw_generate(self, prompt, model=None, **kwargs):
        return json.dumps({
            "type":"dir",
            "name":"root",
            "children":[
                {"type":"dir","name":"logs","children":[]}
            ]
        })

def test_generate_scenario_filesystem_success():
    client = DummyScenarioFS()
    fs = client.generate_scenario_filesystem(description="IoT camera compromise", target_dir="/home/user")
    assert fs["type"] == "dir"
    assert any(child["name"] == "logs" for child in fs["children"])

class DummyBadFS(BaseLLMClient):
    def _raw_generate(self, prompt, model=None, **kwargs):
        return "garbage"

def test_generate_random_filesystem_failure():
    client = DummyBadFS()
    fs = client.generate_random_filesystem()
    assert fs["type"] == "dir"
    assert isinstance(fs.get("children"), list)


class DummyBadScenarioFS(BaseLLMClient):
    def _raw_generate(self, prompt, model=None, **kwargs):
        return "garbage"

def test_generate_scenario_filesystem_failure():
    client = DummyBadScenarioFS()
    fs = client.generate_scenario_filesystem(description="test")
    assert fs["type"] == "dir"
    assert isinstance(fs.get("children"), list)
