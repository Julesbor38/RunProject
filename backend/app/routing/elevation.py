"""Elevation from Terrarium DEM tiles (AWS open data, SRTM + national sources), cached under data/dem/.

Checked against IGN RGE ALTI around Lyon: within ~3 m, fine for climb estimates.
"""
from __future__ import annotations

import io
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
ZOOM = 13  # ~13 m per pixel at 45° N
TILE_PX = 256


class Dem:
    def __init__(self, cache_dir: Path, zoom: int = ZOOM):
        self.cache_dir = cache_dir
        self.zoom = zoom
        self._tiles: dict[tuple[int, int], np.ndarray] = {}
        self._lock = threading.Lock()

    def elevations(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """Bilinear-interpolated elevation (m) for arrays of coordinates."""
        n = 2**self.zoom
        x = (np.asarray(lons) + 180.0) / 360.0 * n * TILE_PX
        y = (1.0 - np.arcsinh(np.tan(np.radians(np.asarray(lats)))) / math.pi) / 2.0 * n * TILE_PX
        x0, y0 = np.floor(x - 0.5).astype(np.int64), np.floor(y - 0.5).astype(np.int64)
        fx, fy = x - 0.5 - x0, y - 0.5 - y0
        needed: set[tuple[int, int]] = set()
        for px in (x0, x0 + 1):
            for py in (y0, y0 + 1):
                needed |= set(zip((px // TILE_PX).tolist(), (py // TILE_PX).tolist()))
        self._load(needed)
        z00, z10 = self._pixels(x0, y0), self._pixels(x0 + 1, y0)
        z01, z11 = self._pixels(x0, y0 + 1), self._pixels(x0 + 1, y0 + 1)
        return (z00 * (1 - fx) + z10 * fx) * (1 - fy) + (z01 * (1 - fx) + z11 * fx) * fy

    def _pixels(self, px: np.ndarray, py: np.ndarray) -> np.ndarray:
        tx, ty = px // TILE_PX, py // TILE_PX
        out = np.empty(px.shape, dtype=np.float64)
        keys = tx * (1 << 32) + ty
        for key in np.unique(keys):
            mask = keys == key
            tile = self._tiles[(int(key >> 32), int(key & 0xFFFFFFFF))]
            out[mask] = tile[py[mask] % TILE_PX, px[mask] % TILE_PX]
        return out

    def _load(self, tiles: set[tuple[int, int]]) -> None:
        missing = [t for t in tiles if t not in self._tiles]
        if not missing:
            return
        with ThreadPoolExecutor(8) as pool:  # S3 has no rate limit worth worrying about
            for t, arr in zip(missing, pool.map(self._read, missing)):
                with self._lock:
                    self._tiles[t] = arr

    def _read(self, tile: tuple[int, int]) -> np.ndarray:
        x, y = tile
        path = self.cache_dir / str(self.zoom) / f"{x}_{y}.png"
        if path.exists():
            data = path.read_bytes()
        else:
            r = httpx.get(TERRARIUM_URL.format(z=self.zoom, x=x, y=y), timeout=30)
            r.raise_for_status()
            data = r.content
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        rgb = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float64)
        return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


def climb(profile: list[float], hysteresis_m: float = 2.0) -> tuple[float, float]:
    """(ascent, descent) of an elevation profile, ignoring wiggles under `hysteresis_m`."""
    up = down = 0.0
    ref = None
    for z in profile:
        if ref is None:
            ref = z
        elif z - ref >= hysteresis_m:
            up += z - ref
            ref = z
        elif ref - z >= hysteresis_m:
            down += ref - z
            ref = z
    return up, down
