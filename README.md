# Vlada AI — embroidery fill

Fills garment panel SVGs with embroidery piece patterns. Upload a panel, pick a
library, set the density, watch the preview, download the filled SVG. The
uploaded file is never modified.

The container listens on **port 8000**.

---

## How it fits together

```
backend/mosaic_fill/   the packing engine — no FastAPI imports, runnable on its own
backend/app/           FastAPI: /api/pack, /api/upload, /api/libraries, static frontend
backend/libraries/     one folder per library, each with an index.json
frontend/              React + Vite + TypeScript (strict) + Tailwind
samples/Velvet.svg     reference panel
tools/                 generators for the stand-in library and panel
```

`POST /api/pack` returns **placement JSON, never SVG**:

```json
{
  "units_per_mm": 3.779528,
  "panels":     [{ "id": "panel", "bbox": [...], "rings": [[x, y, ...]] }],
  "placements": [{ "piece": "mp07", "x": 412.5, "y": 118.2, "angle": 75, "cls": "A" }],
  "stats":      { "count": 4924, "coverage": 0.5267, "region_mm2": 2476863.75 }
}
```

The frontend draws those placements to a canvas for the preview **and** builds
the downloadable SVG from the same list. One computation, two uses — the
preview and the download cannot drift apart.

Packs are cached server-side on a hash of (file bytes, library geometry,
parameters), so returning to a combination you have already tried is instant.
The response carries `"cached": true` when it was served from that cache.

---

## Build and run

### Docker (this is the deploy path)

```sh
docker compose build
docker compose up -d
```

Or without compose:

```sh
docker build -t vlada-ai:latest .
docker run -d --name vlada-ai -p 127.0.0.1:8000:8000 vlada-ai:latest
```

One image: the Node stage builds the frontend, the Python 3.12 stage serves the
API and those built files. Check it with:

```sh
curl http://127.0.0.1:8000/api/health
```

`docker-compose.yml` binds to `127.0.0.1:8000` on the assumption that nginx
terminates TLS in front of it. To reach the container directly while setting
up, change the port mapping to `"8000:8000"`.

### Behind nginx

```nginx
server {
    server_name  fill.example.com;

    client_max_body_size 32m;          # panel SVGs can be large

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # A first pack of a large panel takes several seconds.
        proxy_read_timeout 120s;
    }
}
```

### One command

```sh
./run.sh          # macOS, Linux
run.cmd           # Windows
```

Builds the frontend, sets up Python, and serves everything on
<http://localhost:8000>. Safe to re-run — it skips what is already done;
`./run.sh --clean` redoes it from scratch, and `PORT=9000 ./run.sh` moves it.

Needs Node 20+ and Python 3.11+; the script checks both and says where to get
them if they are missing.

### Local development

Two processes, because Vite serves the frontend with hot reload and proxies
`/api` to the backend on 8000.

