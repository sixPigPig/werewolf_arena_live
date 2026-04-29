import json
import os
import urllib.error

import pytest

from app.werewolf.lm import FakeProvider, LmLog, generate_action, parse_json_object
from app.werewolf.prompts_zh import build_prompt
from app.werewolf.providers import (
    DeepSeekProvider,
    MiniMaxProvider,
    QwenProvider,
    create_model_provider,
    default_model_name,
)
from app.werewolf.streaming import (
    VisibleJsonFieldExtractor,
    action_visible_stream_field,
    extract_openai_chat_delta,
)


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
            "rule_text": "你正在进行一局数字版狼人杀。\n\n游戏规则：\n- 共 6 名玩家：1 名狼人、1 名预言家、1 名守卫、3 名村民。",
            "werewolf_context": "",
            "debate_turns_left": 2,
            "options": "老周、小白",
        },
    )

    assert "狼人杀" in prompt
    assert "共 6 名玩家：1 名狼人、1 名预言家、1 名守卫、3 名村民" in prompt
    assert "你是阿宁，身份是村民" in prompt
    assert "请只输出合法 JSON" in prompt
    assert '"vote"' in prompt
    assert "字段含义：reasoning=推理，vote=投票对象" in prompt
    assert schema["required"] == ["reasoning", "vote"]


def test_build_prompt_supports_witch_save_action() -> None:
    prompt, schema = build_prompt(
        "witch_save",
        _world_state_for_special_action("女巫", "Alice、不使用解药"),
    )

    assert schema["required"] == ["reasoning", "save"]
    assert "女巫夜晚解药" in prompt
    assert "输出字段 reasoning 和 save" in prompt


def test_build_prompt_supports_witch_poison_action() -> None:
    prompt, schema = build_prompt(
        "witch_poison",
        _world_state_for_special_action("女巫", "Bob、Carol、不使用毒药"),
    )

    assert schema["required"] == ["reasoning", "poison"]
    assert "女巫夜晚毒药" in prompt
    assert "输出字段 reasoning 和 poison" in prompt


def test_build_prompt_supports_hunter_shoot_action() -> None:
    prompt, schema = build_prompt(
        "hunter_shoot",
        _world_state_for_special_action("猎人", "Bob、Carol、不发动技能"),
    )

    assert schema["required"] == ["reasoning", "shoot"]
    assert "猎人死亡开枪" in prompt
    assert "输出字段 reasoning 和 shoot" in prompt


def _world_state_for_special_action(role: str, options: str) -> dict[str, object]:
    return {
        "name": "Alice",
        "role": role,
        "round": 1,
        "observations": [],
        "remaining_players": "Alice、Bob、Carol",
        "debate": [],
        "bidding_rationale": "",
        "personality": "",
        "rule_text": "你正在进行一局数字版狼人杀。",
        "werewolf_context": "",
        "debate_turns_left": 0,
        "options": options,
    }


def test_parse_json_object_accepts_fenced_json() -> None:
    parsed = parse_json_object('```json\n{"reasoning":"观察发言","vote":"老周"}\n```')

    assert parsed == {"reasoning": "观察发言", "vote": "老周"}


def test_visible_json_field_extractor_streams_only_new_public_text() -> None:
    extractor = VisibleJsonFieldExtractor("say")

    assert extractor.update('{"reasoning":"先观察",') == ""
    assert extractor.update('{"reasoning":"先观察","say":"我') == "我"
    assert extractor.update('{"reasoning":"先观察","say":"我不是') == "不是"
    assert extractor.update('{"reasoning":"先观察","say":"我不是狼"}') == "狼"
    assert extractor.update('{"reasoning":"先观察","say":"我不是狼"}') == ""


def test_visible_json_field_extractor_decodes_escaped_text() -> None:
    extractor = VisibleJsonFieldExtractor("summary")

    assert extractor.update('{"summary":"第一行\\n') == "第一行"
    assert extractor.update('{"summary":"第一行\\n第二行"}') == "\n第二行"


def test_visible_json_field_extractor_waits_for_complete_unicode_surrogate_pair() -> None:
    extractor = VisibleJsonFieldExtractor("say")

    assert extractor.update('{"say":"\\ud83d') == ""
    delta = extractor.update('{"say":"\\ud83d\\ude00')

    assert delta == "😀"
    assert delta.encode("utf-8") == b"\xf0\x9f\x98\x80"


def test_action_visible_stream_field_only_allows_public_actions() -> None:
    assert action_visible_stream_field("debate") == "say"
    assert action_visible_stream_field("sheriff_speech") == "say"
    assert action_visible_stream_field("sheriff_pk_speech") == "say"
    assert action_visible_stream_field("summarize") == "summary"
    assert action_visible_stream_field("vote") is None
    assert action_visible_stream_field("remove") is None


def test_extract_openai_chat_delta_reads_compatible_sse_chunks() -> None:
    chunk = ('data: {"choices":[{"delta":{"content":"我不是狼"}}]}\n\n').encode(
        "utf-8"
    )

    assert extract_openai_chat_delta(chunk) == "我不是狼"
    assert extract_openai_chat_delta(b"data: [DONE]\n\n") is None
    assert extract_openai_chat_delta(b": heartbeat\n\n") is None


def test_extract_openai_chat_delta_skips_role_only_events_in_same_chunk() -> None:
    chunk = (
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
    ).encode("utf-8")

    assert extract_openai_chat_delta(chunk) == "你好"


