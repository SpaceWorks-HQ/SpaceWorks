from apps.hardware_requests.tasks import send_return_reminders_task


def test_send_return_reminders_task_runs_service_in_eager_mode(monkeypatch):
    result = {"sent": 3, "skipped": 1}

    monkeypatch.setattr(
        "apps.hardware_requests.tasks.run_return_reminders",
        lambda: result,
    )

    assert send_return_reminders_task() == result
    eager = send_return_reminders_task.delay()
    assert eager.successful()
    assert eager.result == result
