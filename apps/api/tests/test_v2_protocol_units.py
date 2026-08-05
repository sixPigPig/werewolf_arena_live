from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import struct
from types import SimpleNamespace
from typing import Any
import wave

import pytest

from app.v2.action_engine import (
    V2DecisionContract,
    V2ModelRetryPolicy,
    V2SpeechSpec,
    _action_model_parameters,
    _constrain_model_speech,
)
from app.v2.director_projection import project_director_scene
from app.v2.god_view_access import (
    issue_god_view_access_token,
    verify_god_view_access_token,
)
from app.v2.god_view_projection import (
    V2GodViewProjectionError,
    project_god_view_player_identities,
)
from app.v2.model_client import (
    V2ModelError,
    V2QualityError,
    _decision_object,
    _decision_repair_kind,
    _decision_fields,
    _speech_output_instruction,
    _required_speech,
    _sse_data,
    _next_with_cancellation,
    model_failure_disposition,
)
from app.v2.live_runtime import _audience_targets
from app.v2.protocol import V2LiveProtocolError, audio_frame
from app.v2.public_projection import (
    V2PublicProjectionError,
    project_public_player_seats,
    project_public_role_assignment_status,
    project_public_rule_snapshot,
)
from app.v2.repository import V2GameCanceled, V2PresentationIdentity
from app.v2.role_assignment import V2RoleAssignmentError, assign_private_roles
from app.v2.tts_client import (
    _AUDIO_SERVER,
    _CONNECTION_STARTED,
    _FULL_SERVER,
    _SESSION_FINISHED,
    _START_SESSION,
    _TASK_REQUEST,
    _WITH_EVENT,
    V2TtsClient,
    _TtsFrame,
    _decode_frame,
    _encode_event,
    _receive,
)
from app.v2 import tts_client as v2_tts
from app.v2.voice_recorder import V2VoiceRecorder, V2VoiceRecordingError


def test_v2_model_retry_policy_uses_extended_timeouts_by_default() -> None:
    policy = V2ModelRetryPolicy()

    assert policy.max_attempts == 3
    assert policy.attempt_total_seconds == 180.0
    assert policy.action_total_seconds == 300.0


@pytest.mark.parametrize(
    ("error", "category", "max_attempts", "pausable"),
    [
        (V2ModelError("model_empty_stream"), "transport", 3, True),
        (V2ModelError("model_first_token_timeout"), "timeout", 2, True),
        (
            V2QualityError("model_decision_invalid_json", raw_response="not-json"),
            "machine_format",
            2,
            True,
        ),
        (
            V2ModelError("model_provider_credentials_missing"),
            "provider_configuration",
            1,
            False,
        ),
    ],
)
def test_v2_model_failure_disposition_is_explicit(
    error: V2ModelError,
    category: str,
    max_attempts: int,
    pausable: bool,
) -> None:
    disposition = model_failure_disposition(error)

    assert disposition.category == category
    assert disposition.max_attempts == max_attempts
    assert disposition.pausable is pausable


def test_v2_decision_parser_repairs_one_extra_trailing_brace() -> None:
    raw = '{"explode": false}}'
    contract = {
        "kind": "boolean",
        "field": "explode",
        "speech": {"mode": "required_if_true"},
    }

    assert _decision_object(raw) == {"explode": False}
    assert _decision_repair_kind(raw, contract) == "single_trailing_brace_removed"


def _identity() -> V2PresentationIdentity:
    return V2PresentationIdentity(
        game_id="v2_game_0000000000000001",
        run_id="v2_run_0000000000000001",
        action_id="v2_action_0000000000000001",
        phase_id="opening",
        presentation_seq=1,
        presentation_id="v2_pres_0000000000000001",
        speech_id="v2_speech_0000000000000001",
        segment_index=0,
        voice_asset_id="v2_voice_0000000000000001",
        storage_key="v2_game_0000000000000001/v2_voice_0000000000000001.wav",
        subtitle_text="欢迎来到这场实时狼人杀对局。",
    )


