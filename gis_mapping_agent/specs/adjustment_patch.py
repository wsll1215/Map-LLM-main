from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


ACTION_ALIASES = {
    "hide_layer": "toggle_layer_visibility",
    "show_layer": "toggle_layer_visibility",
    "set_layer_visibility": "toggle_layer_visibility",
    "update_layer_style": "style_layer",
    "update_title": "update_map_config",
    "modify_generalization_params": "update_generalization_params",
}

PARAM_ALIASES = {
    "retention_ratio": "keep_ratio",
    "line_width": "linewidth",
}


class PatchOperation(BaseModel):
    action: str
    target: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class AdjustmentPatch(BaseModel):
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    operations: List[PatchOperation] = Field(default_factory=list)
    reason: Optional[str] = None

    def normalized(self) -> "AdjustmentPatch":
        return self.__class__(
            session_id=self.session_id,
            task_id=self.task_id,
            reason=self.reason,
            operations=[
                PatchOperation(
                    action=ACTION_ALIASES.get(operation.action, operation.action),
                    target=operation.target,
                    parameters={PARAM_ALIASES.get(k, k): v for k, v in operation.parameters.items()},
                    description=operation.description,
                )
                for operation in self.operations
            ],
        )
