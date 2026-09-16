---
name: img2threejs
description: Build procedural Three.js parts from images, or edit an existing GLB through localized part operations, with staged specs, render feedback and bounded self-correction.
license: Apache-2.0
metadata:
  upstream-version: 2.0.0
  local-workflow: pxform-edit-v5-evidence
---

# img2threejs — procedural construction and source-model editing

Select the task once. If given an existing model to edit, follow **Source-model
editing** below. If asked to reconstruct a whole object from scratch, follow
`docs/reconstruction_workflow.md` instead. Do not load the reconstruction workflow
for a source-model editing task. Its whole-object no-copy, browser-runtime,
animation and independent-factory requirements belong to reconstruction only.
Both routes retain img2threejs's spec → staged build → visual review → correction
process. Supporting documents provide geometry recipes and gate mechanics; task
scope, renderer selection and chain termination are defined here for editing.

## Source-model editing: inputs and operation decision

Inputs: current GLB, text instruction, target image and supplied camera. For a
chain, turn 1 starts from `input/source.glb`; turn k starts from the saved result
of k−1. Never reset to a GT mesh. Read the current turn's text AND image yourself.
Inspect the current model's nodes, geometry, materials and world transforms.
Use semantic and visual evidence to decide add/remove/replace/retexture and the
affected region; do not infer the operation from a dataset cell name or assume
one node always equals one semantic part. Record the decision and affected nodes.
`forge/stage1_intake/probe_glb.py` helps inspect structure; it does not identify
parts visually for you. All intermediate files belong to the example directory.

Preserve every unaffected part's geometry, materials, names and world transforms.
Copying retained source content is required, not forbidden. Construct only the
new/replacement part with Three.js. Do not rebuild the host. Source inspection,
GLB decoding, merging, exporting and compaction may use local Python/Node code;
Blender is the renderer, not a second modeling backend. No asset retrieval,
neural geometry generation or image-generation/editing model is allowed.

| Inferred operation | Execution route |
|---|---|
| remove | Identify and physically delete the target; structural verification; render if identification or removal is uncertain. No sculpt spec/factory/pass loop. |
| add | Construct a new part through the img2threejs loop below, install it in the current model, and review in context. |
| replace | Construct a replacement through that loop, remove only the old target, install the new part, and review in context. |
| retexture | Use the replacement route in this experiment. Build a replacement part matching the target appearance and original intended shape/pose; run the same material and visual iteration. Do not shortcut to a one-line recolor and declare completion. Record semantic_op=retexture, execution_op=replace; the dataset label is unchanged. |

Source geometry may guide replacement dimensions and attachments; it is not a
license to modify unrelated parts. For retexture, geometric drift is a defect to
correct, not a requested edit. Preserve unrelated child attachments and their
world transforms; do not silently discard them with a replaced parent.

## Remove and replacement cleanup

Delete targeted nodes and all their scene/parent references from the exported
GLB. Merely unlinking `scene.nodes`, hiding or zero-scaling is insufficient.
Garbage-collect meshes, accessors, bufferViews, materials, textures and images
owned exclusively by removed content. Retain shared resources, repack BIN and
remap references consistently, including skins/animations if present. When only
part of a mesh is targeted, preserve its unrelated geometry. Reload the output
and verify removed content is absent and surviving decoded content is unchanged.
File hashes/array indices may change during compaction; surviving data may not.
For an unambiguous remove, this structural check can finish the turn. If uncertain,
render once, inspect, and correct the deletion; do not run new-part construction.

## Add / replace / retexture: the img2threejs construction loop

Use a separate `work/turnNN/` state/spec/review history for each constructed part.
Run forge scripts from the skill root with absolute example-local file paths.
Read the named supporting documents at the relevant stage, not the entire corpus.
A spec describes the edited part; the host is immutable assembly context.

1. **Observe and assess.** Follow `grimoire/intake/image_analysis.md` and
   `grimoire/intake/quality_contract.md`: macro/meso/micro shape, materials,
   installation face, scale, orientation, contact and visible identity features.
   Use `forge/stage1_intake/probe_image.py`, then
   `forge/stage2_spec/new_pre_spec_assessment.py` and the skill's local spec search
   (`grimoire/intake/local_spec_search.md`). This is retrieval of modeling
   knowledge within the skill, not retrieval of assets or other benchmark cases.
   Crop the target part when useful; retain the original full target for context.