def test_v2_tts_sends_documented_explicit_dialect_in_additions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[int, dict[str, Any]]] = []
    frames = iter(
        [
            _TtsFrame(message_type=_AUDIO_SERVER, event=None, payload=b"pcm"),
            _TtsFrame(
                message_type=_FULL_SERVER,
                event=_SESSION_FINISHED,
                payload=b"",
            ),
        ]
    )

    class FakeWebsocket:
        async def close(self) -> None:
            return None

    async def connect(*_args: object, **_kwargs: object) -> FakeWebsocket:
        return FakeWebsocket()

    async def send_event(
        _websocket: object,
        event: int,
        payload: bytes,
        _session_id: str | None = None,
    ) -> None:
        sent.append((event, json.loads(payload)))

    async def expect_event(*_args: object, **_kwargs: object) -> _TtsFrame:
        return _TtsFrame(
            message_type=_FULL_SERVER,
            event=_CONNECTION_STARTED,
            payload=b"",
        )

    async def receive(*_args: object, **_kwargs: object) -> _TtsFrame:
        return next(frames)

    monkeypatch.setattr(v2_tts.websockets, "connect", connect)
    monkeypatch.setattr(v2_tts, "_send_event", send_event)
    monkeypatch.setattr(v2_tts, "_expect_event", expect_event)
    monkeypatch.setattr(v2_tts, "_receive", receive)
    client = V2TtsClient(
        enabled=True,
        api_key="key",
        resource_id="seed-tts-2.0",
        ws_url="wss://example.test",
        speaker="zh_female_vv_uranus_bigtts",
        sample_rate=24000,
        first_chunk_seconds=1,
        idle_seconds=1,
    )

    async def collect_audio() -> list[bytes]:
        return [
            chunk
            async for chunk in client.synthesize(
                text="这是一句四川话测试。",
                attempt_id="v2_tts_test",
                dialect="northeast",
            )
        ]

    audio = asyncio.run(collect_audio())

    assert audio == [b"pcm"]
    start_session = next(payload for event, payload in sent if event == _START_SESSION)
    assert json.loads(start_session["req_params"]["additions"]) == {"explicit_dialect": "dongbei"}


def test_directed_audience_merges_public_and_private_stage_events_only() -> None:
    assert _audience_targets("all") == (
        "player_public",
        "spectator_directed",
        "spectator_god_view",
    )
    assert _audience_targets("public") == (
        "player_public",
        "spectator_directed",
    )
    assert _audience_targets("god_view") == (
        "spectator_directed",
        "spectator_god_view",
    )
    assert _audience_targets("director") == ("spectator_directed",)


def test_director_scene_projection_exposes_context_without_raw_action_data() -> None:
    scene = project_director_scene(
        phase_id="first_night",
        phase_state="night_running",
        action_context={
            "action_id": "v2_action_0000000000000001",
            "action_type": "seer_check",
            "ability_id": "seer_check",
            "actor": {"kind": "player", "id": "player-3"},
            "prompt": "must-not-leak",
            "model_id": "must-not-leak",
            "private_state": {"must": "not-leak"},
        },
    )

    assert scene.model_dump(mode="json") == {
        "scene_kind": "seer",
        "action_id": "v2_action_0000000000000001",
        "action_type": "seer_check",
        "ability_id": "seer_check",
        "actor_player_id": "player-3",
    }
    public_scene = project_director_scene(
        phase_id="day_2",
        phase_state="public_discussion_open",
        action_context={
            "action_id": "v2_action_0000000000000002",
            "action_type": "werewolf_self_explosion",
            "actor": {"kind": "player", "id": "player-5"},
        },
    )
    assert public_scene.scene_kind == "public_stage"


