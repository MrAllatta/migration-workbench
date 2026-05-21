"""Shared pure-Python utilities for migration-workbench apps.

This package must never import Django or any app-specific module.
It is a leaf dependency so every app can import it without circularity.
"""