```sh
# terminal 1 — API on :8000
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --reload --port 8000

# terminal 2 — UI on :5173
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173>.

To run the single-image layout locally without Docker, build the frontend into
the backend's static directory and serve only the API process:

```sh
cd frontend && npm run build     # writes ../backend/static
cd ../backend && uvicorn app.main:app --port 8000
```

Then open <http://localhost:8000>.

---

## Tests

```sh
cd backend
pip install -r requirements-dev.txt   # pytest and httpx, once
python -m pytest
```

The gate is `tests/test_pack_velvet.py`: it packs `samples/Velvet.svg` at 2×
piece scale and a 1.0 mm gap, then asserts

* **zero overlapping cells** in the occupancy grid, rebuilt from the placement
  list alone rather than from the packer's own bookkeeping, and
* **coverage between 52% and 57%**, the band around MARBLE's 56% rapport.

Current result on the reference panel: **4,924 pieces at 52.7% coverage, zero
overlaps**, against a reference count of 4,906.

The three piece counts quoted in the specification all reproduce within 5% on
the reconstructed panel and library, which is the main evidence that the
reconstruction is faithful:

| Piece scale | Specified | Produced | Coverage | Overlaps |
| --- | --- | --- | --- | --- |
| 1.5× | 8,101 | 8,506 | 52.0% | 0 |
| 2× | 4,906 | 4,924 | 52.7% | 0 |
| 3× | 2,324 | 2,288 | 53.0% | 0 |

(1.5× and 3× use a 1.0 mm and 1.5 mm gap respectively; 2× is the gated case.)

Frontend type checking:

```sh
cd frontend && npm run typecheck
```

### Container check

The runtime stage has been built and run: it comes up as the non-root `vlada`
user on Python 3.12.14, reports `healthy` to Docker's own healthcheck, serves
the built frontend, and packs `Velvet.svg` to **4,924 pieces at 52.67%** — the
same numbers the host produces, so the result is reproducible across Python
3.11 and 3.12. `docker compose config` validates, and the compose `tmpfs` mount
accepts uploads from uid 10001.

The frontend stage was not built here: this sandbox intercepts TLS with its own
CA, so `npm ci` and `pip install` cannot verify certificates inside a build
container. On an ordinary host both reach their registries normally. The pinned
requirements were separately confirmed to resolve for CPython 3.12 on
`manylinux_2_28_x86_64` — note that `numpy==2.4.6` needs that baseline (glibc
2.28+), which `python:3.12-slim` satisfies.

---

## Using it

### 1. Scale reference

The panel SVG must contain one element with `id="calib"` — any shape. Enter its
real-world width in mm (default 100); the app divides the element's bounding-box
width in user units by that to get units/mm.

If there is no `#calib` element the app says so and asks for units/mm directly.
**It never guesses the scale.**

**From Illustrator**: draw a rectangle exactly 100 mm wide, name it `calib` in
the Layers panel, and export with **Object IDs: Layer Names** — that setting is
what turns the name into an `id`. Naming the *layer* rather than the object
works too: the id lands on the exported `<g>`, and the group is measured across
its contents and kept out of the fill. Illustrator's `calib_1_` mangling of a
duplicate name is also accepted. Only the geometry is measured, so stroke
weight does not affect the reading, and when a document holds more than one
mark the first wins.

**From Inkscape**: set the object's ID in *Object Properties* (Ctrl+Shift+O) and
save as Plain or Inkscape SVG.

Illustrator exports in points, not pixels, so a 50 mm square comes out 141.7
units wide. That is fine — the number you type is the real-world width, and
units/mm follows from it.

### Which shape gets filled

A painted shape says plainly that it is a region, so when the document has any,
those are filled. When nothing is painted — a drawing of stroked outlines,
which is how garment panels usually arrive — the largest closed outline is
taken instead, because a panel is bigger than the seam lines and notches drawn
on it.

That last part is a guess, so the app lists every closed outline under **Region
to fill** with its area and lets you override it. Zero-area strokes such as
grain lines are not offered; hidden shapes and the calibration mark are never
candidates.

### 2. Library

MARBLE mosaic, 22 pieces, 9.4–24.9 mm at 1× — so 19–50 mm at the default 2×
scale. Rapport density 56%.

### 3. Density

Three independent knobs:

| Knob | Effect |
| --- | --- |
| **Piece scale** | Multiplier on library piece size. |
| **Minimum gap** | Millimetres of clear space between pieces. |
| **Target coverage** | Packing stops once reached. 56% is MARBLE's own rapport density. |

Smaller pieces and a smaller gap mean higher coverage and far more elements.
The preview warns above 5,000 pieces.

There is also an **edge clearance** knob, which holds pieces back from the panel
outline for seam allowance.

### 4. Colour blocking

Bands across the panel at a chosen angle, with an optional bleed that softens
the boundary so colours interleave rather than stopping dead. Each placement
carries a colour class (`A`, `B`, …) which the export maps to a thread colour.

### 5. Attachment points

A toggle under **Markers** shows a dot at each point where a piece is stitched
down — one on a small tessera, two or three spread along the long axis of a
larger one that would otherwise swivel.