def test_speech_validation_only_requires_non_empty_text() -> None:
    speech = "“先听我说完。然后我们再决定！”\n#这是自然发言的一部分"
    assert _required_speech(f"  {speech}  ", error_code="invalid") == speech
    with pytest.raises(V2QualityError, match="invalid"):
        _required_speech("  \n  ", error_code="invalid")


def test_decision_fields_accept_multi_sentence_text_and_extra_fields() -> None:
    raw = """模型结果如下：
```json
{"target_player_id":" player-2 ","speech":"先听二号怎么说。之后我再判断！","note":"ignored"}
```"""
    assert _decision_fields(raw, _target_contract()) == (
        "player-2",
        "先听二号怎么说。之后我再判断！",
        None,
        None,
    )


def test_decision_fields_ignore_scalar_identity_metadata_from_real_response() -> None:
    raw = json.dumps(
        {
            "target_player_id": "seat_9",
            "speech": "这一票投给9号。",
            "self_identity": "villager",
        },
        ensure_ascii=False,
    )

    assert _decision_fields(raw, _target_contract()) == (
        "seat_9",
        "这一票投给9号。",
        None,
        None,
    )


def test_decision_fields_repairs_structural_smart_quote_from_real_response() -> None:
    raw = """```json
{
  "target_player_id": "system-player-03",
  "speech": "3号周野，你先把自己的逻辑补齐。你到底想带什么节奏？”
}
```"""

    assert _decision_fields(raw, _target_contract()) == (
        "system-player-03",
        "3号周野，你先把自己的逻辑补齐。你到底想带什么节奏？",
        None,
        None,
    )


def test_decision_fields_keep_only_fundamental_failures() -> None:
    assert _decision_fields(
        "我先保留意见，再听后面的发言。",
        _target_contract(),
    ) == (
        None,
        "我先保留意见，再听后面的发言。",
        None,
        None,
    )
    assert _decision_fields(
        '{"speech":"我先保留意见。"}',
        _target_contract(),
    ) == (
        None,
        "我先保留意见。",
        None,
        None,
    )
    assert _decision_fields(
        '{"target_player_id":3,"speech":"我投三号。"}',
        _target_contract(),
    ) == (
        None,
        "我投三号。",
        None,
        None,
    )
    with pytest.raises(V2QualityError, match="model_decision_invalid_speech"):
        _decision_fields(
            '{"target_player_id":null,"speech":"  "}',
            _target_contract(),
        )


def test_decision_fields_recovers_clean_speech_from_truncated_json_wrapper() -> None:
    raw = '{"speech":"我是7号，今天站边12号。\\n2号昨天的票型需要解释，我暂时不会跟票'
    assert _decision_fields(raw, {"kind": "speech", "speech": {"mode": "required"}}) == (
        None,
        "我是7号，今天站边12号。\n2号昨天的票型需要解释，我暂时不会跟票",
        None,
        None,
    )


def test_decision_fields_recovers_target_and_speech_from_truncated_json() -> None:
    raw = '{"target_player_id":"seat_4","speech":"我选择查验4号，因为他的站边变化最明显'
    assert _decision_fields(raw, _target_contract()) == (
        "seat_4",
        "我选择查验4号，因为他的站边变化最明显",
        None,
        None,
    )


def test_decision_fields_extracts_speech_from_safe_nested_output_wrapper() -> None:
    raw = json.dumps(
        {
            "action_id": "v2_action_real",
            "action_type": "sheriff_campaign_speech",
            "output": {"speech": "8号竞选警长，我会把票型和站边讲清楚。"},
            "actor_id": "seat_8",
        },
        ensure_ascii=False,
    )

    assert _decision_fields(
        raw,
        {"kind": "speech", "speech": {"mode": "required"}},
    ) == (
        None,
        "8号竞选警长，我会把票型和站边讲清楚。",
        None,
        None,
    )


