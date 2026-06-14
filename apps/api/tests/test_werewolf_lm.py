import json
import os
import urllib.error

import pytest

from app.werewolf.lm import (
    FakeProvider,
    LmLog,
    generate_action,
    generate_action_with_events,
    parse_json_object,
)
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


def test_build_prompt_supports_werewolf_discuss_action() -> None:
    prompt, schema = build_prompt(
        "werewolf_discuss",
        _world_state_for_special_action("狼人", "Alice、Bob"),
    )

    assert schema["required"] == ["reasoning", "target", "message"]
    assert "狼人夜晚私密沟通" in prompt
    assert "输出字段 reasoning、target 和 message" in prompt


def test_build_prompt_werewolf_discuss_example_includes_message() -> None:
    prompt, _schema = build_prompt(
        "werewolf_discuss",
        _world_state_for_special_action("狼人", "Alice、Bob"),
    )

    example = prompt.split("JSON 示例", 1)[1]

    assert '"target"' in example
    assert '"message"' in example


def test_build_prompt_supports_werewolf_kill_vote_action() -> None:
    prompt, schema = build_prompt(
        "werewolf_kill_vote",
        {
            **_world_state_for_special_action("狼人", "Alice、Bob"),
            "werewolf_discussion": ["Wolf A 建议袭击 Alice。"],
            "werewolf_previous_vote_round": "第1轮票型：Wolf A -> Alice；Wolf B -> Bob。",
            "werewolf_kill_vote_round": 2,
        },
    )

    assert schema["required"] == ["reasoning", "target"]
    assert "狼人夜晚狼刀投票" in prompt
    assert "当前是第 2 轮狼刀投票" in prompt
    assert "输出字段 reasoning 和 target" in prompt


def test_prompt_renders_public_facts() -> None:
    prompt, _schema = build_prompt(
        "debate",
        {
            **_world_state_for_special_action("村民", ""),
            "public_facts": ["7号玩家警上声明6号玩家为好人。"],
        },
    )

    assert "公开事实记录" in prompt
    assert "7号玩家警上声明6号玩家为好人。" in prompt


def test_prompt_renders_endgame_context() -> None:
    prompt, _schema = build_prompt(
        "debate",
        {
            **_world_state_for_special_action("村民", ""),
            "endgame_context": [
                "当前存活 4 人，公开已出 3 名狼人，最多可能还剩 1 狼。",
                "本轮错误放逐可能导致狼人夜晚获胜。",
            ],
        },
    )

    assert "残局压力" in prompt
    assert "本轮错误放逐可能导致狼人夜晚获胜。" in prompt


def test_hunter_prompt_requires_candidate_comparison() -> None:
    prompt, _schema = build_prompt(
        "hunter_shoot",
        _world_state_for_special_action("猎人", "10号玩家、12号玩家、不发动技能"),
    )

    assert "候选嫌疑对比" in prompt
    assert "随机" in prompt


def test_witch_poison_prompt_requires_reason_to_hold_poison() -> None:
    prompt, _schema = build_prompt(
        "witch_poison",
        _world_state_for_special_action("女巫", "10号玩家、不使用毒药"),
    )

    assert "如果不使用毒药" in prompt
    assert "保留毒药仍有收益" in prompt


def test_bid_prompt_is_no_longer_supported() -> None:
    with pytest.raises(ValueError, match="Unsupported action: bid"):
        build_prompt("bid", _world_state_for_special_action("村民", "Alice、Bob"))


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


class CapturingLmEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, event_type: str, **kwargs: object) -> None:
        self.events.append({"type": event_type, **kwargs})


class StreamingFakeProvider:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.calls = 0

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, prompt, temperature
        self.calls += 1
        return "".join(self.chunks)

    def stream_json(self, *, model: str, prompt: str, temperature: float) -> list[str]:
        del model, prompt, temperature
        self.calls += 1
        return self.chunks


class CompleteOnlyFakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, prompt, temperature
        self.calls += 1
        return self.response


class FailingStreamProvider:
    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, prompt, temperature
        raise AssertionError("stream_json should be preferred")

    def stream_json(self, *, model: str, prompt: str, temperature: float):
        del model, prompt, temperature
        yield '{"reasoning":"试探","say":"已输出'
        raise RuntimeError("partial boom")