def test_extract_openai_chat_delta_skips_leading_comment_in_same_chunk() -> None:
    chunk = (
        ": heartbeat\n\n"
        'data: {"choices":[{"delta":{"content":"继续"}}]}\n\n'
    ).encode("utf-8")

    assert extract_openai_chat_delta(chunk) == "继续"


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
            "rule_text": "你正在进行一局数字版狼人杀。",
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
            "rule_text": "你正在进行一局数字版狼人杀。",
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


def test_minimax_provider_uses_env_and_reasoning_split(tmp_path, monkeypatch) -> None:
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

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.delenv("MINIMAX_API_HOST", raising=False)
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    provider = MiniMaxProvider(transport=fake_transport)

    raw = provider.complete_json(
        model="MiniMax-M2.7",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert json.loads(raw) == {"reasoning": "按格式返回", "vote": "老周"}
    assert requests[0]["url"] == "https://api.minimax.io/v1/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer minimax-key"
    assert requests[0]["payload"]["model"] == "MiniMax-M2.7"
    assert requests[0]["payload"]["reasoning_split"] is True
    assert "response_format" not in requests[0]["payload"]


def test_minimax_provider_accepts_mainland_api_host(monkeypatch) -> None:
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

    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("MINIMAX_API_HOST", "https://api.minimaxi.com")
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    provider = MiniMaxProvider(transport=fake_transport)

    provider.complete_json(
        model="MiniMax-M2.7",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert requests[0]["url"] == "https://api.minimaxi.com/v1/chat/completions"


def test_minimax_provider_explains_invalid_key_region_mismatch(monkeypatch) -> None:
    def failing_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        del url, headers, payload
        raise urllib.error.HTTPError(
            url="https://api.minimax.io/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )

    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    provider = MiniMaxProvider(transport=failing_transport)

    with pytest.raises(RuntimeError, match="MINIMAX_BASE_URL"):
        provider.complete_json(model="MiniMax-M2.7", prompt="{}", temperature=0.3)


def test_qwen_provider_uses_dashscope_env_and_model_alias(tmp_path, monkeypatch) -> None:
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

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.delenv("DASHSCOPE_API_HOST", raising=False)
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    provider = QwenProvider(transport=fake_transport)

    raw = provider.complete_json(
        model="Qwen3.6-Plus",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert json.loads(raw) == {"reasoning": "按格式返回", "vote": "老周"}
    assert requests[0]["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer dashscope-key"
    assert requests[0]["payload"]["model"] == "qwen3.6-plus"


def test_qwen_provider_accepts_dashscope_api_host(tmp_path, monkeypatch) -> None:
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

    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.setenv("DASHSCOPE_API_HOST", "https://dashscope-intl.aliyuncs.com")
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    provider = QwenProvider(transport=fake_transport)

    provider.complete_json(
        model="qwen3.6-plus",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert requests[0]["url"] == (
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
    )


def test_model_provider_router_routes_minimax_without_deepseek_key(tmp_path, monkeypatch) -> None:
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

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.delenv("MINIMAX_API_HOST", raising=False)
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)

    provider = create_model_provider(transport=fake_transport)
    raw = provider.complete_json(
        model="MiniMax-M2.7",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert json.loads(raw) == {"reasoning": "按格式返回", "vote": "老周"}
    assert requests[0]["url"] == "https://api.minimax.io/v1/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer minimax-key"


def test_model_provider_router_routes_qwen_alias_without_other_keys(tmp_path, monkeypatch) -> None:
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

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.delenv("DASHSCOPE_API_HOST", raising=False)
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)

    provider = create_model_provider(transport=fake_transport)
    raw = provider.complete_json(
        model="Qwen3.6-Plus",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert json.loads(raw) == {"reasoning": "按格式返回", "vote": "老周"}
    assert requests[0]["url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer dashscope-key"
    assert requests[0]["payload"]["model"] == "qwen3.6-plus"


def test_model_provider_router_routes_deepseek_models(monkeypatch) -> None:
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

    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    provider = create_model_provider(transport=fake_transport)
    provider.complete_json(
        model="deepseek-chat",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert requests[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer deepseek-key"
    assert requests[0]["payload"]["response_format"] == {"type": "json_object"}


def test_model_provider_router_reports_unknown_models(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    provider = create_model_provider(transport=lambda _url, _headers, _payload: {})

    with pytest.raises(RuntimeError, match="No provider registered for model unknown-model"):
        provider.complete_json(model="unknown-model", prompt="{}", temperature=0.3)


def test_default_model_name_uses_minimax_when_only_minimax_key_is_configured(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "#DEEPSEEK_API_KEY=\n"
        "DEEPSEEK_MODEL=deepseek-chat\n"
        "MINIMAX_API_KEY=minimax-key\n"
        "MINIMAX_MODEL=MiniMax-M2.7\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    assert default_model_name() == "MiniMax-M2.7"


def test_default_model_name_uses_qwen_when_only_dashscope_key_is_configured(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "#DEEPSEEK_API_KEY=\n"
        "#MINIMAX_API_KEY=\n"
        "DASHSCOPE_API_KEY=dashscope-key\n"
        "DASHSCOPE_MODEL=qwen3.6-plus\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    assert default_model_name() == "qwen3.6-plus"


def test_environment_example_uses_empty_deepseek_key_placeholder() -> None:
    example = os.path.join(os.path.dirname(__file__), "..", ".env.example")

    with open(example, encoding="utf-8") as file:
        contents = file.read()

    assert "WEREWOLF_DEFAULT_MODEL=\n" in contents
    assert "DEEPSEEK_API_KEY=\n" in contents
    assert "MINIMAX_API_KEY=\n" in contents
    assert "DASHSCOPE_API_KEY=\n" in contents
