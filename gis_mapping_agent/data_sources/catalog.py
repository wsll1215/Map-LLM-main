"""Fast local dataset catalog backed by filesystem metadata."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from ..utils.config import Config
from ..utils.logger import get_logger


_ALIAS_GROUPS = {
    "Beijing": ["北京", "北京市", "beijing"],
    "Guangdong": ["广东", "广东省", "guangdong"],
    "Henan": ["河南", "河南省", "henan"],
    "Wuhan": ["武汉", "武汉市", "wuhan"],
    "Xian": ["西安", "西安市", "xian", "xi'an"],
    "Highway": ["高速", "高速公路", "highway"],
    "Railway": ["铁路", "railway"],
    "River": ["河流", "river"],
    "Scenic Spot": ["景点", "风景区", "scenic spot"],
    "Historic Site": ["历史遗址", "historic site"],
    "Racecourse": ["赛马场", "racecourse"],
    "Skating Rink": ["滑冰场", "skating rink"],
}


@dataclass(frozen=True)
class DatasetDescriptor:
    dataset_id: str
    name: str
    aliases: List[str]
    source_type: str
    local_path: str
    geometry_type: str
    crs: str
    bbox: List[float]
    feature_count: Optional[int]
    metadata: dict
    role: Optional[str] = None


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())


def _dataset_id(relative_path: str) -> str:
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:12]
    return f"local-{digest}"


class LocalDatasetCatalog:
    """Read local GIS metadata without loading every feature into memory."""

    def __init__(self, root: Optional[Path] = None):
        self.root = (root or Config.DATA_DIRECTORY_BASE).resolve()
        self.logger = get_logger("LocalDatasetCatalog")

    def paths(self) -> Iterable[Path]:
        if not self.root.exists():
            return []
        return sorted(self.root.rglob("*.shp"))

    def describe(self, path: Path) -> DatasetDescriptor:
        path = path.resolve()
        relative = path.relative_to(self.root).as_posix()
        info = self._read_info(path)
        name = path.stem
        aliases = list(_ALIAS_GROUPS.get(name, []))
        if name not in aliases:
            aliases.append(name)
        bbox = [float(value) for value in info.get("total_bounds", ())]
        return DatasetDescriptor(
            dataset_id=_dataset_id(relative),
            name=name,
            aliases=sorted(set(aliases)),
            source_type="local",
            local_path=relative,
            geometry_type=str(info.get("geometry_type") or ""),
            crs=str(info.get("crs") or ""),
            bbox=bbox,
            feature_count=(int(info["features"]) if info.get("features") is not None else None),
            metadata={
                "driver": info.get("driver", ""),
                "fields": [str(field) for field in info.get("fields", [])],
            },
            role="boundary"
            if "polygon" in str(info.get("geometry_type") or "").lower()
            else None,
        )

    def scan(self) -> List[DatasetDescriptor]:
        descriptors = []
        for path in self.paths():
            try:
                descriptors.append(self.describe(path))
            except Exception as exc:
                self.logger.warning(f"跳过无法读取的数据集 {path}: {exc}")
        return descriptors

    def search(self, query: str, *, limit: int = 20) -> List[DatasetDescriptor]:
        needle = _normalize(query)
        if not needle:
            return []
        ranked = []
        for descriptor in self.scan():
            values = [descriptor.name, descriptor.local_path, *descriptor.aliases]
            normalized = [_normalize(value) for value in values]
            score = 0
            if needle in normalized:
                score = 100
            elif any(needle in value for value in normalized):
                score = 70
            elif any(value in needle for value in normalized if value):
                score = 50
            if score:
                ranked.append((score, descriptor))
        ranked.sort(key=lambda item: (-item[0], item[1].dataset_id))
        return [descriptor for _, descriptor in ranked[:limit]]

    @staticmethod
    def _read_info(path: Path) -> dict:
        try:
            import pyogrio

            return pyogrio.read_info(path)
        except ImportError:
            import geopandas as gpd

            frame = gpd.read_file(path, rows=0)
            return {
                "crs": frame.crs.to_string() if frame.crs else "",
                "fields": list(frame.columns.drop("geometry", errors="ignore")),
                "geometry_type": "",
                "features": None,
                "total_bounds": (),
                "driver": "",
            }


class DjangoDatasetCatalog:
    """Runtime catalog backed by Django's Dataset and DatasetFeature tables."""

    def __init__(self, dataset_model=None):
        self.dataset_model = dataset_model
        self.logger = get_logger("DjangoDatasetCatalog")
        self.last_error = None

    def scan(self) -> List[DatasetDescriptor]:
        self.last_error = None
        try:
            model = self.dataset_model
            if model is None:
                from mapping.models import Dataset

                model = Dataset
            queryset = model.objects.filter(
                status=model.STATUS_AVAILABLE,
                source_type=getattr(model, "SOURCE_LOCAL", "local"),
            )
            descriptors = []
            for dataset in queryset:
                metadata = dict(dataset.metadata or {})
                feature_count = dataset.feature_count
                # DatasetFeature is authoritative whenever the related manager
                # exists. A database failure must fail closed; using the stale
                # Dataset.feature_count would make an unavailable catalog look
                # like a valid local source.
                related_features = getattr(dataset, "features", None)
                if related_features is not None:
                    feature_count = related_features.count()
                if feature_count is None or feature_count <= 0:
                    continue
                descriptors.append(
                    DatasetDescriptor(
                        dataset_id=dataset.dataset_id,
                        name=dataset.name,
                        aliases=list(dataset.aliases or []),
                        source_type=dataset.source_type,
                        local_path=dataset.local_path or "",
                        geometry_type=dataset.geometry_type or "",
                        crs=dataset.crs or "EPSG:4326",
                        bbox=[float(value) for value in (dataset.bbox or [])],
                        feature_count=int(feature_count),
                        metadata=metadata,
                        role=_dataset_role(dataset, metadata),
                    )
                )
            return descriptors
        except Exception as exc:
            self.last_error = {
                "error_code": "local_catalog_unavailable",
                "message": str(exc)[:300],
            }
            self.logger.warning(f"运行时数据目录不可用: {exc}")
            return []


def _dataset_role(dataset, metadata: dict) -> Optional[str]:
    roles = metadata.get("roles") or metadata.get("role")
    if isinstance(roles, str):
        return roles
    if roles:
        return str(next(iter(roles)))
    name = str(getattr(dataset, "name", "")).lower()
    geometry_type = str(getattr(dataset, "geometry_type", "")).lower()
    if any(term in name for term in ("highway", "road", "道路", "公路")):
        return "road"
    if any(term in name for term in ("railway", "铁路", "高铁")):
        return "railway"
    if any(term in name for term in ("river", "河流", "河道")):
        return "river"
    if "polygon" in geometry_type or "multipolygon" in geometry_type:
        return "boundary"
    return None
