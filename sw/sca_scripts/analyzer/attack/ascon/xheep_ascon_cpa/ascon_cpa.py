import os
import numpy as np

try:
    import cupy as cp
except Exception:
    cp = None


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def _cupy_is_available():
    if cp is None:
        return False
    try:
        return cp.cuda.runtime.getDeviceCount() > 0
    except Exception:
        return False


def get_cpa_backend_name(requested=None):
    """
    Return the backend selected for CPA kernels.

    Priority:
      1. requested argument if not None
      2. environment variable ASCON_CPA_DEVICE
      3. auto

    Values:
      cpu | gpu | auto
    """
    if requested is None:
        requested = os.environ.get("ASCON_CPA_DEVICE", "auto")

    requested = str(requested).strip().lower()
    gpu_ready = _cupy_is_available()

    if requested == "gpu":
        return "gpu" if gpu_ready else "cpu"

    if requested == "cpu":
        return "cpu"

    if requested == "auto":
        return "gpu" if gpu_ready else "cpu"

    raise ValueError("CPA backend must be one of: cpu, gpu, auto")


def cpa_uses_gpu(requested=None):
    return get_cpa_backend_name(requested) == "gpu"


def _get_xp(backend=None):
    return cp if get_cpa_backend_name(backend) == "gpu" else np


def _to_numpy(array):
    if cp is not None and isinstance(array, cp.ndarray):
        return cp.asnumpy(array)
    return np.asarray(array)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_cpa_inputs(traces, hypothetical_values):
    """
    Normalize CPA inputs and run shared sanity checks once.

    traces:
        shape (N, M)

    hypothetical_values:
        shape (N, K)
    """
    T = np.asarray(traces)
    H = np.asarray(hypothetical_values)

    if T.ndim != 2 or H.ndim != 2:
        raise ValueError("CPA inputs must be 2D arrays")

    N, M = T.shape
    N_h, K = H.shape

    if N != N_h:
        raise ValueError(
            f"Mismatch: traces have {N} rows, hypothetical_values have {N_h} rows"
        )

    if np.any(~np.isfinite(T)):
        raise ValueError("Non-finite values detected in traces")

    if np.any(~np.isfinite(H)):
        raise ValueError("Non-finite values detected in hypothetical_values")

    return T, H, N, M, K


# ---------------------------------------------------------------------------
# Standard full-matrix CPA
# ---------------------------------------------------------------------------

def ascon_cpa(traces, hypothetical_values):
    """
    Compute Pearson correlation between traces and hypothetical leakages.

    traces:
        shape (N, M)

    hypothetical_values:
        shape (N, K)

    Returns:
        R_matrix shape (K, M)
    """
    return ascon_cpa_fast(traces, hypothetical_values)


def ascon_cpa_fast(traces, hypothetical_values, eps=1e-12, backend=None):
    """
    Compute Pearson correlation between traces and hypothetical leakages.

    This version expects traces and hypothetical_values fully available in memory.

    traces:
        shape (N, M)

    hypothetical_values:
        shape (N, K)

    Returns:
        R_matrix shape (K, M)
    """
    T, H, N, M, K = _validate_cpa_inputs(traces, hypothetical_values)

    xp = _get_xp(backend)

    if xp is cp:
        T = cp.asarray(T)
        H = cp.asarray(H)

    sum_t = xp.sum(T, axis=0, dtype=xp.float64)                  # (M,)
    sum_h = xp.sum(H, axis=0, dtype=xp.float64)                  # (K,)

    sumsq_t = xp.einsum("nm,nm->m", T, T, dtype=xp.float64)      # (M,)
    sumsq_h = xp.einsum("nk,nk->k", H, H, dtype=xp.float64)      # (K,)

    sum_ht = H.T @ T                                             # (K, M)

    return ascon_cpa_finalize_from_sums(
        n_used=N,
        sum_t=sum_t,
        sumsq_t=sumsq_t,
        sum_h=sum_h,
        sumsq_h=sumsq_h,
        sum_ht=sum_ht,
        eps=eps,
        backend=backend,
    )


# ---------------------------------------------------------------------------
# Chunked / streaming CPA
# ---------------------------------------------------------------------------