class StreamFallbackProvider:
    def __init__(self) -> None:
        self.stream_calls = 0
        self.complete_calls = 0

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, prompt, temperature
        self.complete_calls += 1
        return '{"reasoning":"完整响应","say":"流式失败后完整返回"}'

    def stream_json(self, *, model: str, prompt: str, temperature: float):
        del model, prompt, temperature
        self.stream_calls += 1
        raise RuntimeError("stream unsupported")


class FailingCompleteOnlyProvider:
    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, prompt, temperature
        raise RuntimeError("boom")


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

    assert extractor.update('{"summary":"第一行\\n') == "第一行\n"
    assert extractor.update('{"summary":"第一行\\n第二行"}') == "第二行"


def test_visible_json_field_extractor_waits_for_complete_unicode_surrogate_pair() -> None:
    extractor = VisibleJsonFieldExtractor("say")

    assert extractor.update('{"say":"\\ud83d') == ""
    delta = extractor.update('{"say":"\\ud83d\\ude00')

    assert delta == "😀"
    assert delta.encode("utf-8") == b"\xf0\x9f\x98\x80"


def test_visible_json_field_extractor_decodes_complete_bmp_unicode_boundary() -> None:
    extractor = VisibleJsonFieldExtractor("say")

    assert extractor.update('{"say":"\\u6211') == "我"


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


def test_extract_openai_chat_delta_joins_multiple_content_events_in_same_chunk() -> None:
    chunk = (
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
    ).encode("utf-8")

    assert extract_openai_chat_delta(chunk) == "你好"


