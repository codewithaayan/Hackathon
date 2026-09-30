import importlib

import pytest


SCIENTIFIC_MODULES = [
    "backend.models.airmodel",
    "backend.models.composite_score",
    "backend.models.exposure",
    "backend.models.flood_model",
    "backend.models.greenmodel",
    "backend.models.heat_model",
    "backend.models.mobile",
    "backend.models.normalize",
    "backend.models.sim",
]


@pytest.mark.parametrize("module_name", SCIENTIFIC_MODULES)
def test_committed_backend_modules_import(module_name):
    """Infrastructure smoke test only; it does not validate scientific methods."""
    assert importlib.import_module(module_name) is not None
