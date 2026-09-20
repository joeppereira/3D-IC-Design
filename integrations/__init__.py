"""3DIC-X <-> EDA interchange layer.

Emit standard artifacts from the physics-AI environment, read vendor results
back, and publish the error band between them.  See
reports/eda_vendor_integration_spec.md.
"""
from .base import HOOK_REGISTRY, VendorHook, HookResult, Finding  # noqa: F401
from .canonical import DesignRecord, load_design                  # noqa: F401