def test_extract_openai_chat_delta_preserves_content_before_done_in_same_chunk() -> None:
    chunk = (
        'data: {"choices":[{"delta":{"content":"结束前"}}]}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")

    assert extract_openai_chat_delta(chunk) == "结束前"


def test_generate_action_with_events_streams_public_visible_text() -> None:
    sink = CapturingLmEventSink()
    provider = StreamingFakeProvider(
        ['{"reasoning":"试探",', '"say":"我', "不是", '狼"}']
    )

    value, log = generate_action_with_events(
        provider=provider,
        action="debate",
        world_state=_world_state_for_special_action("村民", ""),
        model="deepseek-chat",
        allowed_values=None,
        result_key="say",
        event_sink=sink,
        event_context={
            "round_number": 1,
            "phase": "day",
            "actor": "Alice",
            "action": "debate",
        },
        request_id_factory=lambda: "req_public",
        enable_progress_ticks=False,
    )

    assert value == "我不是狼"
    assert log.raw_response == '{"reasoning":"试探","say":"我不是狼"}'
    assert log.request_id == "req_public"
    delta_events = [event for event in sink.events if event["type"] == "model_response_delta"]
    assert len(delta_events) == 1
    assert delta_events[0]["payload"] == {
        "request_id": "req_public",
        "model": "deepseek-chat",
        "delta": "我不是狼",
        "visible_text": "我不是狼",
        "field": "say",
        "is_public": True,
    }


def test_generate_action_with_events_suppresses_private_action_deltas() -> None:
    sink = CapturingLmEventSink()
    provider = StreamingFakeProvider(
        ['{"reasoning":"夜晚决策",', '"remove":"Bob"}']
    )

    value, log = generate_action_with_events(
        provider=provider,
        action="remove",
        world_state=_world_state_for_special_action("狼人", "Bob、Carol"),
        model="deepseek-chat",
        allowed_values=["Bob", "Carol"],
        result_key="remove",
        event_sink=sink,
        event_context={
            "round_number": 1,
            "phase": "night",
            "actor": "Alice",
            "action": "remove",
        },
        request_id_factory=lambda: "req_private",
        enable_progress_ticks=False,
    )

    assert value == "Bob"
    assert log.result == {"reasoning": "夜晚决策", "remove": "Bob"}
    assert log.request_id == "req_private"
    assert [event["type"] for event in sink.events].count("model_response_delta") == 0


def test_generate_action_with_events_does_not_schedule_retry_on_final_invalid_attempt() -> None:
    sink = CapturingLmEventSink()
    provider = FakeProvider([{"reasoning": "想毒10", "poison": "10号玩家"}])

    value, log = generate_action_with_events(
        provider=provider,
        action="witch_poison",
        world_state={
            **_world_state_for_special_action("女巫", ""),
            "options": ["6号玩家", "12号玩家", "不使用毒药"],
        },
        model="deepseek-chat",
        allowed_values=["6号玩家", "12号玩家", "不使用毒药"],
        result_key="poison",
        retries=1,
        event_sink=sink,
        event_context={
            "round_number": 1,
            "phase": "night",
            "actor": "Alice",
            "action": "witch_poison",
        },
        request_id_factory=lambda: "req_final_invalid",
        enable_progress_ticks=False,
    )

    assert value is None
    assert log.invalid_attempts == [
        {
            "value": "10号玩家",
            "allowed_values": ["6号玩家", "12号玩家", "不使用毒药"],
            "result_key": "poison",
        }
    ]
    assert [event["type"] for event in sink.events] == ["model_request_started"]


def test_generate_action_with_events_publishes_sanitized_started_before_model_output() -> None:
    sink = CapturingLmEventSink()
    world_state = _world_state_for_special_action("村民", "")
    world_state["observations"] = ["第一条观察"]
    world_state["seen"] = {"Alice", "Bob"}

    class EventOrderProvider:
        def __init__(self) -> None:
            self.event_types_seen_before_output: list[str] = []

        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            del model, prompt, temperature
            raise AssertionError("stream_json should be preferred")

        def stream_json(self, *, model: str, prompt: str, temperature: float) -> list[str]:
            del model, prompt, temperature
            self.event_types_seen_before_output = [event["type"] for event in sink.events]
            return ['{"reasoning":"试探","say":"我是好人"}']

    provider = EventOrderProvider()

    value, log = generate_action_with_events(
        provider=provider,
        action="debate",
        world_state=world_state,
        model="deepseek-chat",
        result_key="say",
        event_sink=sink,
        event_context={
            "round_number": 1,
            "phase": "day",
            "actor": "Alice",
            "action": "debate",
        },
        request_id_factory=lambda: "req_started",
        enable_progress_ticks=False,
    )

    assert value == "我是好人"
    assert log.request_id == "req_started"
    assert provider.event_types_seen_before_output == ["model_request_started"]
    started = sink.events[0]
    assert started["type"] == "model_request_started"
    assert started["payload"] == {
        "request_id": "req_started",
        "model": "deepseek-chat",
        "message": "玩家正在组织公开发言...",
        "stream_field": "say",
        "is_public": True,
    }
    assert "world_state" not in started["payload"]
    assert "prompt" not in started["payload"]


def test_generate_action_with_events_falls_back_to_complete_json_without_stream() -> None:
    sink = CapturingLmEventSink()
    provider = CompleteOnlyFakeProvider('{"reasoning":"完整响应","say":"我从完整响应返回"}')

    value, log = generate_action_with_events(
        provider=provider,
        action="debate",
        world_state=_world_state_for_special_action("村民", ""),
        model="deepseek-chat",
        result_key="say",
        event_sink=sink,
        event_context={
            "round_number": 1,
            "phase": "day",
            "actor": "Alice",
            "action": "debate",
        },
        request_id_factory=lambda: "req_complete",
        enable_progress_ticks=False,
    )

    assert value == "我从完整响应返回"
    assert log.raw_response == '{"reasoning":"完整响应","say":"我从完整响应返回"}'
    assert log.request_id == "req_complete"
    assert provider.calls == 1
    assert [event["type"] for event in sink.events].count("model_response_delta") == 0


def test_generate_action_with_events_falls_back_when_stream_fails_before_output() -> None:
    sink = CapturingLmEventSink()
    provider = StreamFallbackProvider()

    value, log = generate_action_with_events(
        provider=provider,
        action="debate",
        world_state=_world_state_for_special_action("村民", ""),
        model="deepseek-chat",
        result_key="say",
        event_sink=sink,
        event_context={
            "round_number": 1,
            "phase": "day",
            "actor": "Alice",
            "action": "debate",
        },
        request_id_factory=lambda: "req_stream_fallback",
        enable_progress_ticks=False,
    )

    assert value == "流式失败后完整返回"
    assert log.raw_response == '{"reasoning":"完整响应","say":"流式失败后完整返回"}'
    assert provider.stream_calls == 1
    assert provider.complete_calls == 1
    assert [event["type"] for event in sink.events] == ["model_request_started"]


def test_generate_action_with_events_publishes_failure_and_stops_progress_on_partial_stream_error(
    monkeypatch,
) -> None:
    class FakeProgress:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.started = False
            self.stopped = False
            FakeProgress.instances.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def record_delta(self):
            pass

    monkeypatch.setattr("app.werewolf.lm.ModelRequestProgress", FakeProgress)

    class FailureOrderSink(CapturingLmEventSink):
        def publish(self, event_type: str, **kwargs: object) -> None:
            if event_type == "model_request_failed":
                assert FakeProgress.instances[0].stopped is True
            super().publish(event_type, **kwargs)

    sink = FailureOrderSink()

    with pytest.raises(RuntimeError, match="partial boom"):
        generate_action_with_events(
            provider=FailingStreamProvider(),
            action="debate",
            world_state=_world_state_for_special_action("村民", ""),
            model="deepseek-chat",
            result_key="say",
            event_sink=sink,
            event_context={
                "round_number": 1,
                "phase": "day",
                "actor": "Alice",
                "action": "debate",
            },
            request_id_factory=lambda: "req_stream_fail",
        )

    assert len(FakeProgress.instances) == 1
    assert FakeProgress.instances[0].started is True
    assert FakeProgress.instances[0].stopped is True
    failed_events = [event for event in sink.events if event["type"] == "model_request_failed"]
    assert len(failed_events) == 1
    assert failed_events[0]["payload"] == {
        "request_id": "req_stream_fail",
        "model": "deepseek-chat",
        "message": "模型请求失败，正在中止本次行动",
    }


def test_generate_action_with_events_sanitizes_public_failure_error() -> None:
    class LeakyErrorProvider:
        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            del model, prompt, temperature
            raise RuntimeError(
                "upstream body echoed prompt world_state raw_response reasoning"
            )

    sink = CapturingLmEventSink()

    with pytest.raises(RuntimeError, match="upstream body echoed"):
        generate_action_with_events(
            provider=LeakyErrorProvider(),
            action="debate",
            world_state=_world_state_for_special_action("村民", ""),
            model="deepseek-chat",
            result_key="say",
            event_sink=sink,
            event_context={
                "round_number": 1,
                "phase": "day",
                "actor": "Alice",
                "action": "debate",
            },
            request_id_factory=lambda: "req_leaky_fail",
            enable_progress_ticks=False,
        )

    failed_event = next(event for event in sink.events if event["type"] == "model_request_failed")
    assert failed_event["payload"] == {
        "request_id": "req_leaky_fail",
        "model": "deepseek-chat",
        "message": "模型请求失败，正在中止本次行动",
    }
    public_payload = json.dumps(failed_event["payload"], ensure_ascii=False)
    assert "prompt" not in public_payload
    assert "world_state" not in public_payload
    assert "raw_response" not in public_payload
    assert "reasoning" not in public_payload


def test_generate_action_with_events_publishes_failure_on_complete_error() -> None:
    sink = CapturingLmEventSink()

    with pytest.raises(RuntimeError, match="boom"):
        generate_action_with_events(
            provider=FailingCompleteOnlyProvider(),
            action="debate",
            world_state=_world_state_for_special_action("村民", ""),
            model="deepseek-chat",
            result_key="say",
            event_sink=sink,
            event_context={
                "round_number": 1,
                "phase": "day",
                "actor": "Alice",
                "action": "debate",
            },
            request_id_factory=lambda: "req_complete_fail",
            enable_progress_ticks=False,
        )

    assert [event["type"] for event in sink.events] == [
        "model_request_started",
        "model_request_failed",
    ]
    assert sink.events[1]["payload"] == {
        "request_id": "req_complete_fail",
        "model": "deepseek-chat",
        "message": "模型请求失败，正在中止本次行动",
    }


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


def test_generate_action_retries_with_invalid_allowed_value_feedback() -> None:
    class CapturingProvider:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.responses = [
                '{"reasoning":"想毒10","poison":"10号玩家"}',
                '{"reasoning":"改毒12","poison":"12号玩家"}',
            ]

        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            del model, temperature
            self.prompts.append(prompt)
            return self.responses[len(self.prompts) - 1]

    provider = CapturingProvider()

    value, lm_log = generate_action(
        provider=provider,
        action="witch_poison",
        world_state={
            **_world_state_for_special_action("女巫", ""),
            "options": ["6号玩家", "12号玩家", "不使用毒药"],
        },
        model="deepseek-v4-flash",
        allowed_values=["6号玩家", "12号玩家", "不使用毒药"],
        result_key="poison",
        retries=2,
    )

    assert value == "12号玩家"
    assert len(provider.prompts) == 2
    assert "上次输出的 poison 为“10号玩家”" in provider.prompts[1]
    assert "6号玩家、12号玩家、不使用毒药" in provider.prompts[1]
    assert lm_log.invalid_attempts == [
        {
            "value": "10号玩家",
            "allowed_values": ["6号玩家", "12号玩家", "不使用毒药"],
            "result_key": "poison",
        }
    ]


def test_generate_action_returns_invalid_attempts_after_exhausting_retries() -> None:
    provider = FakeProvider(
        [
            {"reasoning": "想毒10", "poison": "10号玩家"},
            {"reasoning": "仍毒10", "poison": "10号玩家"},
        ]
    )

    value, lm_log = generate_action(
        provider=provider,
        action="witch_poison",
        world_state={
            **_world_state_for_special_action("女巫", ""),
            "options": ["6号玩家", "12号玩家", "不使用毒药"],
        },
        model="deepseek-v4-flash",
        allowed_values=["6号玩家", "12号玩家", "不使用毒药"],
        result_key="poison",
        retries=2,
    )

    assert value is None
    assert lm_log.result == {"reasoning": "仍毒10", "poison": "10号玩家"}
    assert lm_log.invalid_attempts == [
        {
            "value": "10号玩家",
            "allowed_values": ["6号玩家", "12号玩家", "不使用毒药"],
            "result_key": "poison",
        },
        {
            "value": "10号玩家",
            "allowed_values": ["6号玩家", "12号玩家", "不使用毒药"],
            "result_key": "poison",
        },
    ]
    assert "retry" in lm_log.raw_response


def test_generate_action_accepts_numeric_value_for_string_allowed_values() -> None:
    provider = FakeProvider([{"reasoning": "我选择 2 号", "vote": 2}])

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
            "options": "1、2",
        },
        model="deepseek-chat",
        allowed_values=["1", "2"],
        result_key="vote",
    )

    assert value == "2"
    assert log.result == {"reasoning": "我选择 2 号", "vote": 2}


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


