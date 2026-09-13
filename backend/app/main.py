"""FastAPI service: packing API plus the built frontend as static files.

The API returns placements, never SVG. The frontend draws those placements to
a canvas for the preview and assembles the downloadable SVG from the same list,
so one pack serves both and the two can never drift apart.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from mosaic_fill.library import discover_libraries, library_fingerprint
from mosaic_fill.packer import PackParams, pack
from mosaic_fill.svgdoc import CalibrationError, parse_panel, select_shapes, shapes_to_mm

from .cache import UPLOAD_TTL_SECONDS, PackCache, UploadStore
from .models import (
    LibraryDetail, LibrarySummary, PackRequest, PackResponse, UploadResponse,
)

log = logging.getLogger("vlada")

BACKEND_DIR = Path(__file__).resolve().parent.parent
LIBRARY_DIR = Path(os.environ.get("VLADA_LIBRARY_DIR", BACKEND_DIR / "libraries"))
STATIC_DIR = Path(os.environ.get("VLADA_STATIC_DIR", BACKEND_DIR / "static"))
UPLOAD_DIR = Path(os.environ["VLADA_UPLOAD_DIR"]) if os.environ.get("VLADA_UPLOAD_DIR") else None

UPLOAD_TTL = int(os.environ.get("VLADA_UPLOAD_TTL_SECONDS", UPLOAD_TTL_SECONDS))

uploads = UploadStore(UPLOAD_DIR, UPLOAD_TTL)
cache = PackCache()
libraries = discover_libraries(LIBRARY_DIR)


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("libraries: %s", ", ".join(sorted(libraries)) or "none")
    log.info("uploads in %s, ttl %ss", uploads.root, UPLOAD_TTL)
    uploads.sweep()
    sweeper = asyncio.create_task(_sweep_uploads())
    try:
        yield
    finally:
        sweeper.cancel()
        try:
            await sweeper
        except asyncio.CancelledError:
            pass
        uploads.dispose()


async def _sweep_uploads() -> None:
    """Drop expired uploads hourly; there is no database to tidy, only files."""
    while True:
        try:
            await asyncio.sleep(3600)
            removed = uploads.sweep()
            if removed:
                log.info("swept %d expired upload(s)", removed)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - a sweep failure must not kill the app
            log.exception("upload sweep failed")


app = FastAPI(title="Vlada AI - embroidery fill", version="0.1.0", lifespan=lifespan)

# Only needed when the Vite dev server runs on a different origin; in the
# single-image deployment the frontend is served from this same origin.
_dev_origins = os.environ.get("VLADA_DEV_ORIGINS", "")
if _dev_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _dev_origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "libraries": sorted(libraries),
        "cache_entries": len(cache),
    }


@app.get("/api/libraries", response_model=list[LibrarySummary])
def list_libraries() -> list[dict]:
    return [libraries[key].summary_json() for key in sorted(libraries)]


@app.get("/api/libraries/{library_id}", response_model=LibraryDetail)
def get_library(library_id: str) -> dict:
    library = libraries.get(library_id)
    if library is None:
        raise HTTPException(status_code=404, detail=f"unknown library {library_id!r}")
    return library.to_json()


@app.post("/api/upload", response_model=UploadResponse)
async def upload_panel(file: UploadFile = File(...)) -> dict:
    """Store a panel and report what the document says about its own scale."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"unreadable upload: {exc}") from exc

    try:
        doc = parse_panel(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        file_id = uploads.save(raw, file.filename or "panel.svg")
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    return {
        "file_id": file_id,
        "filename": file.filename or "panel.svg",
        "width_units": doc.width_units,
        "height_units": doc.height_units,
        "view_box": list(doc.view_box) if doc.view_box else None,
        "calib_width_units": doc.calib_width_units,
        "needs_scale": doc.calib_width_units is None,
        "shapes": doc.candidates,
    }


@app.post("/api/pack", response_model=PackResponse)
def pack_panel(request: PackRequest) -> dict:
    """Pack a panel and return placements.

    Deliberately returns no SVG: the client draws these placements to a canvas
    and builds the download from the same list.
    """
    if request.file_id:
        try:
            svg_text, _ = uploads.load(request.file_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail="upload not found or expired; please re-upload the panel",
            ) from None
    elif request.svg:
        svg_text = request.svg
    else:
        raise HTTPException(status_code=400, detail="provide either file_id or svg")

    library = libraries.get(request.library)
    if library is None:
        raise HTTPException(status_code=404, detail=f"unknown library {request.library!r}")

    try:
        doc = parse_panel(svg_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if request.units_per_mm is not None:
        units_per_mm = request.units_per_mm
    else:
        try:
            units_per_mm = doc.units_per_mm(request.calib_mm)
        except CalibrationError:
            # The scale is never guessed: say so and let the client ask.
            return JSONResponse(
                status_code=422,
                content={
                    "needs_scale": True,
                    "detail": (
                        "this document has no element with id='calib'; "
                        "supply units_per_mm directly"
                    ),
                },
            )

    payload = request.params.model_dump()
    payload["units_per_mm"] = round(units_per_mm, 9)
    payload["shape_ids"] = sorted(request.shape_ids) if request.shape_ids else None
    key = PackCache.key(svg_text, library.id, library_fingerprint(library), payload)

    hit = cache.get(key)
    if hit is not None:
        return {**hit, "cached": True}

    shapes = shapes_to_mm(select_shapes(doc, request.shape_ids), units_per_mm)
    params = PackParams(**request.params.model_dump())

    started = time.perf_counter()
    try:
        result = pack(shapes, library, params, units_per_mm)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    body = {**result.to_json(), "cached": False, "elapsed_ms": elapsed_ms}
    cache.put(key, body)
    return body


# ---------------------------------------------------------------------------
# Static frontend. Mounted last so it never shadows an /api route.
# ---------------------------------------------------------------------------

if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str, request: Request) -> FileResponse:
        """Serve the built SPA, falling back to index.html for client routes."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = (STATIC_DIR / full_path).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            raise HTTPException(status_code=404, detail="not found") from None
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="frontend not built")
else:
    @app.get("/", include_in_schema=False)
    def no_frontend() -> dict:
        return {
            "status": "api only",
            "detail": (
                "frontend build not found; run the Vite build or use the "
                "Docker image, which bundles it"
            ),
            "docs": "/docs",
        }