2. **Spec and state.** Use `forge/stage2_spec/new_sculpt_spec.py` with the assessment;
   fill actual component hierarchy, topology, features, PBR materials, pivots and
   attachment anchors. Follow `grimoire/intake/surface_topology.md` and
   `grimoire/build/geometry_patterns.md`; a complex shape is not automatically a
   box. Validate with `forge/stage2_spec/validate_sculpt_spec.py`, including
   `--strict-quality`. Initialize with `forge/state.py init --state <state.json>
   --reference <part-reference.png> --profile generic --spec <spec.json>` (use a
   subject-specific profile only for the part actually being constructed).
   Call `forge/next.py --state <state.json> <spec.json>` on start/resume and before
   every correction. Keep evidence for completed steps and explicit reasons for
   non-applicable steps; never mark a failed mandatory gate passed.
3. **Build in locked passes.** Use `forge/stage3_build/orchestrate_passes.py status`
   and `forge/stage3_build/generate_threejs_factory.py` for the part. Preserve the
   skill's blockout → structure → form → material → lighting → interaction →
   optimization order and its pass locks. Lighting here means inspecting the
   material under fixed GT illumination, not changing that illumination. Static
   GLB output needs no invented animation/UI. Mark genuinely non-applicable
   interaction/rig steps with reasons where supported, not fabricated evidence.
   Use `refine-spec` for wrong intent/spec, `refine-code` for faulty implementation;
   carry valid code refinements back into the spec before regeneration.
4. **Export and assemble every reviewed candidate.** Instantiate the generated
   Three.js part, export its geometry/materials as GLB, merge it into the current
   scene at the inferred support/contact frame, and reload the saved candidate.
   Use standard Three.js GLTFExporter or equivalent GLB serialization; retain
   transforms, normals/winding, UVs and material bindings. The factory is the
   construction implementation; the assembled GLB is the review artifact.
   Export the *world-transformed constructed mesh* to geometry JSON when a gate
   needs it, using that gate's actual input schema. No browser URL is necessary.
5. **Render, diagnose, inspect.** Use the renderer below. Review the assembled
   scene against the full target AND the part's visible region, not just a part
   floating in isolation. Compare identically cropped reference/render regions
   when the part is small; record the crop coordinates. Use actual saved images:
   `forge/stage4_review/diagnose_render.py --reference <ref.png> --render <png>
   --spec <spec.json> --pass-id <pass> --in-place`, then
   `forge/stage3_build/orchestrate_passes.py check <spec.json> --pass-id <pass>`.
   Read `grimoire/review/gates_reference.md` and
   `grimoire/review/self_correction.md` for applicable gate mechanics. Inspect
   geometry, winding, symmetry, scale, support and attachment using
   `self_intersection.py` and `attachment_anchor.py` with measured constructed
   geometry/anchors. Intentional inter-part contact is not mesh self-intersection.
   For non-planar new parts also render diagnostic side views and use
   `diagnose_render_multi_angle.py`; these test geometry, not unseen-GT similarity.
   `turntable_gate.py` accepts Blender PNGs for 0/90/180/270 diagnostic views.
   Apply character/hair/rig gates only if that edited part actually needs them.
6. **Compare and record judgment.** Use
   `forge/stage4_review/make_comparison_sheet.py --reference <ref.png> --render
   <png> --out <cmp.png> --json`, then LOOK at the images. Use
   `forge/stage4_review/append_review.py` with pass, fidelity, action, summary,
   `--render-screenshot <Blender PNG>`, comparison image, feature/layer scores and
   `--in-place`. The screenshot field accepts the PNG; it does not require a
   browser. Whole-object similarity does not prove the requested edit succeeded.
   Diagnose the cause using the original camera-first correction order below;
   correct one group at a time,
   export/assemble/render again, sync with `orchestrate_passes.py sync`, and run
   `forge/next.py` again. Camera corrections improve observation and projection
   matching; placement corrections still change the edited part, not the host.
7. **Finish the turn.** A pass requires actual evidence, not file existence. Run
   `check_part_coverage.py` for the constructed part where applicable; verify
   source preservation and physical removal separately on the assembled output.
   Save full `output/turnNN.glb`, notes and review evidence before proceeding to
   the next instruction. Do not generate an entire chain without per-turn review.