def test_decision_fields_extracts_target_from_safe_nested_decision_wrapper() -> None:
    raw = json.dumps(
        {
            "action_id": "v2_action_real",
            "action_type": "ability_witch.heal_decision",
            "actor": {"kind": "player", "id": "seat_7"},
            "decision": {"target_player_id": "seat_1"},
            "speech": None,
        },
        ensure_ascii=False,
    )

    assert _decision_fields(
        raw,
        {
            "kind": "target",
            "target_policy": {"mode": "optional"},
            "speech": {"mode": "optional"},
        },
    ) == (
        "seat_1",
        None,
        None,
        None,
    )


def test_decision_fields_extracts_speech_from_safe_metadata_wrapper() -> None:
    raw = json.dumps(
        {
            "schema_version": 1,
            "action_id": "v2_action_real",
            "action_type": "day_debate_speech",
            "speech": "12号接着盘，先把上一轮票型摆出来。",
        },
        ensure_ascii=False,
    )

    assert _decision_fields(
        raw,
        {"kind": "speech", "speech": {"mode": "required"}},
    ) == (
        None,
        "12号接着盘，先把上一轮票型摆出来。",
        None,
        None,
    )


def test_decision_fields_ignores_structured_metadata_when_output_fields_are_valid() -> None:
    raw = json.dumps(
        {
            "target_player_id": "seat_3",
            "speech": "今晚建议选择3号。",
            "self_identity": {
                "player_id": "seat_1",
                "role_key": "werewolf",
                "team": "werewolves",
            },
        },
        ensure_ascii=False,
    )

    assert _decision_fields(raw, _target_contract()) == (
        "seat_3",
        "今晚建议选择3号。",
        None,
        None,
    )


@pytest.mark.parametrize(
    "raw",
    [
        '{"speech":"{\\"schema_version\\":1,\\"action_id\\":\\"v2_action_echo\\"}"}',
        '```json\n{"schema_version":1,"output_contract":{"kind":"speech"}',
    ],
)
def test_decision_fields_rejects_structured_context_as_broadcast_speech(
    raw: str,
) -> None:
    with pytest.raises(
        V2QualityError,
        match="model_decision_structured_speech_leak",
    ):
        _decision_fields(raw, {"kind": "speech", "speech": {"mode": "required"}})


def test_boolean_decisions_use_semantic_field_and_speech_policy() -> None:
    withdraw_contract = _boolean_contract("withdraw", "required")
    assert _decision_fields(
        '{"withdraw":true,"speech":"9号选择退水。"}',
        withdraw_contract,
    ) == (None, "9号选择退水。", "withdraw", True)
    assert _decision_fields(
        '{"withdraw":false,"speech":"9号不退水，继续参选。"}',
        withdraw_contract,
    ) == (None, "9号不退水，继续参选。", "withdraw", False)

    for raw in (
        '{"speech":"9号选择退水。"}',
        '{"withdraw":"true","speech":"9号选择退水。"}',
        '{"withdraw":null,"speech":"9号选择退水。"}',
    ):
        with pytest.raises(V2QualityError, match="model_decision_invalid_boolean"):
            _decision_fields(raw, withdraw_contract)
    with pytest.raises(V2QualityError, match="model_decision_invalid_speech"):
        _decision_fields(
            '{"withdraw":true,"speech":"  "}',
            withdraw_contract,
        )


def test_boolean_decision_recovers_real_truncated_json_response() -> None:
    raw = '{"run_for_sheriff":true,"speech":"9号上警。我会把发言顺序和矛盾一条条捋清楚。"'

    assert _decision_fields(
        raw,
        _boolean_contract("run_for_sheriff", "required"),
    ) == (
        None,
        "9号上警。我会把发言顺序和矛盾一条条捋清楚。",
        "run_for_sheriff",
        True,
    )


@pytest.mark.parametrize(
    ("raw", "expected_speech"),
    [
        (
            '{"run_for_sheriff"：false，"speech"："12号不上警，先听发言。"}',
            "12号不上警，先听发言。",
        ),
        (
            '{"run_for_sheriff": false, "speech："我是12号，这轮不上警。"}',
            "我是12号，这轮不上警。",
        ),
    ],
)
def test_boolean_decision_nfkc_recovers_fullwidth_json_punctuation(
    raw: str,
    expected_speech: str,
) -> None:
    assert _decision_fields(
        raw,
        _boolean_contract("run_for_sheriff", "required"),
    ) == (
        None,
        expected_speech,
        "run_for_sheriff",
        False,
    )


