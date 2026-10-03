"""compute_validation_metrics must report "unavailable" honestly instead of inventing numbers."""

from __future__ import annotations

import numpy as np

from app.validation.metrics import compute_validation_metrics


def test_not_georeferenced_is_unavailable(tmp_path):
    result = compute_validation_metrics(np.zeros((8, 8), dtype=np.float32), None, tmp_path, dsm_is_metric=True)
    assert result.status == "unavailable"
    assert result.rmse is None and result.mae is None and result.correlation is None