Material work retains img2threejs's `analyze_texture.py`, `extract_pbr_evidence.py`
and material review tools as applicable. Read `grimoire/build/threejs_texture_reference.md`.
Supplied image crops and deterministic texture processing are permitted; generated
image models are not. If reference projection is used, follow the skill's camera
matching and de-lighting/UV rules. Initialize from the supplied camera; record
any fitted review-camera changes separately from the immutable evaluation camera. Do not modify the
source's unrelated textures. A missing required channel is unevaluated, not pass;
the six-channel evidence contract below is required for constructed-part review.
A clickable/explodable whole-object factory is not required for static GLB editing.

## GT Blender rendering bridge

Executable: `/gs/fs/tga-koike-shanda4/yurh/blender-4.2.18-linux-x64/blender`
Script: `/gs/fs/tga-koike-shanda4/yurh/blender_kit/scripts/render.py`

Invoke `<executable> -b -noaudio -P <script> -- --manifest <jobs.jsonl>` with
`CUDA_VISIBLE_DEVICES` set as assigned. For a fixed-view review job, use:
`scene="mesh"`, absolute `mesh`, `material="file_embedded"`, `normalize="none"`,
`source_frame="y_up"`, `frames=1`, `res=420`, `samples=32`, absolute `out_dir`.
Copy `frame_center`, `frame_diag`, `start_az`, `elevation`, `distance` unchanged from
`ref/camera.json`'s `frame`. Keep GT lighting defaults and inspect `f0000.png`.
These parameters define the fixed comparison/evaluation job only. Review-camera
jobs may reframe, orbit, zoom and change the look-at center as described below.
Save their parameters and images separately; do not overwrite ref/camera.json. Blender PNGs
feed the existing forge diagnostic/comparison/review tools directly. Use native
agent image reading for judgment. Do not install/search for a browser or build an
alternative rasterizer. Do not modify renderer or forge code during a trial.

## Required evidence: six passes, semantic mapping, multi-view and meshes

Upstream status: the GLB-mediated v2 fidelity track requires all six passes once
that track is selected; semantic-ID absence blocks per-region comparison claims.
The construction workflow also requires off-axis/turntable, attachment and
self-intersection evidence. Here retain these checks for add/replace/retexture;
remove remains the lightweight physical-deletion route. Do not run independent
whole-object reconstruction merely to collect evidence.

Use `forge/stage4_review/capture_blender_edit.py` as the authorized capture bridge:

```text
<Blender executable> -b -P <skill-root>/forge/stage4_review/capture_blender_edit.py --
  --job <absolute single-job.json> --regions <absolute regions.json>
```

The single job uses the same fields as the GT renderer manifest. The adapter calls
the unchanged GT renderer, retains embedded materials and camera settings, and
adds compositor outputs; it does not construct or modify source geometry.
Author a semantic region map from the text/image and model inspection:
`{"regions":[{"id":"barrel","index":1,"objects":["barrel_body","barrel_hoop"]}]}`.
Names must match imported mesh objects; every mesh needs an explicit mapping.
Several objects can share a region. Indices must be unique positive integers.
The adapter fails on unmapped or missing objects. An ID is not proof of meaning:
verify that its named region really covers the intended part. Existing known
regions should keep their IDs across before/after captures. Do not fabricate
human/anatomical labels for anonymous components.

For every accepted construction pass's reference/match view and required diagnostic
views, capture the saved assembled candidate with this bridge. It writes:
- `f0000.png`: normal GT-renderer beauty image for existing PNG review tools.
- `channels/0001.exr`: beauty, alpha-silhouette, semantic-id, depth, normal and
  roughness-material-id, at the SAME camera and model state. The last channel is
  explicitly the MATERIAL INDEX option, not a measured roughness value. Raw
  normals are Blender world-space Z-up; raw depth uses Blender scene units.
- `regions.json`: region/object and material-index mapping.
- `meshes.json`: evaluated world-space vertices and triangle indices converted
  back to source Y-up, compatible with `self_intersection.py`. This replaces the
  browser mesh export transport, not its geometric evidence requirement.
- `evidence.json`: renderer/model hashes, camera job, channel encodings, file hashes
  and truthful `authority=blender_kit`. Never label these as browser captures.