It is a render option, not a packing parameter: flipping it redraws the canvas
and changes the export, but **does not re-pack** and is not part of the cache
key. The layout stays exactly as it was.

In the export, dots live inside each piece's `<defs>` group, so they are
translated and rotated by the same `<use>` transform as the outline and are
defined once no matter how many placements reference them. They are filled with
`currentColor`, which each `<use>` sets through a `color` attribute, so a dot
takes the thread colour of the piece it belongs to.

The dot marks a needle penetration point, so it stays a fixed physical size
(0.45 mm radius): its position scales with the piece, its radius does not.

### 6. Download

The filled SVG is your original document with one group appended:

```xml
<defs>
  <g id="mp07"><path fill="none" d="M…Z"/></g>
</defs>
<g id="mosaic-fill" fill="none" stroke-width="0.945" …>
  <use href="#mp07" transform="translate(1559.1 446.7) rotate(75)" stroke="#c9a227"/>
</g>
```

Each piece is defined once in `<defs>`, centred on its own centroid, so
`rotate()` spins it in place. Colour is a `stroke` **attribute** on each
`<use>`, not a stylesheet rule — `<use>` clones its referent into a shadow tree
that outside selectors do not reach, so a `#mosaic .A path {}` rule silently
does nothing. Inherited presentation attributes on the `<use>` itself do cross
into the clone, which is why the attribute works.

Deleting the one appended group restores the original file exactly.

---

## Adding a library

Drop a folder into `backend/libraries/` with an `index.json`. No code changes
anywhere.

```
backend/libraries/yourlibrary/
  index.json
  pieces.json                  (optional)
  pieces.svg                   (optional)
```

```json
{
  "id": "yourlibrary",
  "name": "Your library",
  "unit": "mm",
  "rapport_coverage": 0.56,
  "pieces_file": "pieces.json",
  "reference_svg": "pieces.svg",
  "description": "…"
}
```

Geometry comes from `pieces.json` when present, and otherwise from
`reference_svg`, so a library can start life as an SVG alone. Pieces are
re-centred on their centroids at load time.

`pieces.json` holds flat coordinate rings in the declared unit:

```json
{ "unit": "mm",
  "pieces": [
    { "id": "mp01",
      "rings":  [[0, 0, 10, 0, 10, 8, 0, 8]],
      "attach": [[5, 4]] }
  ] }
```

`attach` is optional: it lists the points where the piece is stitched down, in
the same coordinates as the rings. A library that omits it simply has nothing
for the attachment-point toggle to draw, and the toggle is disabled.

A folder that fails to load is skipped rather than taking the service down.

### pieces.svg

`pieces.svg` is the library's base geometry as a viewable file. Data and
presentation are kept apart in it:

```xml
<defs>
  <g id="mp07" class="piece">
    <path d="M-6.2,-3.1 …Z"/>                      <!-- outline, mm, centroid-centred -->
    <circle class="attach" cx="-2.1" cy="0" r="0.45"/>   <!-- stitch-down point -->
  </g>
</defs>
<g …>
  <use href="#mp07" transform="translate(41.9 13.9)"/>   <!-- contact sheet only -->
</g>
```

The `<defs>` block is the library. Every piece sits in its own coordinates —
millimetres, centred on its own centroid — which is exactly the frame the
packer and the export use, so nothing has to be un-done on load. The contact
sheet underneath is `<use>` references and carries no geometry; deleting it
loses nothing but the ability to open the file and look at it.

The two class markers are what the loader keys on, and they exist to stop two
specific misreadings: a `class="attach"` dot being taken for a tiny piece, and
a wrapper or layer group being taken for one enormous piece. An SVG with no
markers — a hand-traced sheet, say — falls back to one piece per drawable
element, which is the only sensible reading of a file that says nothing about
its own structure.

Regenerate it from whatever the loader currently reads:

```sh
python tools/extract_pieces_svg.py --library marble
```

---

## Command line