def test_openai_compatible_provider_streams_chat_deltas(monkeypatch) -> None:
    requests = []

    def fake_stream_transport(url: str, headers: dict[str, str], payload: dict) -> list[str]:
        requests.append({"url": url, "headers": headers, "payload": payload})
        return ["我", "不是", "狼"]

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(stream_transport=fake_stream_transport)

    chunks = list(
        provider.stream_json(
            model="deepseek-chat",
            prompt='请输出 json：{"say":"我不是狼"}',
            temperature=0.3,
        )
    )

    assert chunks == ["我", "不是", "狼"]
    assert requests[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer test-key"
    assert requests[0]["payload"]["stream"] is True
    assert requests[0]["payload"]["model"] == "deepseek-chat"
    assert requests[0]["payload"]["response_format"] == {"type": "json_object"}


def test_openai_compatible_provider_stream_wraps_http_error_with_guidance(monkeypatch) -> None:
    def failing_stream_transport(url: str, headers: dict[str, str], payload: dict) -> list[str]:
        del headers, payload
        raise urllib.error.HTTPError(
            url=url,
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )

    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    provider = MiniMaxProvider(stream_transport=failing_stream_transport)

    with pytest.raises(RuntimeError, match="MINIMAX_BASE_URL"):
        list(provider.stream_json(model="MiniMax-M2.7", prompt="{}", temperature=0.3))


def test_openai_compatible_provider_stream_retries_pre_yield_network_error(monkeypatch) -> None:
    attempts = []
    sleep_calls = []

    def flaky_stream_transport(url: str, headers: dict[str, str], payload: dict) -> list[str]:
        attempts.append({"url": url, "headers": headers, "payload": payload})
        if len(attempts) == 1:
            raise urllib.error.URLError(ConnectionResetError(54, "Connection reset by peer"))
        return ["重试", "成功"]

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(
        stream_transport=flaky_stream_transport,
        sleep=sleep_calls.append,
    )

    assert list(provider.stream_json(model="deepseek-chat", prompt="{}", temperature=0.3)) == [
        "重试",
        "成功",
    ]
    assert len(attempts) == 2
    assert sleep_calls == [0.25]


def test_openai_compatible_provider_stream_does_not_retry_after_yield(monkeypatch) -> None:
    attempts = []

    def flaky_stream_transport(url: str, headers: dict[str, str], payload: dict):
        attempts.append({"url": url, "headers": headers, "payload": payload})
        yield "已经输出"
        raise urllib.error.URLError(ConnectionResetError(54, "Connection reset by peer"))

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(
        stream_transport=flaky_stream_transport,
        sleep=lambda _seconds: None,
    )
    chunks = provider.stream_json(model="deepseek-chat", prompt="{}", temperature=0.3)

    assert next(chunks) == "已经输出"
    with pytest.raises(RuntimeError, match="DeepSeek streaming request failed after partial output"):
        next(chunks)
    assert len(attempts) == 1


def test_urlopen_stream_transport_yields_sse_deltas(monkeypatch) -> None:
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        def __iter__(self):
            return iter(
                [
                    'data: {"choices":[{"delta":{"content":"我"}}]}\n\n'.encode("utf-8"),
                    'data: {"choices":[{"delta":{"content":"不是狼"}}]}\n\n'.encode("utf-8"),
                    b"data: [DONE]\n\n",
                ]
            )

    def fake_urlopen(request, timeout: int):
        requests.append({"request": request, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    provider = DeepSeekProvider()

    chunks = list(provider.stream_json(model="deepseek-chat", prompt="{}", temperature=0.3))

    assert chunks == ["我", "不是狼"]
    assert requests[0]["timeout"] == 30


def test_urlopen_stream_transport_times_out_when_stream_has_no_content(
    monkeypatch,
) -> None:
    monotonic_values = iter([0.0, 30.0, 61.0])
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        def __iter__(self):
            return iter([b": heartbeat\n\n", b": heartbeat\n\n"])

    def fake_urlopen(request, timeout: int):
        requests.append(request)
        assert timeout == 30
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        "app.werewolf.providers.time.monotonic",
        lambda: next(monotonic_values),
    )
    provider = DeepSeekProvider(max_retries=3)

    with pytest.raises(RuntimeError, match="no content"):
        list(provider.stream_json(model="deepseek-chat", prompt="{}", temperature=0.3))
    assert len(requests) == 1


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


def test_model_provider_router_exposes_stream_json(monkeypatch) -> None:
    def fake_stream_transport(url: str, headers: dict[str, str], payload: dict) -> list[str]:
        del url, headers, payload
        return ['{"reasoning":"x","say":"你好"}']

    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    provider = create_model_provider(stream_transport=fake_stream_transport)

    assert list(provider.stream_json(model="deepseek-chat", prompt="{}", temperature=0.3)) == [
        '{"reasoning":"x","say":"你好"}'
    ]


def test_model_provider_router_reports_unknown_models(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    provider = create_model_provider(transport=lambda _url, _headers, _payload: {})

    with pytest.raises(RuntimeError, match="No provider registered for model unknown-model"):
        provider.complete_json(model="unknown-model", prompt="{}", temperature=0.3)


def test_model_provider_router_stream_reports_unknown_models(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    provider = create_model_provider(stream_transport=lambda _url, _headers, _payload: [])

    with pytest.raises(RuntimeError, match="No provider registered for model unknown-model"):
        provider.stream_json(model="unknown-model", prompt="{}", temperature=0.3)


def test_default_model_name_uses_minimax_when_only_minimax_key_is_configured(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "#DEEPSEEK_API_KEY=\n"
        "DEEPSEEK_MODEL=deepseek-v4-flash\n"
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


def test_default_model_name_falls_back_to_deepseek_flash_without_configured_keys(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    assert default_model_name() == "deepseek-v4-flash"


def test_environment_example_uses_empty_deepseek_key_placeholder() -> None:
    example = os.path.join(os.path.dirname(__file__), "..", ".env.example")

    with open(example, encoding="utf-8") as file:
        contents = file.read()

    assert "WEREWOLF_DEFAULT_MODEL=\n" in contents
    assert "DEEPSEEK_API_KEY=\n" in contents
    assert "DEEPSEEK_MODEL=deepseek-v4-flash\n" in contents
    assert "MINIMAX_API_KEY=\n" in contents
    assert "DASHSCOPE_API_KEY=\n" in contents