def test_required_if_true_allows_silent_false_but_requires_true_speech() -> None:
    contract = _boolean_contract("explode", "required_if_true")
    assert _decision_fields('{"explode":false}', contract) == (
        None,
        None,
        "explode",
        False,
    )
    assert _decision_fields(
        '{"explode":false,"speech":"我暂时不自爆。"}',
        contract,
    ) == (None, None, "explode", False)
    with pytest.raises(V2QualityError, match="model_decision_invalid_speech"):
        _decision_fields('{"explode":true}', contract)
    assert _decision_fields(
        '{"explode":true,"speech":"我选择自爆！"}',
        contract,
    ) == (None, "我选择自爆！", "explode", True)


def test_forbidden_speech_is_preserved_for_action_normalization() -> None:
    contract = {
        "kind": "target",
        "target_policy": {"mode": "required"},
        "speech": {"mode": "forbidden"},
    }

    assert _decision_fields(
        '{"target_player_id":"seat_6","speech":"这段违规发言只用于审计。"}',
        contract,
    ) == (
        "seat_6",
        "这段违规发言只用于审计。",
        None,
        None,
    )


def test_model_speech_constraints_cap_characters_and_sentences() -> None:
    long_speech = "甲" * 299 + "。" + "乙" * 20

    assert _constrain_model_speech(
        long_speech,
        max_chars=300,
        max_sentences=None,
    ) == ("甲" * 299 + "。", ("max_chars_exceeded",))
    assert _constrain_model_speech(
        "我建议袭击3号。因为他的身份最可疑。",
        max_chars=None,
        max_sentences=1,
    ) == ("我建议袭击3号。", ("max_sentences_exceeded",))
    assert _constrain_model_speech(
        "我建议袭击3号",
        max_chars=None,
        max_sentences=1,
    ) == ("我建议袭击3号", ())


def test_model_speech_instructions_include_hard_contract_limits() -> None:
    assert _speech_output_instruction(
        {
            "speech": {
                "mode": "required",
                "max_chars": 300,
                "max_sentences": 1,
            }
        }
    ) == ("speech 必须是准备直接播报的非空自然中文。speech 不得超过300字。speech 只能包含一句话。")


def test_boolean_actions_keep_configured_thinking() -> None:
    parameters, source = _action_model_parameters(
        V2SpeechSpec(
            action_type="werewolf_self_explosion",
            phase_id="day_1",
            required_phase_state="public_discussion_open",
            objective="决定是否自爆",
            success_live_state="ready",
            success_phase_state="public_discussion_open",
            model_parameters={"thinking": "enabled", "max_tokens": 16384},
            decision_contract=V2DecisionContract(
                kind="boolean",
                boolean_field="explode",
                speech_mode="forbidden",
            ),
        )
    )

    assert parameters == {"thinking": "enabled", "max_tokens": 16384}
    assert source == "model_configuration"


def test_non_boolean_actions_keep_configured_thinking() -> None:
    parameters, source = _action_model_parameters(
        V2SpeechSpec(
            action_type="day_debate_speech",
            phase_id="day_1",
            required_phase_state="public_discussion_open",
            objective="发表分析",
            success_live_state="ready",
            success_phase_state="public_discussion_open",
            model_parameters={"thinking": "enabled", "max_tokens": 16384},
        )
    )

    assert parameters == {"thinking": "enabled", "max_tokens": 16384}
    assert source == "model_configuration"


def _target_contract() -> dict[str, Any]:
    return {
        "kind": "target",
        "target_policy": {"mode": "required"},
        "speech": {"mode": "required"},
    }