Use the existing `diagnose_render.py`, comparison-sheet and `append_review.py`
loop on the PNGs. Run `self_intersection.py` on constructed meshes (retain the
full export as provenance); do not repair unrelated pre-existing host defects.
Use real measured world-space anchors for `attachment_anchor.py`; geometry export
alone does not establish anchor correctness. Retain `turntable_gate.py` with
0/90/180/270 captures and `diagnose_render_multi_angle.py` on applicable non-planar
parts. Review the added part both as geometry and in the assembled scene.
Missing, stale or malformed required evidence blocks acceptance; record errors
as unevaluated/partial, not pass. A successful capture is not a successful gate.

The agent receives target RGB only. Never load hidden GT geometry/passes to create
paired target evidence. Six output channels support self-checks and comparisons
against the agent's own prior model. They do not supply unavailable target depth,
normals or semantic labels. Upstream `compare_region_passes.py` requires genuine
paired captures and a browser-v2 manifest: do not feed this Blender receipt into
it or fake a compatible authority. Mark paired target-channel comparison
`not_applicable: target RGB only`; still perform RGB/visual/geometry checks and
collect the required output passes. If actual paired reference passes are later
explicitly supplied, their channel encodings and renderer must first be matched.

## Camera iteration: the original img2threejs feedback loop

Use `grimoire/feedback/render_capture.md` and
`grimoire/review/self_correction.md` for camera matching, viewpoint selection and
review decisions. Retain their camera-iteration behavior; only the image capture
backend changes from browser screenshots to Blender PNGs. Review cameras are
editable, not locked to the benchmark camera.

Start with the supplied camera as a known match-view initialization. Before
judging geometry, inspect projection, framing, apparent scale, occlusion and
view direction. If the review is too close/far, poorly framed or from the wrong
angle, choose `refine-code` for the camera first, render again and reassess.
Use the skill's match-view/reference framing guidance and camera-pose fitting
when needed; do not force a known correct supplied camera to fit an arbitrary
occupancy target. A camera change is recorded evidence, not a geometry repair.

Retain the correction order `camera → silhouette → face → clothing → accessory
→ materials → lighting`, omitting only categories not present in the edited part.
Installation errors are corrected in the corresponding geometry/accessory step.
Select front, side, rear, top, three-quarter and close-up views freely; orbit,
zoom and retarget to expose the shape, attachment face, scale, symmetry, contact
and occluded geometry. For non-planar parts retain the original multi-angle and
turntable checks. Inspect both the isolated constructed part when helpful and
its installation in the full current scene; an isolated view cannot prove placement.
After each correction recapture the relevant views, run the applicable existing
forge diagnostics, write `append_review.py` evidence and sync/next state normally.
Camera corrections participate in the same correction history and budget; they
are not an unbounded separate search. Additional views have no unseen GT labels.

Maintain named camera jobs, their exact parameters and image hashes per pass.
A crop comparison uses the identical crop on reference and render; a changed
camera/view is not directly pixel-comparable to the unchanged target image.
Return to the supplied fixed comparison camera after geometry/placement changes
and before accepting a constructed turn. This independently checks that improvement
persists in the benchmark view. Final scoring always uses the untouched supplied
camera; neither fitted review cameras nor close-ups replace it.

Use the same renderer with different manifest camera fields for review views:
`start_az` / `elevation` control orbit, `distance` controls viewing distance and
`frame_center` / `frame_diag` control the review framing. Keep `normalize=none`
and source coordinates unchanged. Use actual supported renderer options for any
other camera parameter; do not silently modify render.py. Store jobs under
`work/turnNN/pass-name/cameras/<view-name>.jsonl` and images under matching
view directories. Blender remains the image source for the original img2threejs
render → diagnose → compare → refine → recapture loop.

## Bounded correction and chain outcome

Keep img2threejs's default limits: three corrections per pass, six per constructed
part; honor earlier plateau/error stops. A stop ends that part's construction
attempt, not permission to bypass a gate. In an unattended benchmark, record
`partial` and the unmet gates; do not ask for user input or claim `done`. Save the
best valid assembled candidate, or retain the previous valid state if no candidate
is safe to serialize; explicitly record that fallback. Continue the next turn
from that saved state. If no valid current model exists, mark remaining turns
`skipped` with the dependency reason. Do not restart the state to reset its budget.
Keep failed attempts and replay provenance. If revising an earlier turn, replay
and revalidate dependent turns; never leave stale outputs/renders downstream.

Keep actual command timestamps and notes per turn; host harness execution/usage
records are authoritative. Unknown usage stays unknown. Final output: one line
per turn (done/partial/skipped with reason), followed by written GLB paths.
