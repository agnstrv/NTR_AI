# Case002: refinement following user review, 2026-10-30

Task:DRAFT-artem-009; https://trello.com/c/CB5LIDqR
Author:Codex for Nagornov Artem. Branch:work/nagornov-artem/building-ucx/draft-artem-009-ostrov.
Status:intermediate, not accepted. Local client assets and coordinate-bearing scripts are intentionally excluded from this repository.

User feedback required removal of nonfunctional tiny remnants, windows represented by their wall, merged adjacent body volumes, and column cuts that preserve large building masses. Whole mesh fences were approved and preserved.

The local deterministic refinement removed13 explicit remnants and absorbed6 standalone window panels into walls. Body parts decreased21→19. Twelve filled columns became23 convex pieces (1–3 each) after clipping against protected large masses. All21 whole mesh fence meshes match the baseline exactly. One exposed body plane was corrected toward the source without subdivision.

Saved artifact:158 closed convex UCX objects,2284 triangles against2571 budget; Blender5.0.0. Reopening verified Solid display, preserved3 user reference objects, and absence of removed IDs. A clean numeric replay produced byte-identical geometry JSON. Two separate AI reviewers inspected the same geometry hash:
`db09fe74b8e65336f2727af05296d45e4a1676a1cb0483d237bab59ac95d90ac`.

Column-versus-large-mass positive overlaps:0. Remaining overall overlaps:91 (baseline120). Sampled source misses beyond25cm:4675/36476, maximum2.785473m. Raw reverse failures:74, maximum1.199869m; intentional fence gap filling contributes and requires classification. Body/technical-room reverse sample failures beyond25cm:0. No claim of continuous tolerance, universal2mm gaps, or global minimum part count. Two exterior bands remain deferred to avoid unnecessary fragments.

Next:resolve remaining intersections while preserving large volumes; classify missing coverage; then add functional exterior details. Human acceptance remains required. No Trello message was sent; prepared update: “Case002 feedback applied:158/2284, column–large-mass overlaps0,91 other overlaps remain; deterministic replay and two AI reviews passed for an intermediate artifact. Coverage remains incomplete. Human review pending.”
