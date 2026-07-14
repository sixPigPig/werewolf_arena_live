from app.werewolf.judge_narration import (
    dawn_result_cue,
    hunter_result_cue,
    hunter_start_cues,
    idiot_reveal_cues,
    self_explosion_cues,
    sheriff_badge_cues,
    sheriff_election_cues,
    sheriff_tie_cues,
)
from app.werewolf.models import SheriffBadgeResolution, SheriffElectionResolution


def election_resolution(**overrides: object) -> SheriffElectionResolution:
    values: dict[str, object] = {
        "schema_version": 1,
        "outcome": "badge_lost",
        "reason_code": "no_off_sheriff_voters",
        "reason_text": "警下无人可投票",
        "sheriff": None,
        "candidates": ["5号玩家", "10号玩家"],
        "withdrawn": [],
        "final_candidates": ["5号玩家", "10号玩家"],
        "voters": [],
        "votes": {},
        "pk_candidates": [],
        "runoff_votes": {},
        "badge_lost": True,
        "election_pending": False,
    }
    values.update(overrides)
    return SheriffElectionResolution(**values)  # type: ignore[arg-type]


def test_cue_payload_v1_is_stable_and_public() -> None:
    cue = sheriff_election_cues(election_resolution())[0]

    assert cue.cue_id == "sheriff_no_voters"
    assert cue.to_payload() == {
        "schema_version": 1,
        "cue_id": "sheriff_no_voters",
        "cue": "sheriff_no_voters",
        "visible_text": "本轮没有警下投票者，警徽流失。",
        "static_asset_id": None,
        "params": {
            "outcome": "badge_lost",
            "reason_code": "no_off_sheriff_voters",
        },
        "outcome": "badge_lost",
        "reason_code": "no_off_sheriff_voters",
    }


def test_dawn_result_only_exposes_public_death_names() -> None:
    peaceful = dawn_result_cue([])
    deaths = dawn_result_cue(["2号玩家", "7号玩家"])

    assert peaceful.cue_id == "dawn_peaceful"
    assert deaths.cue_id == "dawn_deaths"
    assert deaths.params == {"players": ["2号玩家", "7号玩家"]}
    assert "狼人" not in deaths.visible_text
    assert "女巫" not in deaths.visible_text
    assert "毒" not in deaths.visible_text


def test_sheriff_tie_and_runoff_tied_cue_order() -> None:
    assert [cue.cue_id for cue in sheriff_tie_cues(["5号玩家", "8号玩家"])] == [
        "sheriff_tie",
        "sheriff_pk_start",
        "sheriff_runoff_vote",
    ]
    runoff_tied = election_resolution(
        reason_code="runoff_tied",
        reason_text="警长二轮投票未产生唯一领先者",
    )
    assert [cue.cue_id for cue in sheriff_election_cues(runoff_tied)] == [
        "sheriff_runoff_tied",
        "sheriff_no_badge",
    ]


def test_self_explosion_cues_preserve_public_interruption_context() -> None:
    cues = self_explosion_cues(
        "9号玩家",
        stage="debate",
        completed_actors=["10号玩家"],
        pending_actors=["5号玩家", "7号玩家"],
    )

    assert [cue.cue_id for cue in cues] == [
        "werewolf_self_explosion",
        "self_explosion_skip",
    ]
    assert cues[1].params["pending_actors"] == ["5号玩家", "7号玩家"]
    assert "投票终止" in cues[1].visible_text


def test_hunter_idiot_and_badge_causal_cue_sequences() -> None:
    assert [cue.cue_id for cue in hunter_start_cues("4号玩家")] == [
        "hunter_shot_start",
        "hunter_shot_choose",
    ]
    assert hunter_result_cue("8号玩家").cue_id == "hunter_shot_result"
    assert hunter_result_cue(None).cue_id == "hunter_shot_skipped"
    assert [cue.cue_id for cue in idiot_reveal_cues("6号玩家")] == [
        "idiot_reveal",
        "idiot_stays",
    ]
    badge = SheriffBadgeResolution(
        schema_version=1,
        outcome="transferred",
        from_player="4号玩家",
        to_player="8号玩家",
        reason_code="owner_selected_target",
    )
    assert [cue.cue_id for cue in sheriff_badge_cues(badge)] == [
        "badge_owner_out",
        "badge_transfer",
    ]