def ascon_cpa_init_accumulators(n_samples, n_hypotheses, backend=None):
    """
    Initialize streaming CPA accumulators.

    Parameters
    ----------
    n_samples:
        Number of time samples per trace.

    n_hypotheses:
        Number of key hypotheses.

    backend:
        cpu | gpu | auto | None

    Returns
    -------
    dict of accumulators.

    The accumulators are enough to compute Pearson correlation later:

        sum_t    : sum of trace samples over traces
        sumsq_t  : sum of trace samples squared over traces
        sum_h    : sum of hypothetical leakage values
        sumsq_h  : sum of hypothetical leakage values squared
        sum_ht   : sum of H * T products
        n_used   : number of accumulated traces
    """
    xp = _get_xp(backend)

    acc = {
        "backend": get_cpa_backend_name(backend),
        "n_used": 0,
        "sum_t": xp.zeros(n_samples, dtype=xp.float64),
        "sumsq_t": xp.zeros(n_samples, dtype=xp.float64),
        "sum_h": xp.zeros(n_hypotheses, dtype=xp.float64),
        "sumsq_h": xp.zeros(n_hypotheses, dtype=xp.float64),
        "sum_ht": xp.zeros((n_hypotheses, n_samples), dtype=xp.float64),
    }

    return acc


def ascon_cpa_update_accumulators(acc, traces_chunk, hypothetical_chunk):
    """
    Update streaming CPA accumulators with one trace chunk.

    Parameters
    ----------
    acc:
        accumulator dict from ascon_cpa_init_accumulators()

    traces_chunk:
        shape (B, M)

    hypothetical_chunk:
        shape (B, K)

    Notes
    -----
    This function does not keep the chunk after updating the accumulators.
    This is the key function for large HDF5 files.
    """
    backend = acc["backend"]
    xp = cp if backend == "gpu" else np

    T = xp.asarray(traces_chunk)
    H = xp.asarray(hypothetical_chunk)

    if T.ndim != 2 or H.ndim != 2:
        raise ValueError("CPA chunks must be 2D arrays")

    B, M = T.shape
    B_h, K = H.shape

    if B != B_h:
        raise ValueError(
            f"Chunk mismatch: traces have {B} rows, hypothetical values have {B_h} rows"
        )

    if acc["sum_t"].shape[0] != M:
        raise ValueError(
            f"n_samples mismatch: accumulator has {acc['sum_t'].shape[0]}, chunk has {M}"
        )

    if acc["sum_h"].shape[0] != K:
        raise ValueError(
            f"n_hypotheses mismatch: accumulator has {acc['sum_h'].shape[0]}, chunk has {K}"
        )

    acc["sum_t"] += xp.sum(T, axis=0, dtype=xp.float64)
    acc["sum_h"] += xp.sum(H, axis=0, dtype=xp.float64)

    acc["sumsq_t"] += xp.einsum("nm,nm->m", T, T, dtype=xp.float64)
    acc["sumsq_h"] += xp.einsum("nk,nk->k", H, H, dtype=xp.float64)

    acc["sum_ht"] += H.T @ T

    acc["n_used"] += int(B)

    return acc


def ascon_cpa_finalize_from_sums(
    n_used,
    sum_t,
    sumsq_t,
    sum_h,
    sumsq_h,
    sum_ht,
    eps=1e-12,
    backend=None,
):
    """
    Finalize Pearson correlation from accumulated sums.

    Returns:
        R matrix, shape (K, M)
    """
    xp = cp if (cp is not None and isinstance(sum_ht, cp.ndarray)) else np

    n_used = float(n_used)

    cov = sum_ht - xp.outer(sum_h, sum_t) / n_used

    var_h = sumsq_h - (sum_h * sum_h) / n_used
    var_t = sumsq_t - (sum_t * sum_t) / n_used

    xp.maximum(var_h, 0.0, out=var_h)
    xp.maximum(var_t, 0.0, out=var_t)

    denom = xp.sqrt(var_h + eps)[:, None] * xp.sqrt(var_t + eps)[None, :]

    # NumPy supports the ufunc ``where=`` keyword here, but some CuPy versions
    # reject it. The denominator includes eps, so the raw division is finite;
    # invalid zero-variance rows/columns are cleared just below.
    R = cov / denom

    zero_h = var_h <= eps
    zero_t = var_t <= eps

    if bool(_to_numpy(xp.any(zero_h))):
        R[zero_h, :] = 0.0

    if bool(_to_numpy(xp.any(zero_t))):
        R[:, zero_t] = 0.0

    return _to_numpy(R)


def ascon_cpa_finalize_accumulators(acc, eps=1e-12):
    """
    Finalize full CPA correlation matrix from a streaming accumulator.

    Returns:
        R matrix, shape (K, M)
    """
    if acc["n_used"] <= 1:
        raise ValueError("Need at least two traces to compute CPA correlation")

    return ascon_cpa_finalize_from_sums(
        n_used=acc["n_used"],
        sum_t=acc["sum_t"],
        sumsq_t=acc["sumsq_t"],
        sum_h=acc["sum_h"],
        sumsq_h=acc["sumsq_h"],
        sum_ht=acc["sum_ht"],
        eps=eps,
    )


