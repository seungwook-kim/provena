"""Langfuse 트레이스가 요청 헤더의 추적 표시 때문에 버려지지 않는지(F4: 운영 `/chat` 284건 중 116건만 남던 문제)."""
from __future__ import annotations

from backend.services import tracing


def test_sampler_defaults_to_always_on(monkeypatch):
    monkeypatch.setenv(tracing.SAMPLER_ENV, "")
    tracing._keep_all_traces()
    import os
    assert os.environ[tracing.SAMPLER_ENV] == "always_on"


def test_operator_sampler_is_kept(monkeypatch):
    monkeypatch.setenv(tracing.SAMPLER_ENV, "parentbased_always_on")
    tracing._keep_all_traces()
    import os
    assert os.environ[tracing.SAMPLER_ENV] == "parentbased_always_on"


def test_unsampled_traceparent_is_still_recorded(monkeypatch):
    """`always_on`으로 만든 TracerProvider는 부모가 '추적 안 함'이어도 span을 기록한다(기본값은 버린다)."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

    parent = trace.set_span_in_context(NonRecordingSpan(SpanContext(
        trace_id=0x0AF7651916CD43DD8448EB211C80319C, span_id=0xB7AD6B7169203331, is_remote=True, trace_flags=TraceFlags(0))))
    monkeypatch.setenv(tracing.SAMPLER_ENV, "parentbased_always_on")   # SDK 기본값과 같다
    assert not TracerProvider().get_tracer("t").start_span("question", context=parent).is_recording()   # 고치기 전 동작
    monkeypatch.setenv(tracing.SAMPLER_ENV, "")
    tracing._keep_all_traces()
    assert TracerProvider().get_tracer("t").start_span("question", context=parent).is_recording()
