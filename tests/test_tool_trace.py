import json

from gis_mapping_agent.state.trace import ToolTraceRecord, ToolTraceStore, summarize_value


def test_tool_trace_store_writes_sanitized_jsonl(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    store = ToolTraceStore(trace_path)

    store.append(
        ToolTraceRecord(
            session_id="s1",
            task_id="t1",
            tool_name="render",
            args=summarize_value({"input_gdf": object(), "color": "red"}),
            result_summary={"ok": True},
            success=True,
            error=None,
            duration_ms=12,
            created_at="2026-01-01T00:00:00",
        )
    )

    payload = json.loads(trace_path.read_text(encoding="utf-8").strip())
    assert payload["session_id"] == "s1"
    assert payload["args"]["input_gdf"] == "<omitted>"
    assert payload["args"]["color"] == "red"
