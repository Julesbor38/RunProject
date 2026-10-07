"""Adding activities from the web page: a new Strava export (.zip) or single .fit / .gpx / .tcx files.

A Strava export always holds every activity, so it replaces data/raw/strava/ as a whole; single
files go to data/raw/uploads/. Only the files the import reads are extracted from a zip, with
size limits and no path leaving the target folder (zip slip, zip bombs).
"""
from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from .ingest.parsers import SUPPORTED

MAX_UPLOAD = 4 * 2**30  # bytes per uploaded file
MAX_UNZIPPED = 12 * 2**30  # total size of the extracted activity files
CHUNK = 2**20


class InvalidImport(ValueError):
    """A file that cannot be imported, with a message for the user."""


def activity_file(name: str) -> bool:
    name = name.lower()
    return any(name.endswith(ext) or name.endswith(ext + ".gz") for ext in SUPPORTED)


def save_stream(src: BinaryIO, dest: Path, limit: int = MAX_UPLOAD) -> int:
    """Copy an upload to disk in chunks, refusing it past `limit` bytes."""
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as out:
        while chunk := src.read(CHUNK):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise InvalidImport(f"fichier trop gros (plus de {limit // 2**30} Go)")
            out.write(chunk)
    return size


def install_strava_zip(zip_path: Path, raw_dir: Path) -> int:
    """Replace raw_dir/strava with the export's activities.csv + activity files. Returns the file count."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise InvalidImport("ce .zip est illisible") from e
    with zf:
        csvs = [i for i in zf.infolist() if PurePosixPath(i.filename).name == "activities.csv"]
        if not csvs:
            raise InvalidImport("ce n'est pas une archive Strava (activities.csv introuvable)")
        csv = min(csvs, key=lambda i: len(i.filename))  # the export's own, not one nested deeper
        root = PurePosixPath(csv.filename).parent
        wanted = [csv]
        for info in zf.infolist():
            rel = PurePosixPath(info.filename)
            if not info.is_dir() and _under(rel, root / "activities") and activity_file(rel.name):
                wanted.append(info)
        if sum(i.file_size for i in wanted) > MAX_UNZIPPED:
            raise InvalidImport("archive trop volumineuse une fois décompressée")
        new = raw_dir / "strava.new"
        shutil.rmtree(new, ignore_errors=True)
        new.mkdir(parents=True)
        try:
            _extract(zf, wanted, root, new)
        except BaseException:
            shutil.rmtree(new, ignore_errors=True)  # the current activities stay as they were
            raise
    old = raw_dir / "strava"
    if old.exists():
        old.rename(raw_dir / "strava.old")
    new.rename(old)
    shutil.rmtree(raw_dir / "strava.old", ignore_errors=True)
    return len(wanted) - 1


def install_file(path: Path, original_name: str, raw_dir: Path) -> Path:
    """Move one uploaded activity file into raw_dir/uploads under a safe name."""
    if not activity_file(original_name):
        raise InvalidImport(f"{original_name} : format non pris en charge (.zip Strava, .fit, .gpx, .tcx)")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", PurePosixPath(original_name.replace("\\", "/")).name).lstrip(".") or "activite"
    dest = raw_dir / "uploads" / safe
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(path, dest)
    return dest


def _extract(zf: zipfile.ZipFile, members: list[zipfile.ZipInfo], root: PurePosixPath, dest: Path) -> None:
    for info in members:
        rel = PurePosixPath(info.filename).relative_to(root)
        target = (dest / rel).resolve()
        if ".." in rel.parts or not target.is_relative_to(dest.resolve()):
            raise InvalidImport(f"chemin refusé dans l'archive : {info.filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out, CHUNK)


def _under(path: PurePosixPath, folder: PurePosixPath) -> bool:
    return path.parts[: len(folder.parts)] == folder.parts and len(path.parts) > len(folder.parts)
