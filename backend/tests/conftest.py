from __future__ import annotations

from pathlib import Path

import pytest

from mosaic_fill.library import Library, discover_libraries
from mosaic_fill.svgdoc import PanelDocument, parse_panel

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
VELVET = REPO_ROOT / "samples" / "Velvet.svg"


@pytest.fixture(scope="session")
def marble() -> Library:
    libraries = discover_libraries(BACKEND_ROOT / "libraries")
    assert "marble" in libraries, "the MARBLE library should be discoverable"
    return libraries["marble"]


@pytest.fixture(scope="session")
def velvet_doc() -> PanelDocument:
    assert VELVET.is_file(), f"missing reference panel at {VELVET}"
    return parse_panel(VELVET.read_text(encoding="utf-8"))
