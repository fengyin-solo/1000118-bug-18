"""出库管理业务规则：状态流转、字段校验与筛选口径都收在这里。

批量安排发运采用「先整组校验、后统一回写」的口径：只要有一条出库单不满足
发运条件，整组都不改动，原有出库单原样保留；校验全部通过后才就地更新状态，
不会新增任何记录，因此重复提交不会产生重复单据。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "outbound"
REQUIRED_FIELDS = ["出库单号", "客户名称", "货物名称"]
STATUS_ORDER = ["待拣货", "已拣货", "已发运", "已取消"]
ACTION_RULES = {"确认拣货": "已拣货", "安排发运": "已发运", "取消出库": "已取消"}
# 每个动作允许的前置状态：逐条与批量共用同一套流转规则。
ACTION_REQUIRED_STATUS = {
    "确认拣货": {"待拣货"},
    "安排发运": {"已拣货"},
    "取消出库": {"待拣货", "已拣货"},
}
# 目前只对「安排发运」开放批量入口。
BATCH_ACTIONS = {"安排发运"}
TERMINAL_STATUSES = {"已发运", "已取消"}
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
        message = self._transition_error(entry, action)
        if message is not None:
            return None, message
        self._apply_transition(entry, action)
        return entry, f"出库单已{action}"

    def batch_run_action(self, action: str, raw_ids: Any) -> dict[str, Any]:
        """批量执行动作，返回整组结论与逐条结论（同一口径，供列表/详情/导出共用）。"""
        if not action:
            return self._batch_failure(action, "未指定要执行的动作", [])
        if action not in BATCH_ACTIONS:
            return self._batch_failure(action, f"批量操作暂不支持「{action}」，请逐条处理", [])

        # 标识归一化：去空白、去重复，保证同一批次提交两次不会按多条计数。
        ids: list[int] = []
        invalid: list[str] = []
        for value in raw_ids or []:
            try:
                entry_id = int(value)
            except (TypeError, ValueError):
                invalid.append(str(value))
                continue
            if entry_id not in ids:
                ids.append(entry_id)
        if invalid:
            return self._batch_failure(
                action,
                f"存在无法识别的出库单标识：{'、'.join(invalid)}，整组未提交，原有出库单保持不变",
                [],
            )
        if not ids:
            return self._batch_failure(action, "请先勾选要安排发运的出库单", [])

        # 第一阶段：只做校验并形成逐条计划，此时不写任何状态。
        plans: list[tuple[int, dict[str, Any] | None, bool, str]] = []
        for entry_id in ids:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                plans.append((entry_id, None, False, f"出库单 {entry_id} 不存在或已归档"))
                continue
            reason = self._transition_error(entry, action)
            if reason is not None:
                plans.append((entry_id, entry, False, reason))
            else:
                plans.append((entry_id, entry, True, "校验通过"))

        rejected = [plan for plan in plans if not plan[2]]
        if rejected:
            # 整组失败：一条都不回写，全部出库单保留原状态，逐条结论如实标记为未执行。
            items = [
                {
                    "id": entry_id,
                    "code": self._code(entry),
                    "ok": False,
                    "message": (
                        f"整组校验未通过，保留原状态「{entry.get('status')}」，未安排发运"
                        if eligible else reason
                    ),
                }
                for entry_id, entry, eligible, reason in plans
            ]
            return {
                "ok": False,
                "action": action,
                "message": (
                    f"整组发运未提交：{len(rejected)} 条不满足发运条件，"
                    f"全部 {len(plans)} 张出库单保持原状态"
                ),
                "total": len(plans),
                "success_count": 0,
                "failure_count": len(plans),
                "items": items,
            }

        # 第二阶段：校验全部通过，就地回写状态（更新而非新增，杜绝重复记录）。
        items: list[dict[str, Any]] = []
        for entry_id, entry, _eligible, _reason in plans:
            assert entry is not None
            self._apply_transition(entry, action)
            items.append({
                "id": entry_id,
                "code": self._code(entry),
                "ok": True,
                "message": "安排发运成功，状态已更新为「已发运」",
            })
        return {
            "ok": True,
            "action": action,
            "message": f"批量安排发运完成：{len(items)} 张出库单均已发运",
            "total": len(items),
            "success_count": len(items),
            "failure_count": 0,
            "items": items,
        }

    def _transition_error(self, entry: dict[str, Any], action: str) -> str | None:
        """返回不能执行该动作的原因；可以执行时返回 None。"""
        if action not in ACTION_RULES:
            return f"动作「{action}」不属于出库管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return f"目标状态「{target}」不在允许的状态序列里"
        status = str(entry.get("status") or "")
        if status not in ACTION_REQUIRED_STATUS[action]:
            code = self._code(entry)
            if status == "已取消":
                hint = "出库单已取消，不能再执行该动作"
            elif action == "安排发运" and status == "已发运":
                hint = "出库单已发运，请勿重复提交"
            elif action == "安排发运" and status == "待拣货":
                hint = "出库单尚未确认拣货，不能安排发运"
            else:
                hint = f"当前状态为「{status}」，不能{action}"
            return f"出库单 {code} {hint}"
        return None

    def _apply_transition(self, entry: dict[str, Any], action: str) -> None:
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target not in TERMINAL_STATUSES
        entry["abnormal"] = action in NEGATIVE_ACTIONS

    @staticmethod
    def _code(entry: dict[str, Any] | None) -> str:
        if entry is None:
            return ""
        return str(entry.get("出库单号") or entry.get("id") or "")

    @staticmethod
    def _batch_failure(action: str, message: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "ok": False,
            "action": action,
            "message": message,
            "total": len(items),
            "success_count": 0,
            "failure_count": len(items),
            "items": items,
        }
