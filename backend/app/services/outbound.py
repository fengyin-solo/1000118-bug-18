"""出库管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "outbound"
REQUIRED_FIELDS = ["出库单号", "客户名称", "货物名称"]
STATUS_ORDER = ["待拣货", "已拣货", "已发运", "已取消"]
ACTION_RULES = {"确认拣货": "已拣货", "安排发运": "已发运", "取消出库": "已取消"}
ALLOWED_TRANSITIONS: dict[str, dict[str, str]] = {
    "确认拣货": {"待拣货": "已拣货"},
    "安排发运": {"已拣货": "已发运"},
    "取消出库": {"待拣货": "已取消", "已拣货": "已取消"},
}
BATCH_ACTIONS = {"安排发运"}
NEGATIVE_ACTIONS = []


class OutboundService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("出库单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"出库单 {entry_id} 不存在或已归档"
        return self._change_status(entry, action)

    def run_batch_action(
        self,
        entry_ids: list[Any],
        action: str,
    ) -> tuple[dict[str, Any], bool]:
        """按 ID 执行批量动作；入参非法时不改任何记录。

        单条是否允许流转由当前状态决定，结果与请求 ID 一一对应。前端只根据
        汇总结果重新拉取列表，不自行拼接状态，从而避免成功/失败串位和重复行。
        """
        action = action.strip()
        if action not in ACTION_RULES:
            return self._batch_payload_error(action, f"动作「{action}」不属于出库管理可执行范围"), False
        if action not in BATCH_ACTIONS:
            return self._batch_payload_error(action, f"动作「{action}」暂不支持批量执行"), False
        if not entry_ids:
            return self._batch_payload_error(action, "请至少选择一条出库单"), False

        normalized_ids: list[int] = []
        for raw_id in entry_ids:
            if isinstance(raw_id, bool) or not isinstance(raw_id, int):
                return self._batch_payload_error(action, "出库单编号必须是整数"), False
            if raw_id <= 0:
                return self._batch_payload_error(action, "出库单编号必须大于 0"), False
            normalized_ids.append(raw_id)

        unique_ids = list(dict.fromkeys(normalized_ids))
        if len(unique_ids) != len(normalized_ids):
            return self._batch_payload_error(action, "同一批次中不能重复选择出库单"), False

        entries = [store.find(MODULE, entry_id) for entry_id in unique_ids]
        if any(entry is None for entry in entries):
            missing_ids = [
                entry_id for entry_id, entry in zip(unique_ids, entries) if entry is None
            ]
            return (
                self._batch_payload_error(
                    action,
                    f"出库单 {'、'.join(str(item) for item in missing_ids)} 不存在或已归档",
                ),
                False,
            )

        planned: list[tuple[int, dict[str, Any], str | None, str]] = []
        for entry_id, entry in zip(unique_ids, entries):
            assert entry is not None
            target, message = self._transition_target(entry, action)
            planned.append((entry_id, entry, target, message))

        success_count = sum(1 for _, _, target, _ in planned if target is not None)
        failure_count = len(planned) - success_count
        if success_count == 0:
            results = [
                {
                    "id": entry_id,
                    "code": str(entry.get("出库单号", "")),
                    "ok": False,
                    "message": message,
                    "entry": entry,
                }
                for entry_id, entry, _, message in planned
            ]
            return {
                "ok": False,
                "action": action,
                "total": len(results),
                "success_count": 0,
                "failure_count": failure_count,
                "message": "整组安排发运失败，原出库单均已保留",
                "results": results,
            }, True

        results: list[dict[str, Any]] = []
        for entry_id, entry, target, message in planned:
            changed = None
            if target is not None:
                self._apply_status(entry, target, action)
                changed = entry
                message = "出库单已安排发运"
            results.append({
                "id": entry_id,
                "code": str(entry.get("出库单号", "")),
                "ok": changed is not None,
                "message": message,
                "entry": changed,
            })

        if failure_count:
            message = f"安排发运完成：成功 {success_count} 条，失败 {failure_count} 条"
            ok = True
        else:
            message = f"安排发运完成：成功 {success_count} 条"
            ok = True

        return {
            "ok": ok,
            "action": action,
            "total": len(results),
            "success_count": success_count,
            "failure_count": failure_count,
            "message": message,
            "results": results,
        }, True

    def _change_status(
        self,
        entry: dict[str, Any],
        action: str,
    ) -> tuple[dict[str, Any] | None, str]:
        action = action.strip()
        target, message = self._transition_target(entry, action)
        if target is None:
            return None, message
        self._apply_status(entry, target, action)
        return entry, f"出库单已{action}"

    def _transition_target(
        self,
        entry: dict[str, Any],
        action: str,
    ) -> tuple[str | None, str]:
        action = action.strip()
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于出库管理可执行范围"

        current_status = str(entry.get("status") or "")
        target = ALLOWED_TRANSITIONS.get(action, {}).get(current_status)
        if target is None:
            return None, f"出库单 {entry.get('出库单号', entry.get('id'))} 当前为{current_status}，不能{action}"
        return target, ""

    def _apply_status(self, entry: dict[str, Any], target: str, action: str) -> None:
        entry["status"] = target
        entry["pending"] = target not in {"已发运", "已取消"}
        entry["abnormal"] = action in NEGATIVE_ACTIONS

    def _batch_payload_error(self, action: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "action": action,
            "total": 0,
            "success_count": 0,
            "failure_count": 0,
            "message": message,
            "results": [],
        }
