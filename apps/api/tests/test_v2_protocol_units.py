from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import wave

import pytest

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
    _decision_fields,
    _required_speech,
    _sse_data,
)
from app.v2.protocol import V2LiveProtocolError, audio_frame
from app.v2.public_projection import (
    V2PublicProjectionError,
    project_public_player_seats,
    project_public_role_assignment_status,
    project_public_rule_snapshot,
)
from app.v2.repository import V2PresentationIdentity
from app.v2.role_assignment import V2RoleAssignmentError, assign_private_roles
from app.v2.tts_client import (
    _AUDIO_SERVER,
    _CONNECTION_STARTED,
    _START_SESSION,
    _TASK_REQUEST,
    _WITH_EVENT,
    _decode_frame,
    _encode_event,
)
from app.v2.voice_recorder import V2VoiceRecorder, V2VoiceRecordingError


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
    assert _decision_fields(raw) == (
        "player-2",
        "先听二号怎么说。之后我再判断！",
    )


def test_decision_fields_keep_only_fundamental_failures() -> None:
    with pytest.raises(V2QualityError, match="model_decision_invalid_json"):
        _decision_fields("not json")
    with pytest.raises(V2QualityError, match="model_decision_invalid_shape"):
        _decision_fields('{"speech":"我先保留意见。"}')
    with pytest.raises(V2QualityError, match="model_decision_invalid_target"):
        _decision_fields('{"target_player_id":3,"speech":"我投三号。"}')
    with pytest.raises(V2QualityError, match="model_decision_invalid_speech"):
        _decision_fields('{"target_player_id":null,"speech":"  "}')


def test_sse_parser_rejects_malformed_provider_events() -> None:
    assert _sse_data("event: response.output_text.delta") is None
    assert _sse_data("data: [DONE]") is None
    assert _sse_data('data: {"type":"response.output_text.delta","delta":"欢迎"}') == {
        "type": "response.output_text.delta",
        "delta": "欢迎",
    }
    with pytest.raises(V2ModelError, match="model_invalid_sse"):
        _sse_data("data: {")


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
