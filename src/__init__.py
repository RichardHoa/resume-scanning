"""
Vietnamese Resume Scanning Package
Initializes environment variables to disable ONNX Runtime thread affinity errors globally.
"""
import os

from src.core.onnx_patch import apply_onnx_affinity_patch

apply_onnx_affinity_patch()
