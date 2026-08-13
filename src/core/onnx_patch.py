"""
ONNX Runtime Environment & Thread Affinity Fix
Prevents ONNX Runtime pthread_setaffinity_np (env.cc:228 Error 22: Invalid argument)
on containerized/multi-core/NUMA systems when running PyMuPDF4LLM or layout models.
"""
import os
import sys

def apply_onnx_affinity_patch():
    """Globally configures environment variables and patches ONNX Runtime to disable thread affinity pinning."""
    # 1. Environment variables for ONNX Runtime C++ engine
    os.environ["ORT_DISABLE_THREAD_AFFINITY"] = "1"
    os.environ["ONNXRUNTIME_DISABLE_THREAD_AFFINITY"] = "1"
    os.environ["ORT_DISABLE_CPU_AFFINITY"] = "1"
    os.environ["ORT_SESSION_THREAD_POOL_SIZE"] = "4"
    os.environ["ORT_LOGGING_LEVEL"] = "4"
    os.environ["ONNXRUNTIME_LOG_LEVEL"] = "4"
    os.environ.setdefault("ORT_INTRA_OP_NUM_THREADS", "4")
    os.environ.setdefault("ORT_INTER_OP_NUM_THREADS", "4")
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
    os.environ.setdefault("MKL_NUM_THREADS", "4")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "4")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "4")

    # 2. ONNX Runtime Python API Global Patch
    try:
        import onnxruntime as ort
        try:
            ort.set_default_logger_severity(4)
        except Exception:
            pass

        # Monkeypatch InferenceSession to explicitly force intra_op_num_threads > 0.
        # When intra_op_num_threads is explicitly set (e.g. 4 or 1), ONNX Runtime's ThreadMain
        # skips pthread_setaffinity_np core affinity pinning completely (env.cc:228).
        if not getattr(ort, "_affinity_patched", False):
            _orig_init = ort.InferenceSession.__init__

            def _patched_init(self, path_or_bytes, sess_options=None, provider_options=None, providers=None, **kwargs):
                if sess_options is None:
                    sess_options = ort.SessionOptions()
                if getattr(sess_options, "intra_op_num_threads", 0) == 0:
                    sess_options.intra_op_num_threads = int(os.environ.get("ORT_INTRA_OP_NUM_THREADS", "4"))
                if getattr(sess_options, "inter_op_num_threads", 0) == 0:
                    sess_options.inter_op_num_threads = int(os.environ.get("ORT_INTER_OP_NUM_THREADS", "4"))
                sess_options.log_severity_level = 4
                return _orig_init(self, path_or_bytes, sess_options=sess_options, provider_options=provider_options, providers=providers, **kwargs)

            ort.InferenceSession.__init__ = _patched_init
            ort._affinity_patched = True
    except ImportError:
        pass

# Automatically execute when module is imported
apply_onnx_affinity_patch()
