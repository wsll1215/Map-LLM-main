import geopandas as gpd
import numpy as np
from pathlib import Path
from typing import List, Optional
from .config import Config

def calculate_extent_from_files(
    data_files: List[str],
    data_dir: str,
    margin_ratio: float = Config.HYPERPARAMETERS.AUTO_EXTENT_MARGIN_RATIO,
    verbose: bool = True
) -> Optional[List[float]]:
    """
    Calculates the combined bounding box for a list of shapefiles.
    """
    all_bounds = []
    data_dir_path = Path(data_dir)

    for data_file in data_files:
        file_path = data_dir_path / data_file
        if not file_path.exists():
            if verbose:
                print(f"⚠️ File not found: {file_path}")
            continue
        
        try:
            gdf = gpd.read_file(file_path)
            if not gdf.empty:
                all_bounds.append(gdf.total_bounds)
        except Exception as e:
            if verbose:
                print(f"❌ Failed to read {data_file}: {e}")

    if not all_bounds:
        return None

    all_bounds = np.array(all_bounds)
    min_lon = np.min(all_bounds[:, 0])
    min_lat = np.min(all_bounds[:, 1])
    max_lon = np.max(all_bounds[:, 2])
    max_lat = np.max(all_bounds[:, 3])

    lon_margin = (max_lon - min_lon) * margin_ratio
    lat_margin = (max_lat - min_lat) * margin_ratio

    return [
        min_lon - lon_margin,
        min_lat - lat_margin,
        max_lon + lon_margin,
        max_lat + lat_margin
    ]

def format_extent_for_request(extent: List[float]) -> str:
    """
    Formats the extent list into a string for an agent request.
    """
    return f"[{extent[0]:.4f}, {extent[1]:.4f}, {extent[2]:.4f}, {extent[3]:.4f}]"
