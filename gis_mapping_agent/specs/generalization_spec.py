from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class GeneralizationSpec(BaseModel):
    data_file: str
    data_directory: Optional[str] = None
    algorithm: str = "stroke"
    source_scale: int = 500
    target_scale: int = 2000
    keep_ratio: Optional[float] = None
    hierarchy_method: Optional[str] = None
    hierarchy_attribute: Optional[str] = None
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_legacy_dict(cls, payload: Dict[str, Any]) -> "GeneralizationSpec":
        return cls.model_validate(payload)
