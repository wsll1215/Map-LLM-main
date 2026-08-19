from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MapSpec(BaseModel):
    map_id: Optional[str] = None
    title: Optional[str] = None
    extent: Optional[List[float]] = None
    crs: Optional[str] = None
    background_color: str = "white"
    figsize: Optional[List[float]] = None
    dpi: Optional[int] = None
    data_directory: Optional[str] = None
    data_files: List[str] = Field(default_factory=list)
    layer_styles: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    auto_legend: bool = True
    auto_scalebar: bool = True
    auto_compass: bool = True

    @classmethod
    def from_legacy_dict(cls, payload: Dict[str, Any]) -> "MapSpec":
        return cls.model_validate(payload)