def ascon_cpa_finalize_corrmax_accumulators(
    acc,
    eps=1e-12,
    return_argmax_samples=False,
):
    """
    Finalize streaming CPA and return only max absolute correlation per hypothesis.

    This is usually better for attacks because it avoids returning/storing
    the full R matrix if you only need:

        max_t |corr(hypothesis, trace_sample_t)|

    Returns
    -------
    max_abs_corr:
        shape (K,)

    optionally:
    argmax_samples:
        shape (K,)
    """
    R = ascon_cpa_finalize_accumulators(acc, eps=eps)

    abs_R = np.abs(R)
    argmax_samples = np.argmax(abs_R, axis=1)
    max_abs_corr = abs_R[np.arange(abs_R.shape[0]), argmax_samples]

    if return_argmax_samples:
        return max_abs_corr, argmax_samples

    return max_abs_corr


# ---------------------------------------------------------------------------
# Progressive CPA, full-memory version
# ---------------------------------------------------------------------------

def ascon_cpa_progressive(
    traces,
    hypothetical_values,
    trace_counts,
    eps=1e-12,
    return_argmax_samples=False,
    backend=None,
):
    """
    Progressive CPA summary over multiple trace counts.

    This function still expects full traces and hypothetical_values in memory.

    Parameters
    ----------
    traces:
        shape (N, M)

    hypothetical_values:
        shape (N, K)

    trace_counts:
        strictly increasing trace counts.

    Returns
    -------
    max_abs_corr:
        shape (len(trace_counts), K)

    optionally:
    argmax_samples:
        shape (len(trace_counts), K)
    """
    T, H, N, M, K = _validate_cpa_inputs(traces, hypothetical_values)

    xp = _get_xp(backend)

    if xp is cp:
        T = cp.asarray(T)
        H = cp.asarray(H)

    counts = np.asarray(list(trace_counts), dtype=np.int64)

    if counts.ndim != 1 or counts.size == 0:
        raise ValueError("trace_counts must be a non-empty 1D iterable")

    if np.any(counts <= 1) or np.any(counts > N):
        raise ValueError("trace_counts entries must satisfy 1 < count <= number of traces")

    if np.any(np.diff(counts) <= 0):
        raise ValueError("trace_counts must be strictly increasing")

    sum_t = xp.zeros(M, dtype=xp.float64)
    sum_h = xp.zeros(K, dtype=xp.float64)
    sumsq_t = xp.zeros(M, dtype=xp.float64)
    sumsq_h = xp.zeros(K, dtype=xp.float64)
    sum_ht = xp.zeros((K, M), dtype=xp.float64)

    max_abs_corr = xp.empty((counts.size, K), dtype=xp.float64)
    argmax_samples = xp.empty((counts.size, K), dtype=xp.int64) if return_argmax_samples else None

    start = 0

    for step_idx, stop in enumerate(counts):
        Tb = T[start:stop]
        Hb = H[start:stop]

        sum_t += xp.sum(Tb, axis=0, dtype=xp.float64)
        sum_h += xp.sum(Hb, axis=0, dtype=xp.float64)

        sumsq_t += xp.einsum("nm,nm->m", Tb, Tb, dtype=xp.float64)
        sumsq_h += xp.einsum("nk,nk->k", Hb, Hb, dtype=xp.float64)

        sum_ht += Hb.T @ Tb

        n_used = float(stop)

        cov = sum_ht - xp.outer(sum_h, sum_t) / n_used

        var_h = sumsq_h - (sum_h * sum_h) / n_used
        var_t = sumsq_t - (sum_t * sum_t) / n_used

        xp.maximum(var_h, 0.0, out=var_h)
        xp.maximum(var_t, 0.0, out=var_t)

        denom = xp.sqrt(var_h + eps)[:, None] * xp.sqrt(var_t + eps)[None, :]

        R = cov / denom

        zero_h = var_h <= eps
        zero_t = var_t <= eps

        if bool(_to_numpy(xp.any(zero_h))):
            R[zero_h, :] = 0.0

        if bool(_to_numpy(xp.any(zero_t))):
            R[:, zero_t] = 0.0

        abs_R = xp.abs(R)
        argmax_idx = xp.argmax(abs_R, axis=1)

        max_abs_corr[step_idx] = abs_R[xp.arange(K), argmax_idx]

        if return_argmax_samples:
            argmax_samples[step_idx] = argmax_idx

        start = stop

    if return_argmax_samples:
        return _to_numpy(max_abs_corr), _to_numpy(argmax_samples)

    return _to_numpy(max_abs_corr)
