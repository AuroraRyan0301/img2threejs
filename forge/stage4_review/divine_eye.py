#!/usr/bin/env python3
"""The Divine Eye — deterministic multi-signal render↔reference evaluator.

Plan 1.3 Phase 3 core (§3.1 ensemble, §3.3 combination + self-uncertainty). This is
the single authority the correction loop asks "how close is this render to the
reference, and what's wrong?". It is DETERMINISTIC and ZERO-TOKEN: pure Python +
pixel math, reusing the Tier-1 primitives (diagnose_render) + the shared pHash. No
LLM/VLM call lives here — the VLM layer (§3.4) is a separate, gated, subordinate step.

Signals (each → normalized [0,1] agreement + a defect tag when it fails):
  HARD gates (a fail cannot be averaged away):
    - silhouette IoU        (< 0.85 ⇒ reject)
    - scale delta           (> 0.08 ⇒ reject)
  SOFT signals (ensemble-weighted):
    - proportion / aspect ratio
    - bilateral symmetry
    - pHash structural similarity
    - global SSIM (luma)
    - edge-map overlap (Sobel linework)
    - blowout parity (QA: blown-highlight fraction vs reference)
    - flat-region ratio (QA: material reacting to light, not a dead flat fill)
    - tonal/contrast parity (QA: luma-histogram match)

Deferred to later Phase-3 increments (documented, not silently missing):
  Directional Chamfer Distance, OSIM objectness (numpy+weights, R-DEP/R-OSIM-EFFORT),
  multi-angle browser capture (diagnose_render_multi_angle.py), CIE-Lab per-region ΔE
  wiring (available via extract_part_color_recipe; folded in with per-feature §3.8).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diagnose_render import (  # noqa: E402
    MASK_GRID_SIZE,
    bbox_of,
    bilateral_symmetry_error,
    largest_component,
    load_mask,
    mask_is_inverted,
    proportion_delta,
    silhouette_iou,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stage1_intake"))
from extract_pbr_evidence import build_foreground_mask, load_image  # noqa: E402

from objectness import objectness_similarity  # noqa: E402  (stdlib OSIM-lite, same dir)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_shared"))
from color_metrics import ciede2000, srgb_to_lab  # noqa: E402
from image_hash import normalized_similarity, phash_from_image  # noqa: E402

# Hard-gate thresholds (shared with diagnose_render; calibratable in Phase 5).
IOU_HARD_MIN = 0.85
SCALE_HARD_MAX = 0.08
# Ensemble: fidelity target + disagreement (self-uncertainty) spread.
FIDELITY_TARGET = 0.85
DISAGREEMENT_SPREAD = 0.35  # if soft-signal spread exceeds this ⇒ low-confidence → probe
ASPECT_SOFT_MAX = 0.05      # aspect-ratio delta allowed for a reconstruction-mode soft pass.
RECON_OBJ_MIN = 0.48        # objectness ≥ this rescues an IoU-only hard reject → probe (recon mode).
#                            Separates same-object-different-framing (real pairs ~0.53–0.58) from a
#                            genuinely different shape (~0.43). Rescue only ever downgrades reject→probe.
# RESOLUTION CEILING, and it is a hard limit on what this module can ever report.
# Every signal below -- SSIM, tonal, blowout, flat, edge overlap -- is computed on these grids, so a
# feature a few pixels wide in a 1920px reference is not scored badly, it is ABSENT before any
# comparison happens. No threshold tuning recovers it. per_feature.py cannot compensate either: it
# consumes a scores dict and never opens an image, so its critical-feature gate is sound and starved.
# Feature-scale fidelity needs zoom patches instead: grimoire/review/divine_eye_microscope.md.
LUMA_SIZE = 64   # SSIM / tonal / blowout / flat work on this downsampled luma grid
EDGE_SIZE = 96   # edge overlap grid
HUE_ZONE_DELTA_E = 2.3   # per-band CIEDE2000 "same hue zone" tolerance (Context Part 2.2)
HUE_ZONE_BANDS = 8       # bands sampled along the axis for hue_zone_parity
COLOR_SAMPLE = 160       # coarse per-axis subsample cap for colour helpers (perf on full-res refs)

# --- adapter-provided reference mask -------------------------------------------------------
# The heuristic (build_foreground_mask) models the background from the image corners. That is
# sound for renders (uniform backdrop) and for product-style photos, but it cannot segment a
# photo whose backdrop is itself structured — banded studio lighting deviates from any corner
# model by more than any threshold that still admits the subject. For those references the
# pipeline's own answer is the segmentation adapter (`run_vision_adapter.py segment`, SAM2),
# which drops a mask + provenance sidecar into the workspace. When that artifact is present it
# is the REFERENCE-side ruler here; the RENDER side always keeps the heuristic.
WORKSPACE_STATE_DIR = ".img2threejs"
REFERENCE_MASK_NAME = "reference-mask.png"
REFERENCE_MASK_SIDECAR_NAMES = (
    "reference-mask.json",           # canonical: written with `segment --json-out`
    "reference-mask.png.json",       # the adapter's default sidecar name for that output
)
REFERENCE_MASK_KIND = "segmentation-mask"
MASK_SOURCE_ARTIFACT = f"artifact:{REFERENCE_MASK_KIND}"
MASK_SOURCE_HEURISTIC = "heuristic"


class ReferenceMaskError(RuntimeError):
    """A reference-mask artifact exists but cannot be trusted to score this reference.

    Raised instead of falling back to the heuristic: a silent fallback would publish a fidelity
    number whose ruler nobody can name afterwards. Present-but-invalid is always a hard stop.
    """


class ReferenceMask(NamedTuple):
    """A validated artifact mask: full-resolution truth plus the scoring grid derived from it."""

    path: Path
    sidecar: Path
    full: list[bool]          # width*height, foreground=True — for the colour helpers
    grid: list[bool]          # MASK_GRID_SIZE² — for IoU/bbox/symmetry, same grid as load_mask
    warnings: list[str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def find_reference_mask_artifact(reference_png: Path) -> tuple[Path, Path | None] | None:
    """Locate `<workspace>/.img2threejs/reference-mask.png` for this reference, or None.

    The workspace root is the NEAREST ancestor of the reference image that owns a state
    directory — the scoring path is handed image paths, never a workspace, and every sanctioned
    run keeps its reference inside the workspace it is scoring. The search stops at that first
    state directory so a stale mask in some outer directory can never be adopted for an inner
    workspace. No state directory above the reference ⇒ no artifact ⇒ heuristic, as before.
    """
    reference_png = reference_png.resolve()
    for candidate in (reference_png.parent, *reference_png.parent.parents):
        state_dir = candidate / WORKSPACE_STATE_DIR
        if not state_dir.is_dir():
            continue
        mask_path = state_dir / REFERENCE_MASK_NAME
        if not mask_path.exists():
            return None
        sidecar = next((state_dir / name for name in REFERENCE_MASK_SIDECAR_NAMES
                        if (state_dir / name).is_file()), None)
        return mask_path, sidecar
    return None


def _read_sidecar(mask_path: Path, sidecar: Path, reference_png: Path) -> dict[str, Any]:
    """Parse and authenticate the provenance envelope the segmentation adapter emits."""
    try:
        envelope = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReferenceMaskError(f"reference mask sidecar {sidecar} is unreadable: {exc}") from exc
    if not isinstance(envelope, dict):
        raise ReferenceMaskError(f"reference mask sidecar {sidecar} is not a JSON object")
    kind = envelope.get("kind")
    if kind != REFERENCE_MASK_KIND:
        raise ReferenceMaskError(
            f"reference mask sidecar {sidecar} declares kind {kind!r}, not {REFERENCE_MASK_KIND!r}"
        )
    source_sha = envelope.get("sourceSha256")
    if not isinstance(source_sha, str) or not source_sha:
        raise ReferenceMaskError(
            f"reference mask sidecar {sidecar} carries no sourceSha256; nothing proves the mask "
            "was cut from the reference being scored"
        )
    actual_sha = _sha256(reference_png)
    if source_sha.lower() != actual_sha.lower():
        raise ReferenceMaskError(
            f"reference mask {mask_path} was cut from a different image: sidecar sourceSha256 "
            f"{source_sha[:12]}… (sourceImage {envelope.get('sourceImage')}) but "
            f"{reference_png} hashes to {actual_sha[:12]}…"
        )
    output_sha = envelope.get("outputSha256")
    if isinstance(output_sha, str) and output_sha:
        actual_mask_sha = _sha256(mask_path)
        if output_sha.lower() != actual_mask_sha.lower():
            raise ReferenceMaskError(
                f"reference mask {mask_path} changed after its sidecar was written: sidecar "
                f"outputSha256 {output_sha[:12]}… but the file hashes to {actual_mask_sha[:12]}…"
            )
    return envelope


def _artifact_foreground(pixels: list[tuple[int, int, int, int]]) -> list[bool]:
    """Foreground rule for a mask image: alpha when the mask carries transparency, else luma.

    A mask painted as shape-on-transparent and a mask painted as white-on-black are both
    idiomatic; reading luma on the first would call the whole frame foreground, so transparency
    wins whenever the image actually uses it.
    """
    has_alpha = any(alpha < 255 for _r, _g, _b, alpha in pixels)
    if has_alpha:
        return [alpha > 0 for _r, _g, _b, alpha in pixels]
    return [r > 0 or g > 0 or b > 0 for r, g, b, _a in pixels]


def _grid_from_full_mask(
    mask: list[bool],
    width: int,
    height: int,
    size: int = MASK_GRID_SIZE,
) -> tuple[list[bool], list[str]]:
    """Downsample + largest-blob filter, mirroring diagnose_render.load_mask.

    The artifact mask must reach the signals through exactly the post-processing the render-side
    heuristic mask goes through, or IoU would compare two differently-conditioned silhouettes.
    """
    resized: list[bool] = []
    for y in range(size):
        sy = min(height - 1, int(y * height / size))
        for x in range(size):
            sx = min(width - 1, int(x * width / size))
            resized.append(mask[sy * width + sx])
    filtered, discarded = largest_component(resized, size)
    warnings: list[str] = []
    if discarded > 0.02:
        warnings.append(
            f"{discarded:.1%} of foreground cells lie outside the largest connected blob and were "
            "excluded from the bounding box; if the subject really has separated parts in this "
            "projection, they are not being measured"
        )
    return filtered, warnings


def load_reference_mask_artifact(reference_png: Path) -> ReferenceMask | None:
    """Return the validated adapter mask for this reference, or None when none is published."""
    found = find_reference_mask_artifact(reference_png)
    if found is None:
        return None
    mask_path, sidecar = found
    if sidecar is None:
        raise ReferenceMaskError(
            f"reference mask {mask_path} has no provenance sidecar; expected one of "
            f"{', '.join(REFERENCE_MASK_SIDECAR_NAMES)} beside it — an unprovenanced mask cannot "
            "be tied to the reference it claims to segment"
        )
    envelope = _read_sidecar(mask_path, sidecar, reference_png)
    ref_width, ref_height, _ref_pixels, _ref_warn = load_image(reference_png)
    try:
        width, height, pixels, warnings = load_image(mask_path)
    except Exception as exc:  # noqa: BLE001 — any decode failure is one fail-loud condition
        raise ReferenceMaskError(f"reference mask {mask_path} could not be decoded: {exc}") from exc
    if (width, height) != (ref_width, ref_height):
        raise ReferenceMaskError(
            f"reference mask {mask_path} is {width}x{height} but the reference "
            f"{reference_png} is {ref_width}x{ref_height}; a resampled mask would move the "
            "silhouette it is supposed to measure"
        )
    declared = envelope.get("imageSize")
    if isinstance(declared, list) and len(declared) == 2 and list(declared) != [ref_width, ref_height]:
        raise ReferenceMaskError(
            f"reference mask sidecar {sidecar} declares imageSize {declared} but the reference "
            f"{reference_png} is {ref_width}x{ref_height}"
        )
    full = _artifact_foreground(pixels)
    if not any(full):
        raise ReferenceMaskError(
            f"reference mask {mask_path} marks no foreground pixels; it cannot measure a silhouette"
        )
    grid, grid_warnings = _grid_from_full_mask(full, width, height)
    return ReferenceMask(
        path=mask_path,
        sidecar=sidecar,
        full=full,
        grid=grid,
        warnings=list(warnings) + grid_warnings,
    )


def _banded_median_lab(png_path: Path, axis: str, bands: int,
                       mask_override: list[bool] | None = None) -> list[tuple[float, float, float] | None]:
    """Median CIELAB per foreground-masked band along the axis (axis 'u'=x, 'v'=y).
    Colour-aware (not luma) — used only by hue_zone_parity, which is report-only until calibrated.
    mask_override carries the validated reference-mask artifact so every reference-side mask in
    this module names the same source; None keeps the heuristic (always the case render-side)."""
    width, height, pixels, _ = load_image(png_path)
    if mask_override is not None:
        mask = mask_override
    else:
        mask, _meta, _warn = build_foreground_mask(width, height, pixels)
    span = width if axis == "u" else height
    band = max(1, span // bands)
    # Subsample on a coarse grid (≤ COLOR_SAMPLE px/axis) so full-res references stay O(fast) —
    # median hue is stable under downsampling (Context Part 2.5 perf note).
    sx = max(1, width // COLOR_SAMPLE)
    sy = max(1, height // COLOR_SAMPLE)
    out: list[tuple[float, float, float] | None] = []
    for b in range(bands):
        lo = b * band
        hi = span if b == bands - 1 else (b + 1) * band
        rs: list[int] = []
        gs: list[int] = []
        bs: list[int] = []
        for y in range(0, height, sy):
            for x in range(0, width, sx):
                coord = x if axis == "u" else y
                if coord < lo or coord >= hi:
                    continue
                idx = y * width + x
                if idx >= len(mask) or not mask[idx]:
                    continue
                r, g, bl, _a = pixels[idx]
                rs.append(r)
                gs.append(g)
                bs.append(bl)
        if not rs:
            out.append(None)
            continue
        rs.sort(); gs.sort(); bs.sort()
        m = len(rs) // 2
        out.append(srgb_to_lab((rs[m], gs[m], bs[m])))
    return out


def _foreground_hsv_stats(png_path: Path, mask_override: list[bool] | None = None) -> tuple[float, float]:
    """Saturation-weighted mean (hueDeg, saturation) over the foreground. Colour-aware."""
    import colorsys
    import math as _m
    width, height, pixels, _ = load_image(png_path)
    if mask_override is not None:
        mask = mask_override
    else:
        mask, _meta, _warn = build_foreground_mask(width, height, pixels)
    sx = max(1, width // COLOR_SAMPLE)
    sy = max(1, height // COLOR_SAMPLE)
    sc = ss = wsum = sat_sum = 0.0
    n = 0
    for y in range(0, height, sy):
        for x in range(0, width, sx):
            idx = y * width + x
            if idx >= len(mask) or not mask[idx]:
                continue
            r, g, b, _a = pixels[idx]
            h, s, _v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            sat_sum += s
            n += 1
            if s > 0.15:
                sc += s * _m.cos(2 * _m.pi * h)
                ss += s * _m.sin(2 * _m.pi * h)
                wsum += s
    mean_sat = sat_sum / n if n else 0.0
    mean_hue = (_m.degrees(_m.atan2(ss, sc)) % 360.0) if wsum > 0 else 0.0
    return mean_hue, mean_sat


def specular_wash(reference_png: Path, render_png: Path,
                  reference_mask: list[bool] | None = None) -> dict[str, Any]:
    """Detect the envMap/metalness 'hue theft': the render desaturates a saturated reference AND
    drifts its hue toward cyan (~180°). Report-only — advisory, never a gate (lighting legitimately
    shifts hue). Returns {satRatio, hueDriftDeg, towardCyan, flagged}. (Context Part 3.2)."""
    ref_hue, ref_sat = _foreground_hsv_stats(reference_png, reference_mask)
    ren_hue, ren_sat = _foreground_hsv_stats(render_png)
    sat_ratio = (ren_sat / ref_sat) if ref_sat > 1e-6 else 1.0
    # circular hue drift toward cyan (180°): did the render move closer to 180 than the reference?
    ref_to_cyan = min(abs(ref_hue - 180.0), 360.0 - abs(ref_hue - 180.0))
    ren_to_cyan = min(abs(ren_hue - 180.0), 360.0 - abs(ren_hue - 180.0))
    toward_cyan = ren_to_cyan < ref_to_cyan
    flagged = ref_sat > 0.35 and sat_ratio < 0.6 and toward_cyan
    return {
        "satRatio": round(sat_ratio, 3),
        "hueDriftDeg": round(ref_to_cyan - ren_to_cyan, 1),
        "towardCyan": toward_cyan,
        "flagged": flagged,
        "advice": "lower metalness / envMapIntensity (candy-coat dielectric recipe)" if flagged else None,
    }


def hue_zone_parity(reference_png: Path, render_png: Path, axis: str = "u",
                    bands: int = HUE_ZONE_BANDS,
                    reference_mask: list[bool] | None = None) -> float:
    """Fraction of along-axis bands whose median colour matches the reference within CIEDE2000
    ≤ HUE_ZONE_DELTA_E. Catches "purple rendered blue" that luma/structure signals miss.
    Report-only (no ensemble weight) until calibrated on the labeled corpus."""
    ref = _banded_median_lab(reference_png, axis, bands, reference_mask)
    ren = _banded_median_lab(render_png, axis, bands)
    matched = 0
    counted = 0
    for a, b in zip(ref, ren):
        if a is None or b is None:
            continue
        counted += 1
        if ciede2000(a, b) <= HUE_ZONE_DELTA_E:
            matched += 1
    return matched / counted if counted else 0.0


def load_luma(png_path: Path, size: int) -> list[float]:
    """Box-average downsample of Rec.709 luma to size×size, normalized 0..1."""
    width, height, pixels, _warn = load_image(png_path)
    acc = [0.0] * (size * size)
    cnt = [0] * (size * size)
    for idx, (r, g, b, _a) in enumerate(pixels):
        x = idx % width
        y = idx // width
        if y >= height:
            break
        cell = min(size - 1, y * size // height) * size + min(size - 1, x * size // width)
        acc[cell] += (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
        cnt[cell] += 1
    return [acc[i] / cnt[i] if cnt[i] else 0.0 for i in range(size * size)]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def global_ssim(a: list[float], b: list[float]) -> float:
    """Single-window SSIM over the whole downsampled luma image (structure signal)."""
    n = len(a)
    if n == 0 or len(b) != n:
        return 0.0
    mu_a, mu_b = _mean(a), _mean(b)
    var_a = _mean([(x - mu_a) ** 2 for x in a])
    var_b = _mean([(x - mu_b) ** 2 for x in b])
    cov = _mean([(a[i] - mu_a) * (b[i] - mu_b) for i in range(n)])
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    ssim = ((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / (
        (mu_a ** 2 + mu_b ** 2 + c1) * (var_a + var_b + c2)
    )
    return max(0.0, min(1.0, ssim))


def _sobel_edges(luma: list[float], size: int, thresh: float = 0.12) -> list[bool]:
    edges = [False] * (size * size)
    for y in range(1, size - 1):
        for x in range(1, size - 1):
            def g(dx, dy):
                return luma[(y + dy) * size + (x + dx)]
            gx = (g(-1, -1) + 2 * g(-1, 0) + g(-1, 1)) - (g(1, -1) + 2 * g(1, 0) + g(1, 1))
            gy = (g(-1, -1) + 2 * g(0, -1) + g(1, -1)) - (g(-1, 1) + 2 * g(0, 1) + g(1, 1))
            if math.hypot(gx, gy) > thresh:
                edges[y * size + x] = True
    return edges


def edge_overlap(a: list[float], b: list[float], size: int) -> float:
    ea, eb = _sobel_edges(a, size), _sobel_edges(b, size)
    inter = union = 0
    for i in range(len(ea)):
        if ea[i] or eb[i]:
            union += 1
            if ea[i] and eb[i]:
                inter += 1
    return inter / union if union else 0.0


def _blown_fraction(luma: list[float], hi: float = 0.95) -> float:
    return sum(1 for v in luma if v >= hi) / max(1, len(luma))


def blowout_parity(ref: list[float], ren: list[float]) -> float:
    diff = abs(_blown_fraction(ren) - _blown_fraction(ref))
    return max(0.0, 1.0 - diff * 4.0)  # 25% extra blown pixels ⇒ score 0


def flat_fraction(luma: list[float], size: int, eps: float = 0.02) -> float:
    """Fraction of pixels whose local gradient is ~0 (a dead flat fill)."""
    flat = 0
    total = 0
    for y in range(1, size - 1):
        for x in range(1, size - 1):
            c = luma[y * size + x]
            grad = abs(c - luma[y * size + x - 1]) + abs(c - luma[(y - 1) * size + x])
            total += 1
            if grad < eps:
                flat += 1
    return flat / total if total else 0.0


def tonal_parity(ref: list[float], ren: list[float], bins: int = 16) -> float:
    def hist(xs):
        h = [0] * bins
        for v in xs:
            h[min(bins - 1, int(v * bins))] += 1
        tot = sum(h) or 1
        return [c / tot for c in h]
    ha, hb = hist(ref), hist(ren)
    l1 = sum(abs(ha[i] - hb[i]) for i in range(bins))
    return max(0.0, 1.0 - l1 / 2.0)  # L1 over two distributions ∈ [0,2]


def evaluate(reference_png: Path, render_png: Path) -> dict[str, Any]:
    """Run all deterministic signals and combine into a verdict + routing action."""
    # Reference side: the adapter artifact when the workspace publishes one (validated, or a hard
    # error — never a quiet fallback), else the corner-model heuristic exactly as before.
    reference_mask = load_reference_mask_artifact(reference_png)
    if reference_mask is None:
        ref_mask, ref_mask_warnings = load_mask(reference_png)
        ref_mask_source = MASK_SOURCE_HEURISTIC
    else:
        ref_mask, ref_mask_warnings = reference_mask.grid, reference_mask.warnings
        ref_mask_source = MASK_SOURCE_ARTIFACT
    ref_full_mask = reference_mask.full if reference_mask is not None else None
    # Render side always stays heuristic: renders have a uniform backdrop (measured noise 0.0),
    # which is precisely the case the corner model is correct for.
    ren_mask, ren_mask_warnings = load_mask(render_png)
    ref_luma = load_luma(reference_png, LUMA_SIZE)
    ren_luma = load_luma(render_png, LUMA_SIZE)
    ref_edge = load_luma(reference_png, EDGE_SIZE)
    ren_edge = load_luma(render_png, EDGE_SIZE)
    rw, rh, rpx, _ = load_image(reference_png)
    vw, vh, vpx, _ = load_image(render_png)

    iou = silhouette_iou(ref_mask, ren_mask)
    prop = proportion_delta(bbox_of(ref_mask), bbox_of(ren_mask))
    # proportion_delta returns snake_case keys; reading camelCase here silently defaulted both
    # to 0.0, which dead-coded the scale HARD gate and pinned the proportion soft signal at 1.0.
    scale_delta = prop.get("scale_delta", 0.0)
    aspect_delta = prop.get("aspect_ratio_delta", 0.0)
    # symmetry + flat-region are PARITY signals (render vs reference), NOT absolute —
    # a legitimately asymmetric or flat-lit subject must not be penalized when the
    # render matches the reference. score = 1 when render is as (a)symmetric / as flat
    # as the reference; drops when the render diverges (e.g. render flatter ⇒ material
    # not reacting to light).
    sym_ref = bilateral_symmetry_error(ref_mask)
    sym_ren = bilateral_symmetry_error(ren_mask)
    sym = max(0.0, 1.0 - abs(sym_ren - sym_ref) / 0.10)
    flat_ref = flat_fraction(ref_luma, LUMA_SIZE)
    flat_ren = flat_fraction(ren_luma, LUMA_SIZE)
    flat = max(0.0, 1.0 - abs(flat_ren - flat_ref) * 4.0)
    phash_sim = normalized_similarity(phash_from_image(rw, rh, rpx), phash_from_image(vw, vh, vpx))
    ssim = global_ssim(ref_luma, ren_luma)
    edges = edge_overlap(ref_edge, ren_edge, EDGE_SIZE)
    blow = blowout_parity(ref_luma, ren_luma)
    tonal = tonal_parity(ref_luma, ren_luma)
    # OSIM-lite objectness (stdlib HOG-like, bg/pose/scale/brightness-invariant). Graceful:
    # if it errors it degrades to absent (must-not-block, R-OSIM-EFFORT). It is the one
    # signal that stays meaningful for photo-vs-procedural where IoU/SSIM/edge collapse.
    try:
        objectness: float | None = objectness_similarity(reference_png, render_png)
    except Exception:
        objectness = None

    # hue_zone_parity: colour-aware along-axis hue match (CIEDE2000). REPORT-ONLY — not in the
    # weighted ensemble until calibrated on the labeled corpus. Catches "purple→blue" that
    # every luma/structure signal above is blind to. Graceful: degrades to None on error.
    try:
        hue_zone: float | None = hue_zone_parity(reference_png, render_png,
                                                 reference_mask=ref_full_mask)
    except Exception:
        hue_zone = None
    try:
        spec_wash: dict[str, Any] | None = specular_wash(reference_png, render_png,
                                                         reference_mask=ref_full_mask)
    except Exception:
        spec_wash = None

    # HARD gates: a fail is an immediate reject with a specific numeric reason.
    hard_failures: list[str] = []
    if mask_is_inverted(ref_mask_warnings) or mask_is_inverted(ren_mask_warnings):
        hard_failures.append(
            "foreground mask fell back to whole-frame coverage; silhouette, scale and aspect "
            "signals are not measuring the subject"
        )
    if iou < IOU_HARD_MIN:
        hard_failures.append(f"silhouette IoU {iou:.3f} < {IOU_HARD_MIN}")
    if scale_delta > SCALE_HARD_MAX:
        hard_failures.append(f"scale delta {scale_delta:.3f} > {SCALE_HARD_MAX}")

    # SOFT signals → weighted ensemble fidelity. Weights are provisional (Phase 5
    # calibrates them on the known-good/known-bad corpus); recorded here so they are
    # auditable, not magic.
    soft = {
        "proportion": (max(0.0, 1.0 - aspect_delta / 0.05), 1.0),
        "symmetry": (sym, 0.5),
        "phash": (phash_sim, 1.0),
        "ssim": (ssim, 1.5),
        "edgeOverlap": (edges, 1.0),
        "blowoutParity": (blow, 0.8),
        "flatRegion": (flat, 0.8),
        "tonalParity": (tonal, 1.0),
    }
    if objectness is not None:
        soft["objectness"] = (objectness, 1.5)  # strongest structural signal when present
    weighted = sum(s * w for s, w in soft.values())
    total_w = sum(w for _s, w in soft.values())
    fidelity = weighted / total_w if total_w else 0.0

    soft_scores = [s for s, _w in soft.values()]
    spread = max(soft_scores) - min(soft_scores) if soft_scores else 0.0

    # Verdict + routing (deterministic function of which signal failed — §3.5).
    if hard_failures:
        verdict, action = "reject", "refine-code"
    elif spread > DISAGREEMENT_SPREAD and fidelity < FIDELITY_TARGET:
        verdict, action = "low-confidence", "probe"
    elif fidelity >= FIDELITY_TARGET:
        verdict, action = "pass", "continue"
    else:
        verdict, action = "reject", "refine-code"

    # Reconstruction-mode rescue: a *photo* reference vs a *procedural* render fails the
    # silhouette-IoU hard gate purely from framing/background/scale mismatch. When the only
    # hard failure is IoU AND objectness says "same object" (high, brightness/bg-invariant),
    # downgrade the confident reject to a probe rather than hard-failing a faithful build.
    # Never rescues a scale-delta failure or a genuinely different object (low objectness).
    reconstruction_suspected = False
    if hard_failures and objectness is not None and objectness >= RECON_OBJ_MIN:
        if all("silhouette IoU" in f for f in hard_failures):
            reconstruction_suspected = True
            # Per-track calibration: silhouette IoU 0.85 is unreachable for a procedural-primitive
            # reconstruction of a detailed photo (solid primitives structurally over-fill cutouts,
            # serrations and AA curves), so IoU alone must not veto forever — otherwise the loop can
            # only ever bounded-stop. When objectness confirms the same object AND the soft ensemble
            # already meets the fidelity target AND scale/aspect are within gate, promote the
            # IoU-only reject to a real pass; otherwise route to probe (human/VLM look). Genuinely
            # wrong geometry still fails: low objectness isn't rescued at all, and a weak soft
            # ensemble (< target) or an out-of-gate scale/aspect can only reach probe, never pass.
            if fidelity >= FIDELITY_TARGET and scale_delta <= SCALE_HARD_MAX and aspect_delta <= ASPECT_SOFT_MAX:
                verdict, action = "pass", "continue"
            else:
                verdict, action = "low-confidence", "probe"

    return {
        "verdict": verdict,
        "action": action,
        "fidelity": round(fidelity, 4),
        "fidelityTarget": FIDELITY_TARGET,
        "hardGateFailures": hard_failures,
        "maskWarnings": (
            [f"reference: {w}" for w in ref_mask_warnings]
            + [f"render: {w}" for w in ren_mask_warnings]
        ),
        "disagreementSpread": round(spread, 4),
        "signals": {
            "silhouetteIoU": round(iou, 4),
            "scaleDelta": round(scale_delta, 4),
            "aspectRatioDelta": round(aspect_delta, 4),
            "symmetryParity": round(sym, 4),
            "phashSimilarity": round(phash_sim, 4),
            "ssim": round(ssim, 4),
            "edgeOverlap": round(edges, 4),
            "blowoutParity": round(blow, 4),
            "flatRegionScore": round(flat, 4),
            "tonalParity": round(tonal, 4),
            "objectness": round(objectness, 4) if objectness is not None else None,
            "hueZoneParity": round(hue_zone, 4) if hue_zone is not None else None,
        },
        "specularWash": spec_wash,
        "reportOnlySignals": ["hueZoneParity", "specularWash"],
        "reconstructionModeSuspected": reconstruction_suspected,
        "weights": {k: w for k, (_s, w) in soft.items()},
        "reference": str(reference_png.resolve()),
        "render": str(render_png.resolve()),
        # Which ruler produced this score. Without it a fidelity number is ambiguous about the
        # silhouette it was measured against.
        "referenceMaskSource": ref_mask_source,
        "referenceMaskArtifact": str(reference_mask.path) if reference_mask is not None else None,
        "note": "deterministic ensemble; zero VLM/token. hueZoneParity is REPORT-ONLY (colour-aware, "
                "CIEDE2000) — not yet in the weighted fidelity; promote after corpus calibration. "
                "VLM layer (§3.4) runs only if this passes.",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--render", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = evaluate(args.reference.expanduser().resolve(), args.render.expanduser().resolve())
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"{result['verdict'].upper()} → {result['action']}  fidelity={result['fidelity']} "
              f"(target {result['fidelityTarget']})")
        if result["referenceMaskArtifact"]:
            print(f"  reference mask: {result['referenceMaskSource']} "
                  f"({result['referenceMaskArtifact']})")
        for f in result["hardGateFailures"]:
            print(f"  HARD: {f}")
    # exit 0 only on a clean pass; non-zero otherwise so a pipeline can gate on it.
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
