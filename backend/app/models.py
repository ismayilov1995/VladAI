"""Request and response models for the HTTP layer."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PackParamsIn(BaseModel):
    """Packing knobs. Everything here feeds the cache key."""

    piece_scale: float = Field(2.0, ge=0.1, le=20.0)
    min_gap_mm: float = Field(1.0, ge=0.0, le=100.0)
    target_coverage: float = Field(0.56, gt=0.0, le=0.95)
    seed: int = Field(20260913, ge=0, le=0x7FFFFFFF)
    grid_res: float = Field(2.0, ge=0.5, le=20.0)
    rotation_steps: int = Field(24, ge=0, le=360)
    max_passes: int = Field(8, ge=1, le=24)
    edge_clearance_mm: float = Field(0.0, ge=0.0, le=100.0)
    bands: int = Field(1, ge=1, le=26)
    band_angle_deg: float = Field(0.0)
    band_jitter_mm: float = Field(0.0, ge=0.0, le=500.0)


class PackRequest(BaseModel):
    """A pack request.

    The panel arrives either as a `file_id` from a prior upload or inline as
    `svg`. The two-step form is what the UI uses: the panel is uploaded once
    and then re-packed on every parameter change without resending the file.
    """

    file_id: str | None = None
    svg: str | None = None
    library: str = "marble"
    calib_mm: float = Field(100.0, gt=0.0)
    units_per_mm: float | None = Field(None, gt=0.0)
    shape_ids: list[str] | None = None
    params: PackParamsIn = Field(default_factory=PackParamsIn)


class ShapeInfo(BaseModel):
    id: str
    tag: str
    area_units: float
    bbox: list[float]
    # False for a stroked outline with no fill, which is how garment panels
    # usually arrive; such a document is packed from its largest outline.
    filled: bool = True
    # What the server would use if the client sends no shape_ids.
    auto_selected: bool = False


class UploadResponse(BaseModel):
    file_id: str
    filename: str
    width_units: float
    height_units: float
    view_box: list[float] | None = None
    calib_width_units: float | None = None
    # True when the document carries no id="calib" element, in which case the
    # client must supply units/mm. The scale is never guessed.
    needs_scale: bool = False
    shapes: list[ShapeInfo] = []


class PackStats(BaseModel):
    count: int
    coverage: float
    covered_mm2: float = 0.0
    region_mm2: float = 0.0
    grid_res: float | None = None
    note: str | None = None


class PlacementOut(BaseModel):
    piece: str
    x: float
    y: float
    angle: float
    cls: str


class PanelOut(BaseModel):
    id: str
    fill_rule: str
    bbox: list[float]
    rings: list[list[float]]


class PackResponse(BaseModel):
    units_per_mm: float
    panels: list[PanelOut]
    placements: list[PlacementOut]
    stats: PackStats
    cached: bool = False
    elapsed_ms: int = 0


class PieceOut(BaseModel):
    id: str
    rings: list[list[float]]
    area_mm2: float
    width_mm: float
    height_mm: float
    attach: list[list[float]] = []


class LibrarySummary(BaseModel):
    id: str
    name: str
    unit: str
    description: str = ""
    provenance: str = ""
    rapport_coverage: float
    piece_count: int
    size_range_mm: list[float]


class LibraryDetail(LibrarySummary):
    pieces: list[PieceOut]