def _boolean_contract(field: str, speech_mode: str) -> dict[str, Any]:
    return {
        "kind": "boolean",
        "field": field,
        "speech": {"mode": speech_mode},
    }


def test_sse_parser_rejects_malformed_provider_events() -> None:
    assert _sse_data("event: response.output_text.delta") is None
    assert _sse_data("data: [DONE]") is None
    assert _sse_data('data: {"type":"response.output_text.delta","delta":"欢迎"}') == {
        "type": "response.output_text.delta",
        "delta": "欢迎",
    }
    with pytest.raises(V2ModelError, match="model_invalid_sse"):
        _sse_data("data: {")


def test_model_stream_wait_checks_durable_cancellation() -> None:
    async def delayed_lines():
        await asyncio.sleep(5)
        yield "data: [DONE]"

    def check_cancellation() -> None:
        raise V2GameCanceled("operator stop")

    with pytest.raises(V2GameCanceled):
        asyncio.run(
            _next_with_cancellation(
                delayed_lines().__aiter__(),
                timeout=5,
                check_cancellation=check_cancellation,
            )
        )


def test_tts_receive_wait_checks_durable_cancellation() -> None:
    class DelayedWebSocket:
        async def recv(self) -> bytes:
            await asyncio.sleep(5)
            return b""

    def check_cancellation() -> None:
        raise V2GameCanceled("operator stop")

    with pytest.raises(V2GameCanceled):
        asyncio.run(
            _receive(
                DelayedWebSocket(),
                timeout=5,
                check_cancellation=check_cancellation,
            )
        )


def test_public_player_projection_is_ordered_and_fail_closed() -> None:
    projected = project_public_player_seats(
        [
            {
                "seat": 2,
                "profile_id": "profile-2",
                "name": "",
                "model": "must-not-leak",
            },
            {
                "seat": 1,
                "profile_id": "profile-1",
                "name": "阿青",
                "avatar_image_url": "/avatar/profile-1",
                "personality": "must-not-leak",
            },
        ]
    )

    assert [item.model_dump(mode="json") for item in projected] == [
        {
            "seat": 1,
            "player_id": "profile-1",
            "display_name": "阿青",
            "avatar_url": "/avatar/profile-1",
            "alive": True,
        },
        {
            "seat": 2,
            "player_id": "profile-2",
            "display_name": "2号玩家",
            "avatar_url": None,
            "alive": True,
        },
    ]
    with pytest.raises(V2PublicProjectionError, match="duplicate player seat"):
        project_public_player_seats(
            [
                {"seat": 1, "profile_id": "profile-1"},
                {"seat": 1, "profile_id": "profile-2"},
            ]
        )
    with pytest.raises(V2PublicProjectionError, match="duplicate public player id"):
        project_public_player_seats(
            [
                {"seat": 1, "profile_id": "profile-1"},
                {"seat": 2, "profile_id": "profile-1"},
            ]
        )


def test_public_rule_projection_excludes_internal_rule_fields() -> None:
    projected = project_public_rule_snapshot(
        {
            "max_rounds": 8,
            "rule_set_revision_id": "private-revision",
            "lineup_quality_report": {"private": True},
            "rule_set": {
                "id": "classic_2",
                "name": "测试两人局",
                "version": "1",
                "player_count": 2,
                "content_hash": "private-hash",
                "roles": [
                    {"role": "狼人", "count": 1, "team": "private-team"},
                    {"role": "村民", "count": 1, "model_group": "private-model-group"},
                ],
                "sheriff_enabled": False,
                "werewolf_self_explosion_enabled": True,
                "exile_last_words_enabled": True,
                "first_night_last_words_enabled": True,
            },
        }
    )

    assert projected is not None
    assert projected.model_dump(mode="json") == {
        "rule_id": "classic_2",
        "name": "测试两人局",
        "version": "1",
        "player_count": 2,
        "roles": [{"role": "狼人", "count": 1}, {"role": "村民", "count": 1}],
        "max_rounds": 8,
        "sheriff_enabled": False,
        "werewolf_self_explosion_enabled": True,
        "exile_last_words_enabled": True,
        "first_night_last_words_enabled": True,
    }
    with pytest.raises(V2PublicProjectionError, match="does not match"):
        project_public_rule_snapshot(
            {
                "max_rounds": 8,
                "rule_set": {
                    "id": "broken",
                    "name": "错误规则",
                    "version": "1",
                    "player_count": 2,
                    "roles": [{"role": "村民", "count": 1}],
                },
            }
        )


