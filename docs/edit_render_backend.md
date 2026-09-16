# Editing capture backend: GT Blender adapter

Only capture transport differs from the browser branch. Wherever the original
workflow requests a browser screenshot/capture, provide a real GT Blender capture;
where it requests browser mesh export, provide the evaluated mesh export from the
same saved assembled candidate. Keep spec/factory/pass locks, camera iterations,
quality thresholds, semantic requirements and gate decisions unchanged. Blender
is not authorized to model new parts. This renderer mapping takes precedence over
browser-only backend sentences in supporting documents, not over their checks.

Executable: /gs/fs/tga-koike-shanda4/yurh/blender-4.2.18-linux-x64/blender
GT renderer: /gs/fs/tga-koike-shanda4/yurh/blender_kit/scripts/render.py
Adapter: forge/stage4_review/capture_blender_edit.py

Run the executable with `-b -P <absolute adapter> -- --job <job.json> --regions
<regions.json>`. Job fields: scene=mesh, absolute mesh, material=file_embedded,
normalize=none, source_frame=y_up, frames=1, res=420, samples=32, absolute out_dir.
For evaluation copy frame_center/frame_diag/start_az/elevation/distance from the
supplied camera frame. Review views use separate named jobs and editable cameras.
Keep the GT lighting defaults. Never alter source coordinates for framing.

regions.json contains {"regions":[{"id":"barrel","index":1,"objects":["body"]}]}.
Map every imported mesh explicitly; identifiers do not establish semantics without
inspection. The adapter fails on missing/unmapped objects. It calls the unmodified
GT renderer and outputs beauty PNG, six channels in multilayer EXR, region/material
mapping, evaluated source-Y-up world meshes.json and a hashed evidence receipt.
Depth is raw Blender depth; normals are world-space Blender Z-up. The sixth channel
uses the material-ID option, not roughness. Do not mislabel constant colors as data.

Use PNGs with the original diagnose_render, multi-angle, comparison-sheet and
append_review tools; meshes.json supplies vertices/indices to self_intersection.
Supply genuinely measured anchors to attachment_anchor. Capture the same required
turntable views. Existing host defects do not authorize modifying untouched parts.
Record each applicable original gate; capture success alone is not gate success.

## Paired-pass comparison bridge

After capturing two states at the SAME camera/settings, convert their real EXR
channels using `forge/stage4_review/prepare_blender_pass_pair.py`:

```bash
PYTHONPATH=/gs/fs/tga-koike-shanda4/yurh/img2threejs_capture_deps \
/gs/fs/tga-koike-shanda4/yurh/miniconda3/envs/partflow/bin/python \
  <skill-root>/forge/stage4_review/prepare_blender_pass_pair.py \
  --reference <previous-capture>/evidence.json \
  --candidate <candidate-capture>/evidence.json \
  --out <pair-folder> --depth-near 0 --depth-far <shared-far>
python3 <skill-root>/forge/stage4_review/compare_region_passes.py \
  --manifest <pair-folder>/manifest.json --capture-id hero \
  --out <pair-folder>/comparison.json
```

The converter requires numpy, Pillow and OpenEXR (the latter installed in the
PYTHONPATH directory above). It validates source/capture hashes, camera settings
and renderer identity. Depth uses one declared range for BOTH captures and fails
on foreground clipping. Normal XYZ uses the same world Z-up encoding for both;
ID colors share a joint region/material-name mapping. Data PNGs use raw byte
codes without a color transfer; beauty PNGs are retained unchanged. EXR originals
remain authoritative floating-point evidence. No GT channel is synthesized.

The paired-pass-evidence.v1 manifest truthfully declares blender-kit authority;
it is not mislabeled as the browser profile. The common region comparator now
accepts this transport alongside the original browser transport, while using
identical scoring functions. Missing passes, camera/encoding differences and
corrupt PNG/profile hashes reject comparison. Material-ID similarity is the
original encoded-image diagnostic, not a physical material-distance metric.

Current-model/candidate pairs support preservation checks. Changed regions are
not expected to match their previous state; use target RGB to judge the requested
edit. Without supplied target channels, target depth/normal agreement is unknown.
The adapter does not create withheld GT information or replace original build gates.
