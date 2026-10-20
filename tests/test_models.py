from aiwork.models import UsageEvent


def test_usage_event_requires_ids_and_tokens():
    ev = UsageEvent(
        run_id="r1",
        step_id="s1",
        agent="cursor",
        role="parent",
        model_requested="composer-2",
        model_actual="composer-2",
        input_uncached=7,
        cache_read=100,
        cache_write=20,
        output=50,
        cost_usd=None,
        session_id="sess",
        dirty=False,
        mismatch=False,
    )
    assert ev.total_input() == 127
