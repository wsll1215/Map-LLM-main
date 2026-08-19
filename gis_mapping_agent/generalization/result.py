from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class GeneralizationResult:
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    output_gdf: Any = None
    input_gdf: Any = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_legacy_dict(self) -> Dict[str, Any]:
        return {
            "success": True,
            "source_scale": self.params.get("source_scale"),
            "target_scale": self.params.get("target_scale"),
            "algorithm": self.params.get("algorithm"),
            "keep_ratio": self.params.get("keep_ratio"),
            "input_path": self.input_path,
            "filepath": self.output_path,
            "input_gdf": self.input_gdf,
            "output_gdf": self.output_gdf,
            "statistics": self.metrics,
            **self.meta,
        }
