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

The original browser render-profile schema has browser-specific constants and is
not a valid Blender manifest. Use the adapter's truthful evidence receipt instead;
do not impersonate browser authority. The source/current model is the preservation
baseline. Without actual target diagnostic channels, mark paired target-channel
comparisons unavailable. The original compare_region_passes CLI does not accept
this adapter receipt directly: do not claim that integration is implemented. Retain
output six-pass evidence, real region mapping and applicable image/geometry gates;
missing required gate compatibility is a recorded limitation/partial result, not a
waiver or a fabricated pass. No hidden GT geometry/passes may be used.
