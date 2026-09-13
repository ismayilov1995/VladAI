"""HTTP contract tests.

The contract the frontend is written against: /api/pack returns placements and
never SVG, repeats are served from cache, and a document with no calibration
element is reported rather than guessed at.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, cache

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VELVET = REPO_ROOT / "samples" / "Velvet.svg"

NO_CALIB_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<rect id="panel" x="10" y="10" width="80" height="80" fill="#333"/></svg>'
)

SMALL_PANEL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">'
    '<rect id="calib" x="0" y="0" width="100" height="4" fill="none"/>'
    '<rect id="panel" x="20" y="20" width="340" height="340" fill="#333"/></svg>'
)

# Fast settings: these tests check the contract, not packing quality.
QUICK = {"piece_scale": 2.0, "min_gap_mm": 1.0, "max_passes": 2, "target_coverage": 0.3}


@pytest.fixture()
def client():
    cache.clear()
    with TestClient(app) as test_client:
        yield test_client


def upload(client, svg: str, name: str = "panel.svg") -> dict:
    response = client.post(
        "/api/upload",
        files={"file": (name, io.BytesIO(svg.encode()), "image/svg+xml")},
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestHealthAndLibraries:
    def test_health(self, client):
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert "marble" in body["libraries"]

    def test_library_list(self, client):
        entries = client.get("/api/libraries").json()
        assert any(e["id"] == "marble" for e in entries)
        marble = next(e for e in entries if e["id"] == "marble")
        assert marble["piece_count"] == 22
        assert marble["rapport_coverage"] == pytest.approx(0.56)

    def test_library_detail_carries_geometry(self, client):
        body = client.get("/api/libraries/marble").json()
        assert len(body["pieces"]) == 22
        for piece in body["pieces"]:
            assert piece["rings"] and len(piece["rings"][0]) >= 6
            assert piece["area_mm2"] > 0

    def test_library_sizes_match_the_documented_envelope(self, client):
        body = client.get("/api/libraries/marble").json()
        low, high = body["size_range_mm"]
        # 2x is documented as 19-50 mm, so 1x must be about 9.5-25 mm.
        assert low == pytest.approx(9.4, abs=0.3)
        assert high == pytest.approx(24.9, abs=0.3)

    def test_unknown_library_is_404(self, client):
        assert client.get("/api/libraries/nope").status_code == 404


class TestUpload:
    def test_upload_reports_calibration(self, client):
        body = upload(client, SMALL_PANEL_SVG)
        assert body["needs_scale"] is False
        assert body["calib_width_units"] == pytest.approx(100.0)
        assert body["file_id"]

    def test_upload_without_calib_asks_for_the_scale(self, client):
        body = upload(client, NO_CALIB_SVG)
        assert body["needs_scale"] is True
        assert body["calib_width_units"] is None

    def test_upload_lists_fillable_shapes(self, client):
        body = upload(client, SMALL_PANEL_SVG)
        assert [s["id"] for s in body["shapes"]] == ["panel"]

    def test_non_svg_upload_is_rejected(self, client):
        response = client.post(
            "/api/upload",
            files={"file": ("x.svg", io.BytesIO(b"<html>no</html>"), "image/svg+xml")},
        )
        assert response.status_code == 400


class TestPack:
    def test_pack_returns_placements_and_no_svg(self, client):
        file_id = upload(client, SMALL_PANEL_SVG)["file_id"]
        body = client.post("/api/pack", json={
            "file_id": file_id, "library": "marble", "calib_mm": 100.0, "params": QUICK,
        }).json()

        assert set(body) >= {"units_per_mm", "panels", "placements", "stats"}
        assert "svg" not in body
        assert body["units_per_mm"] == pytest.approx(1.0)
        assert body["stats"]["count"] == len(body["placements"])
        assert body["stats"]["count"] > 0

    def test_placement_shape_matches_the_contract(self, client):
        file_id = upload(client, SMALL_PANEL_SVG)["file_id"]
        body = client.post("/api/pack", json={
            "file_id": file_id, "params": QUICK,
        }).json()
        placement = body["placements"][0]
        assert set(placement) == {"piece", "x", "y", "angle", "cls"}
        assert isinstance(placement["piece"], str)
        assert placement["cls"] == "A"

    def test_panels_carry_outlines_for_the_preview(self, client):
        file_id = upload(client, SMALL_PANEL_SVG)["file_id"]
        body = client.post("/api/pack", json={"file_id": file_id, "params": QUICK}).json()
        assert body["panels"]
        panel = body["panels"][0]
        assert panel["id"] == "panel"
        assert len(panel["rings"][0]) >= 8
        # calib is 100 units wide for 100 mm, so units/mm is 1 and the
        # 340-unit panel at x=20 spans 20-360 mm.
        assert panel["bbox"] == pytest.approx([20.0, 20.0, 360.0, 360.0], abs=0.01)

    def test_repeating_a_request_is_served_from_cache(self, client):
        file_id = upload(client, SMALL_PANEL_SVG)["file_id"]
        payload = {"file_id": file_id, "params": QUICK}
        first = client.post("/api/pack", json=payload).json()
        second = client.post("/api/pack", json=payload).json()
        assert first["cached"] is False
        assert second["cached"] is True
        assert first["placements"] == second["placements"]

    def test_changing_a_parameter_misses_the_cache(self, client):
        file_id = upload(client, SMALL_PANEL_SVG)["file_id"]
        client.post("/api/pack", json={"file_id": file_id, "params": QUICK})
        changed = dict(QUICK, min_gap_mm=4.0)
        body = client.post("/api/pack", json={"file_id": file_id, "params": changed}).json()
        assert body["cached"] is False

    def test_missing_calib_is_reported_not_guessed(self, client):
        file_id = upload(client, NO_CALIB_SVG)["file_id"]
        response = client.post("/api/pack", json={"file_id": file_id, "params": QUICK})
        assert response.status_code == 422
        assert response.json()["needs_scale"] is True

    def test_supplying_units_per_mm_packs_a_file_without_calib(self, client):
        file_id = upload(client, NO_CALIB_SVG)["file_id"]
        body = client.post("/api/pack", json={
            "file_id": file_id, "units_per_mm": 0.5, "params": QUICK,
        }).json()
        assert body["units_per_mm"] == pytest.approx(0.5)
        assert body["stats"]["count"] > 0

    def test_inline_svg_is_accepted(self, client):
        body = client.post("/api/pack", json={
            "svg": SMALL_PANEL_SVG, "params": QUICK,
        }).json()
        assert body["stats"]["count"] > 0

    def test_colour_bands_assign_distinct_classes(self, client):
        file_id = upload(client, SMALL_PANEL_SVG)["file_id"]
        body = client.post("/api/pack", json={
            "file_id": file_id, "params": dict(QUICK, bands=3),
        }).json()
        assert {p["cls"] for p in body["placements"]} == {"A", "B", "C"}

    def test_unknown_file_id_is_404(self, client):
        response = client.post("/api/pack", json={"file_id": "deadbeef", "params": QUICK})
        assert response.status_code == 404

    def test_a_request_with_neither_file_nor_svg_is_400(self, client):
        assert client.post("/api/pack", json={"params": QUICK}).status_code == 400

    def test_out_of_range_parameters_are_rejected(self, client):
        file_id = upload(client, SMALL_PANEL_SVG)["file_id"]
        response = client.post("/api/pack", json={
            "file_id": file_id, "params": dict(QUICK, piece_scale=-5.0),
        })
        assert response.status_code == 422


class TestVelvetThroughTheApi:
    @pytest.mark.skipif(not VELVET.is_file(), reason="reference panel missing")
    def test_velvet_packs_through_the_api(self, client):
        file_id = upload(client, VELVET.read_text(), "Velvet.svg")["file_id"]
        body = client.post("/api/pack", json={
            "file_id": file_id, "calib_mm": 100.0,
            "params": {"piece_scale": 2.0, "min_gap_mm": 1.0, "target_coverage": 0.56},
        }).json()
        assert body["units_per_mm"] == pytest.approx(3.779528, rel=1e-6)
        assert 0.52 <= body["stats"]["coverage"] <= 0.57
