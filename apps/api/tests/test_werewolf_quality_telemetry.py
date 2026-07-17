from app.werewolf.quality_telemetry import (
    record_speech_quality,
    render_speech_quality_metrics,
    reset_speech_quality_metrics_for_tests,
)


def test_speech_quality_metrics_use_only_bounded_labels() -> None:
    reset_speech_quality_metrics_for_tests()
    record_speech_quality(
        phase="day",
        report={
            "novelty_score": 0.25,
            "issues": [
                {
                    "code": "repeated_debate_phrase",
                    "severity": "rewrite",
                },
                {
                    "code": "SENTINEL_PRIVATE_DRAFT",
                    "severity": "warning",
                },
            ],
        },
        attempt_count=2,
        retry_exhausted=True,
        retry_duration_ms=1250,
    )

    metrics = render_speech_quality_metrics()

    assert (
        'werewolf_speech_quality_total{code="repeated_debate_phrase",'
        'result="exhausted",phase="day"} 1'
    ) in metrics
    assert 'code="unknown",result="warning",phase="day"' in metrics
    assert 'result="exhausted",phase="day"} 1' in metrics
    assert 'werewolf_speech_novelty_score_sum{phase="day"} 0.25' in metrics
    assert (
        'werewolf_speech_quality_retry_extra_duration_seconds_sum'
        '{result="exhausted",phase="day"} 1.25'
    ) in metrics
    assert (
        'werewolf_speech_quality_retry_extra_duration_seconds_count'
        '{result="exhausted",phase="day"} 1'
    ) in metrics
    assert "SENTINEL_PRIVATE_DRAFT" not in metrics
