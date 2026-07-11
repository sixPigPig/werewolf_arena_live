from threading import Event

from app.admin import voice_jobs


def test_continuous_worker_drains_jobs_until_stop(monkeypatch) -> None:
    stop_event = Event()
    claimed = iter(["job-1", "job-2"])

    def fake_run_next(_session_factory) -> str:
        job_id = next(claimed)
        if job_id == "job-2":
            stop_event.set()
        return job_id

    monkeypatch.setattr(voice_jobs, "run_next_voice_generation_job", fake_run_next)
    observed: list[str] = []

    processed = voice_jobs.run_voice_generation_worker(
        object(),
        stop_event=stop_event,
        poll_seconds=0.25,
        on_job=observed.append,
    )

    assert processed == 2
    assert observed == ["job-1", "job-2"]


def test_once_worker_returns_without_waiting_on_empty_queue(monkeypatch) -> None:
    stop_event = Event()
    monkeypatch.setattr(
        voice_jobs,
        "run_next_voice_generation_job",
        lambda _session_factory: None,
    )

    processed = voice_jobs.run_voice_generation_worker(
        object(),
        stop_event=stop_event,
        poll_seconds=60,
        once=True,
    )

    assert processed == 0
