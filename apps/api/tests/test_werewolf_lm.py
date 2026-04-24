import json
import os
import urllib.error

import pytest

from app.werewolf.lm import FakeProvider, LmLog, generate_action, parse_json_object
from app.werewolf.prompts_zh import build_prompt
from app.werewolf.providers import DeepSeekProvider


def test_chinese_prompt_contains_rules_role_and_json_instruction() -> None:
    prompt, schema = build_prompt(
        "vote",
        {
            "name": "阿宁",
            "role": "村民",
            "round": 2,
            "observations": ["第1轮：昨晚无人出局。"],
            "remaining_players": "阿宁、老周、小白",
            "debate": ["老周：我怀疑小白。"],
            "bidding_rationale": "我需要说明自己的判断。",
            "personality": "",
            "num_players": 8,
            "num_villagers": 4,
            "werewolf_context": "",
            "debate_turns_left": 2,
            "options": "老周、小白",
        },
    )

    assert "狼人杀" in prompt
    assert "你是阿宁，身份是村民" in prompt
    assert "请只输出合法 JSON" in prompt
    assert '"vote"' in prompt
    assert schema["required"] == ["reasoning", "vote"]


def test_parse_json_object_accepts_fenced_json() -> None:
    parsed = parse_json_object('```json\n{"reasoning":"观察发言","vote":"老周"}\n```')

    assert parsed == {"reasoning": "观察发言", "vote": "老周"}


def test_generate_action_retries_until_allowed_value() -> None:
    provider = FakeProvider(
        [
            {"reasoning": "先试探", "vote": "不存在的玩家"},
            {"reasoning": "改投合法目标", "vote": "老周"},
        ]
    )

    value, log = generate_action(
        provider=provider,
        action="vote",
        world_state={
            "name": "阿宁",
            "role": "村民",
            "round": 1,
            "observations": [],
            "remaining_players": "阿宁、老周、小白",
            "debate": [],
            "bidding_rationale": "",
            "personality": "",
            "num_players": 8,
            "num_villagers": 4,
            "werewolf_context": "",
            "debate_turns_left": 2,
            "options": "老周、小白",
        },
        model="deepseek-chat",
        allowed_values=["老周", "小白"],
        result_key="vote",
    )

    assert value == "老周"
    assert isinstance(log, LmLog)
    assert log.result == {"reasoning": "改投合法目标", "vote": "老周"}
    assert provider.calls == 2


def test_generate_action_accepts_numeric_value_for_string_allowed_values() -> None:
    provider = FakeProvider([{"reasoning": "我想发言", "bid": 2}])

    value, log = generate_action(
        provider=provider,
        action="bid",
        world_state={
            "name": "阿宁",
            "role": "村民",
            "round": 1,
            "observations": [],
            "remaining_players": "阿宁、老周、小白",
            "debate": [],
            "bidding_rationale": "",
            "personality": "",
            "num_players": 8,
            "num_villagers": 4,
            "werewolf_context": "",
            "debate_turns_left": 2,
            "options": "0、1、2、3、4",
        },
        model="deepseek-chat",
        allowed_values=["0", "1", "2", "3", "4"],
        result_key="bid",
    )

    assert value == "2"
    assert log.result == {"reasoning": "我想发言", "bid": 2}


def test_deepseek_provider_uses_env_and_json_response_format(monkeypatch) -> None:
    requests = []

    def fake_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        requests.append({"url": url, "headers": headers, "payload": payload})
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"reasoning": "按格式返回", "vote": "老周"})
                    }
                }
            ]
        }

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(transport=fake_transport)

    raw = provider.complete_json(
        model="deepseek-chat",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert json.loads(raw) == {"reasoning": "按格式返回", "vote": "老周"}
    assert requests[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer test-key"
    assert requests[0]["payload"]["model"] == "deepseek-chat"
    assert requests[0]["payload"]["response_format"] == {"type": "json_object"}


def test_deepseek_provider_requires_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        DeepSeekProvider()


def test_deepseek_provider_loads_key_from_dotenv(tmp_path, monkeypatch) -> None:
    requests = []

    def fake_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        requests.append({"url": url, "headers": headers, "payload": payload})
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"reasoning": "按格式返回", "vote": "老周"})
                    }
                }
            ]
        }

    (tmp_path / ".env").write_text(
        "APP_NAME=Python React Web API\n"
        "DEEPSEEK_API_KEY=dotenv-key\n"
        "DEEPSEEK_BASE_URL=https://example.deepseek.test\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)

    provider = DeepSeekProvider(transport=fake_transport)
    provider.complete_json(model="deepseek-chat", prompt="{}", temperature=0.3)

    assert requests[0]["url"] == "https://example.deepseek.test/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer dotenv-key"


def test_deepseek_provider_retries_connection_reset(monkeypatch) -> None:
    attempts = []

    def flaky_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        attempts.append({"url": url, "headers": headers, "payload": payload})
        if len(attempts) == 1:
            raise urllib.error.URLError(ConnectionResetError(54, "Connection reset by peer"))
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"reasoning": "重试成功", "vote": "老周"})
                    }
                }
            ]
        }

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(transport=flaky_transport, sleep=lambda _seconds: None)

    raw = provider.complete_json(
        model="deepseek-chat",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert json.loads(raw) == {"reasoning": "重试成功", "vote": "老周"}
    assert len(attempts) == 2


def test_deepseek_provider_raises_clear_error_after_network_retries(monkeypatch) -> None:
    def failing_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        del url, headers, payload
        raise urllib.error.URLError(ConnectionResetError(54, "Connection reset by peer"))

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(
        transport=failing_transport,
        max_retries=2,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(RuntimeError, match="DeepSeek network request failed after 2 attempts"):
        provider.complete_json(
            model="deepseek-chat",
            prompt='请输出 json：{"vote":"老周"}',
            temperature=0.3,
        )


def test_environment_example_uses_empty_deepseek_key_placeholder() -> None:
    example = os.path.join(os.path.dirname(__file__), "..", ".env.example")

    with open(example, encoding="utf-8") as file:
        contents = file.read()

    assert "DEEPSEEK_API_KEY=\n" in contents
