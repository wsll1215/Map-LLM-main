from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


RenderMode = Literal["geojson", "geojson-worker", "mvt", "pmtiles"]


class MapSpecStyle(BaseModel):
    fill: Optional[str] = None
    stroke: Optional[str] = None
    stroke_width: float = Field(default=1.0, ge=0)
    opacity: float = Field(default=1.0, ge=0, le=1)
    line_dash: List[float] = Field(default_factory=list)
    point_radius: float = Field(default=5.0, ge=0)
    label: Optional[Dict[str, Any]] = None


class MapLayerSpec(BaseModel):
    id: str
    name: str
    geometry_type: str
    data_url: Optional[str] = None
    style: MapSpecStyle = Field(default_factory=MapSpecStyle)
    visible: bool = True
    z_index: int = 0


class LayerManifest(BaseModel):
    id: str
    version: int = Field(ge=1)
    name: str
    geometry_type: str
    feature_count: int = Field(ge=0)
    extent: Optional[List[float]] = None
    data_hash: Optional[str] = None
    render_mode: RenderMode
    data_url: Optional[str] = None

    @field_validator("extent")
    @classmethod
    def validate_extent(cls, value: Optional[List[float]]) -> Optional[List[float]]:
        if value is None:
            return value
        if len(value) != 4 or value[0] >= value[2] or value[1] >= value[3]:
            raise ValueError("extent must be [minx, miny, maxx, maxy]")
        return value


class MapSpec(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    map_id: Optional[str] = None
    version: int = Field(default=1, ge=1)
    title: Optional[str] = None
    extent: Optional[List[float]] = None
    crs: Optional[str] = None
    display_crs: str = "EPSG:3857"
    background_color: str = "white"
    layers: List[MapLayerSpec] = Field(default_factory=list)
    annotations: List[Dict[str, Any]] = Field(default_factory=list)
    decorations: Dict[str, Any] = Field(default_factory=dict)
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