The engine runs without the web layer, exactly as it did before there was an
app:

```sh
cd backend
python -m mosaic_fill.cli ../samples/Velvet.svg \
    --scale 2.0 --gap 1.0 --coverage 0.56 \
    --out filled.svg --json placements.json --check-overlaps
```

`--attach-dots` marks the stitch-down points in the exported SVG, and
`--attach-radius` sets their size in mm.

`--units-per-mm` replaces the `#calib` convention for files that lack one.
`python -m mosaic_fill.cli --help` lists the rest.

---

## How the packing works

The engine packs onto a boolean occupancy grid rather than by polygon-distance
tests.

1. The panel is flattened to polygons and rasterised into an "inside" mask at
   `grid_res` cells per mm.
2. Each library piece, at each rotation, is pre-rasterised twice: a solid stamp,
   and a stamp grown by the minimum gap.
3. One `blocked` grid holds the panel exterior plus every placed piece's
   gap-grown footprint. A candidate fits when its solid stamp misses `blocked`
   entirely — a single masked test that enforces the panel edge and the spacing
   rule at once, because "distance ≥ gap" is the same statement as "grow one
   side by gap and check for intersection".
4. Passes sweep jittered lattices from coarse to fine, biasing towards large
   pieces first and smaller ones into the gaps, until the coverage target is hit
   or the panel saturates.

Everything is seeded: the same file, library and parameters always produce the
same layout. Change the **seed** in Advanced for a different one at the same
density.

Pack time scales with panel area. The reference panel is 2.48 m² and takes
about five seconds for a first pack; repeats are served from cache.

---

## Constraints this was built under

No database, no auth, no accounts. Uploaded panels live in a temp directory with
a TTL (`VLADA_UPLOAD_TTL_SECONDS`, default 6 hours) and are swept hourly. No
paid API calls anywhere.

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `VLADA_UPLOAD_DIR` | a fresh temp dir | Where uploaded panels are stored. |
| `VLADA_UPLOAD_TTL_SECONDS` | `21600` | How long an upload survives. |
| `VLADA_LIBRARY_DIR` | `backend/libraries` | Where libraries are discovered. |
| `VLADA_STATIC_DIR` | `backend/static` | Built frontend to serve. |
| `VLADA_DEV_ORIGINS` | unset | Comma-separated CORS origins, dev only. |

---

## Stand-in inputs

The original packing script, `Velvet.svg`, and the traced MARBLE library were
not available when this was built. Two generators produce stand-ins so the
pipeline is exercisable end to end:

* `tools/make_marble_library.py` — 22 pieces matching MARBLE's documented size
  envelope (9.4–24.9 mm at 1×, giving 14–37 mm at 1.5×, 19–50 mm at 2× and
  28–75 mm at 3×) and its 56% rapport density. It also derives 39 attachment
  points across the set, one to three per piece by size, each verified to lie
  inside its own outline. The outlines are generated, not traced, and so are
  the stitch points — the real library's own attachment data should replace
  them.
* `tools/extract_pieces_svg.py` — writes `pieces.svg` from whatever geometry
  the loader currently reads. It is not a stand-in: point it at the real
  library once that lands and it will extract that instead.
* `tools/make_velvet_panel.py` — a gown front panel with a shaped hem, a
  neckline cut out as a hole, and a 100 mm `#calib` square, in CSS pixels
  (3.779528 units/mm).

Both write **data files**. Replacing them with the real library and panel is a
file swap, not a code change:

```sh
# drop the real files in and delete nothing else
cp /path/to/pieces.json                backend/libraries/marble/
cp /path/to/Velvet.svg                 samples/
python tools/extract_pieces_svg.py --library marble   # refresh pieces.svg
cd backend && python -m pytest
```

The packing engine is a reimplementation from the written specification, not a
port of the original script, because the script was not available. It matches
the specified behaviour — occupancy-grid packing, `#calib` calibration, the
placement contract, deterministic output — and lands within 0.4% of the stated
4,906-piece benchmark, but it is not the same code.