def test_private_role_assignment_is_deterministic_and_public_status_is_sealed() -> None:
    players = [
        {"seat": 2, "profile_id": "profile-2"},
        {"seat": 1, "profile_id": "profile-1"},
    ]
    rule = {
        "rule_set": {
            "roles": [
                {"role": "狼人", "count": 1, "team": "werewolves"},
                {"role": "村民", "count": 1, "team": "village"},
            ]
        }
    }
    first = assign_private_roles(
        players_snapshot=players,
        rule_snapshot=rule,
        seed_hex="01" * 32,
    )
    second = assign_private_roles(
        players_snapshot=list(reversed(players)),
        rule_snapshot=rule,
        seed_hex="01" * 32,
    )

    assert first == second
    assert [item.seat for item in first.assignments] == [1, 2]
    assert sorted((item.role, item.team) for item in first.assignments) == [
        ("村民", "village"),
        ("狼人", "werewolves"),
    ]
    assert len(first.digest) == 64
    assert project_public_role_assignment_status(2).model_dump(mode="json") == {
        "state": "sealed",
        "assigned_count": 2,
    }
    assert project_public_role_assignment_status(None).model_dump(mode="json") == {
        "state": "unavailable",
        "assigned_count": 0,
    }
    with pytest.raises(V2RoleAssignmentError, match="does not match"):
        assign_private_roles(
            players_snapshot=players,
            rule_snapshot={"rule_set": {"roles": [{"role": "村民", "count": 1}]}},
            seed_hex="01" * 32,
        )


def test_god_view_access_and_projection_are_separate_and_fail_closed() -> None:
    token, token_hash = issue_god_view_access_token()
    assert token != token_hash
    assert verify_god_view_access_token(token=token, expected_sha256=token_hash)
    assert not verify_god_view_access_token(
        token="wrong-token-that-is-long-enough-to-be-valid",
        expected_sha256=token_hash,
    )

    projected = project_god_view_player_identities(
        players_snapshot=[
            {
                "seat": 1,
                "profile_id": "profile-1",
                "name": "阿青",
                "model": "must-not-leak",
                "personality": "must-not-leak",
            }
        ],
        assignments=[
            SimpleNamespace(
                seat=1,
                player_id="profile-1",
                role="狼人",
                team="werewolves",
            )
        ],
        player_states={
            "profile-1": SimpleNamespace(alive=True, death_cause=None),
        },
    )
    assert [item.model_dump(mode="json") for item in projected] == [
        {
            "seat": 1,
            "player_id": "profile-1",
            "display_name": "阿青",
            "avatar_url": None,
            "role": "狼人",
            "team": "werewolves",
            "alive": True,
            "death_cause": None,
        }
    ]
    with pytest.raises(V2GodViewProjectionError, match="does not match"):
        project_god_view_player_identities(
            players_snapshot=[{"seat": 1, "profile_id": "profile-1"}],
            assignments=[
                SimpleNamespace(
                    seat=1,
                    player_id="profile-2",
                    role="狼人",
                    team="werewolves",
                )
            ],
            player_states={
                "profile-1": SimpleNamespace(alive=True, death_cause=None),
            },
        )


