import json
from typing import Any


class StructuredMemory:
    def __init__(self):
        self.plan: dict = {}
        self.findings: dict = {"items": [], "summary": ""}
        self.context: dict = {}

    def update(self, section: str, data: str | dict) -> None:
        if isinstance(data, str):
            data = json.loads(data)

        if section == "plan":
            self._merge_plan(data)
        elif section == "findings":
            self._merge_findings(data)
        elif section == "context":
            self.context = data
        else:
            raise ValueError(f"Unknown memory section: {section}")

    def _merge_plan(self, data: dict) -> None:
        if "steps" in data and "steps" not in self.plan:
            self.plan["steps"] = data["steps"]
        elif "steps" in data and "steps" in self.plan:
            existing = {s["id"]: s for s in self.plan["steps"]}
            for step in data["steps"]:
                existing[step["id"]] = step
            self.plan["steps"] = sorted(existing.values(), key=lambda s: s["id"])

        for key, value in data.items():
            if key != "steps":
                self.plan[key] = value

    def _merge_findings(self, data: dict) -> None:
        if "items" in data:
            self.findings["items"].extend(data["items"])
        if "summary" in data:
            self.findings["summary"] = data["summary"]

    def read(self) -> str:
        return self.format_for_injection()

    def format_for_injection(self) -> str:
        parts = []
        parts.append(self._format_plan())
        parts.append(self._format_findings())
        parts.append(self._format_context())
        return "\n\n".join(parts)

    def _format_plan(self) -> str:
        if not self.plan:
            return "[计划] 暂无计划"

        lines = [f"[计划] {self.plan.get('goal', '未设定目标')}"]
        current = self.plan.get("current_step", 0)
        for step in self.plan.get("steps", []):
            sid = step["id"]
            action = step["action"]
            note = f" — {step['note']}" if step.get("note") else ""
            if step["status"] == "done":
                marker = "✓"
            elif step["status"] == "failed":
                marker = "✗"
            elif step["status"] == "in_progress" or sid == current:
                marker = "→"
            else:
                marker = "·"
            lines.append(f"  {marker} {sid}. {action}{note}")

        return "\n".join(lines)

    def _format_findings(self) -> str:
        count = len(self.findings.get("items", []))
        summary = self.findings.get("summary", "")
        if count == 0:
            return "[数据] 暂无数据。"
        if summary:
            return f"[数据] {summary}"
        return f"[数据] 已采集 {count} 条。"

    def _format_context(self) -> str:
        if not self.context:
            return "[状态] 初始状态"
        url = self.context.get("current_url", "未知页面")
        action = self.context.get("current_action", "")
        parts = [f"[状态] 在 {url}"]
        if action:
            parts.append(action)
        errors = self.context.get("errors", [])
        for err in errors[:3]:
            parts.append(f"⚠ {err}")
        return " | ".join(parts)
