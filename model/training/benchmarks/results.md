# DepthWizard / AakashDrishti -- Landscape-Stratified Benchmark

GAMUS test split, 59 tiles sampled (15 per available subset, seed=0).
Landscape subset from GAMUS's own 7-class CLS masks (urban: building frac > 0.2; sparse: building frac < 0.05 and low-veg frac > 0.3; forested: tree frac > 0.4; mixed: everything else). No 'hilly' subset -- GAMUS's AGL height maps normalize away broad terrain relief by construction, so it cannot be recovered without a separate bare-earth DEM (not bundled locally); see this script's docstring.

RMSE and MAE in meters. r = Pearson correlation. 'Aligned' rows fit a per-tile scale+shift (best case, shows how well the model's SHAPE matches truth); the production row uses the exact formula the deployed pipeline runs (app/fusion/edge_aware.py::build_height_field), with no per-tile fitting -- the real number a user would see.

| Config | urban RMSE (n) | sparse RMSE (n) | forested RMSE (n) | mixed RMSE (n) | Mean MAE | Mean r |
|---|---|---|---|---|---|---|
| Zero-shot DA-V2 + per-tile affine fit | 3.83 (15) | 3.13 (15) | 9.07 (15) | 3.66 (14) | 3.93 | 0.346 |
| Fine-tuned DA-V2 + per-tile affine fit | 2.33 (15) | 1.85 (15) | 6.18 (15) | 2.22 (14) | 2.04 | 0.746 |
| Fine-tuned DA-V2, production formula (no per-tile fit) | 2.75 (15) | 2.09 (15) | 8.22 (15) | 2.65 (14) | 2.71 | 0.746 |