def test_live_audio_frame_binds_pcm_to_one_presentation() -> None:
    pcm = b"\x01\x00\x02\x00"
    packet = audio_frame(
        _identity(),
        chunk_index=2,
        start_sample=4,
        sample_count=2,
        sample_rate=24000,
        pcm=pcm,
    )
    assert packet[:4] == b"LV2A"
    header_size = int.from_bytes(packet[4:6], "big")
    header = json.loads(packet[6 : 6 + header_size])
    assert header["presentation_id"] == "v2_pres_0000000000000001"
    assert header["speech_id"] == "v2_speech_0000000000000001"
    assert header["chunk_index"] == 2
    assert header["start_sample"] == 4
    assert packet[6 + header_size :] == pcm
    with pytest.raises(V2LiveProtocolError, match="sample_count"):
        audio_frame(
            _identity(),
            chunk_index=0,
            start_sample=0,
            sample_count=3,
            sample_rate=24000,
            pcm=pcm,
        )


def test_voice_recorder_atomically_saves_exact_pcm(tmp_path: Path) -> None:
    recorder = V2VoiceRecorder(
        root=tmp_path,
        storage_key="game/voice.wav",
        sample_rate=24000,
    )
    chunks = (b"\x01\x00" * 120, b"\x02\x00" * 240)
    assert recorder.append(chunks[0]) == 120
    assert recorder.append(chunks[1]) == 240
    result = recorder.finalize()

    final_path = tmp_path / "game/voice.wav"
    assert final_path.is_file()
    assert not (tmp_path / "game/voice.wav.writing").exists()
    with wave.open(str(final_path), "rb") as saved:
        assert saved.getframerate() == 24000
        assert saved.getnchannels() == 1
        assert saved.getnframes() == 360
        assert saved.readframes(360) == b"".join(chunks)
    assert result.sample_count == 360
    assert result.duration_ms == 15
    assert result.pcm_sha256 == hashlib.sha256(b"".join(chunks)).hexdigest()


def test_voice_recorder_abort_leaves_no_partial_asset(tmp_path: Path) -> None:
    recorder = V2VoiceRecorder(
        root=tmp_path,
        storage_key="game/voice.wav",
        sample_rate=24000,
    )
    recorder.append(b"\x01\x00")
    recorder.abort()
    assert not (tmp_path / "game/voice.wav").exists()
    assert not (tmp_path / "game/voice.wav.writing").exists()
    with pytest.raises(V2VoiceRecordingError, match="closed"):
        recorder.append(b"\x01\x00")


def test_tts_v3_client_frame_layout_matches_event_protocol() -> None:
    request = _encode_event(
        event=_START_SESSION,
        payload=b'{"event":100}',
        session_id="session-1",
    )
    assert request[:4] == bytes((0x11, 0x14, 0x10, 0x00))
    assert struct.unpack_from(">i", request, 4)[0] == _START_SESSION
    session_size = struct.unpack_from(">I", request, 8)[0]
    assert request[12 : 12 + session_size] == b"session-1"

    session = b"session-1"
    pcm = b"\x01\x00\x02\x00"
    response = bytearray((0x11, (_AUDIO_SERVER << 4) | _WITH_EVENT, 0x00, 0x00))
    response.extend(struct.pack(">i", 352))
    response.extend(struct.pack(">I", len(session)))
    response.extend(session)
    response.extend(struct.pack(">I", len(pcm)))
    response.extend(pcm)
    decoded = _decode_frame(bytes(response))
    assert decoded.message_type == _AUDIO_SERVER
    assert decoded.event == 352
    assert decoded.payload == pcm

    connection_id = b"connection-1"
    metadata = b'{"status_code":20000000}'
    started = bytearray((0x11, 0x94, 0x10, 0x00))
    started.extend(struct.pack(">i", _CONNECTION_STARTED))
    started.extend(struct.pack(">I", len(connection_id)))
    started.extend(connection_id)
    started.extend(struct.pack(">I", len(metadata)))
    started.extend(metadata)
    assert _decode_frame(bytes(started)).event == _CONNECTION_STARTED

    assert _TASK_REQUEST == 200
