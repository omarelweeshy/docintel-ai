from app.observability.trace import Trace, bind_trace, current_trace, traced_stage
from app.providers.ollama import record_usage


def test_trace_is_bound_only_inside_context_and_stages_accumulate():
    assert current_trace() is None
    with traced_stage("ignored"):
        pass
    trace = Trace()
    with bind_trace(trace):
        assert current_trace() is trace
        for _ in range(2):
            with traced_stage("retrieve"):
                pass
    assert current_trace() is None
    assert set(trace.stages_ms) == {"retrieve"}
    assert trace.stages_ms["retrieve"] >= 0


def test_ollama_usage_is_recorded_without_text():
    trace = Trace()
    with bind_trace(trace):
        record_usage({"prompt_eval_count": 12, "eval_count": 30, "load_duration": 2_000_000}, "gen")
        record_usage({"prompt_eval_count": 3, "load_duration": 0, "message": "secret"}, "gen")
    assert trace.tokens == {"gen_prompt": 15, "gen_output": 30}
    assert trace.attributes == {"gen_load_ms": 2.0}
    assert "secret" not in str(trace.to_dict())
