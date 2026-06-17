import json
import pytest
from agent.memory import StructuredMemory


def test_initial_state():
    mem = StructuredMemory()
    assert mem.plan == {}
    assert mem.findings == {"items": [], "summary": ""}
    assert mem.context == {}


def test_update_plan_merges():
    mem = StructuredMemory()
    mem.update("plan", {"goal": "test", "steps": [{"id": 1, "action": "step1", "status": "pending", "note": ""}]})
    assert mem.plan["goal"] == "test"
    assert len(mem.plan["steps"]) == 1
    mem.update("plan", {"current_step": 2})
    assert mem.plan["goal"] == "test"
    assert mem.plan["current_step"] == 2


def test_update_findings_appends_items():
    mem = StructuredMemory()
    mem.update("findings", {"items": [{"a": 1}], "summary": "1 item"})
    assert len(mem.findings["items"]) == 1
    mem.update("findings", {"items": [{"a": 2}], "summary": "2 items"})
    assert len(mem.findings["items"]) == 2
    assert mem.findings["summary"] == "2 items"


def test_update_context_replaces():
    mem = StructuredMemory()
    mem.update("context", {"current_url": "https://example.com", "current_action": "browsing"})
    assert mem.context["current_url"] == "https://example.com"
    mem.update("context", {"current_url": "https://other.com", "current_action": "clicking"})
    assert mem.context["current_url"] == "https://other.com"
    assert mem.context["current_action"] == "clicking"


def test_format_for_injection_empty():
    mem = StructuredMemory()
    text = mem.format_for_injection()
    assert "[计划]" not in text or "暂无计划" in text


def test_format_for_injection_with_plan():
    mem = StructuredMemory()
    mem.update("plan", {
        "goal": "采集100个Python岗位",
        "steps": [
            {"id": 1, "action": "打开boss直聘", "status": "done", "note": ""},
            {"id": 2, "action": "选择成都", "status": "in_progress", "note": ""},
            {"id": 3, "action": "搜索Python", "status": "pending", "note": ""},
        ],
        "current_step": 2,
    })
    text = mem.format_for_injection()
    assert "采集100个Python岗位" in text
    assert "✓" in text or "→" in text


def test_format_for_injection_with_findings():
    mem = StructuredMemory()
    mem.update("findings", {"items": [{"岗位": "Python", "工资": "10K"}], "summary": "已采集1条"})
    text = mem.format_for_injection()
    assert "已采集" in text


def test_read_returns_all():
    mem = StructuredMemory()
    mem.update("plan", {"goal": "test"})
    result = mem.read()
    assert "计划" in result or "plan" in result.lower()


def test_update_invalid_section_raises():
    mem = StructuredMemory()
    with pytest.raises(ValueError):
        mem.update("invalid_section", {})
