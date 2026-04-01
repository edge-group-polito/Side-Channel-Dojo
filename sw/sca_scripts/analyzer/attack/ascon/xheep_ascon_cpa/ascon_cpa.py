import numpy as np

def ascon_cpa(traces, hypothetical_values):
    """
    Compute Pearson correlation between traces and hypothetical leakages
    for each key hypothesis.
    
    traces:            shape (N, M)  - N traces, M samples per trace
    hypothetical_values: shape (N, K) - N traces, K key hypotheses
    
    Returns:
        R_matrix: shape (K, M), R[k, t] = corr(traces[:, t], hypothetical_values[:, k])
    """

    N, M = traces.shape
    N_h, K = hypothetical_values.shape
    if N != N_h:
        raise ValueError(
            f"Mismatch: traces have {N} rows, hypothetical_values have {N_h} rows"
        )

    # Initialize correlation matrix
    R_matrix = np.zeros((K, M), dtype=np.float64)

    # Global sanity checks
    if np.any(np.isnan(traces)):
        print("[WARN] NaN detected in traces input")
    if np.any(np.isnan(hypothetical_values)):
        print("[WARN] NaN detected in hypothetical values input")
    if np.any(np.isinf(traces)):
        print("[WARN] Inf detected in traces input")
    if np.any(np.isinf(hypothetical_values)):
        print("[WARN] Inf detected in hypothetical values input")

    # Loop over key hypotheses
    for k in range(K):
        y = hypothetical_values[:, k]

        # Per-hypothesis guards
        if np.any(np.isnan(y)) or np.any(np.isinf(y)):
            # leave row k as zeros
            print(f"[WARN] Invalid values in hypothetical_values for hypothesis {k}, skipping.")
            continue

        if np.std(y) == 0:
            # leakage prediction is constant across traces → no information
            # ;eakage prediction independent of this key guess, row k remains zeros
            # print(f"[INFO] Hypothesis {k}: constant leakage (std=0), skipping.")
            continue

        # Loop over time samples
        for t in range(M):
            x = traces[:, t]

            # Per-sample guards for traces
            if np.any(np.isnan(x)) or np.any(np.isinf(x)):
                # correlation stays 0.0
                continue

            if np.std(x) == 0:
                # constant trace sample → correlation undefined / uninformative
                # traces at this time sample does not depend on the key  
                # correlation stays 0.0
                # Optional debug:
                # print(f"[WARN] Constant value detected in traces at sample index {t}")
                continue

            # Safe to compute Pearson correlation
            R_matrix[k, t] = np.corrcoef(x, y)[0, 1]

    return R_matrix


def ascon_cpa_fast(traces, hypothetical_values, eps=1e-12):
    """
    Compute Pearson correlation between traces and hypothetical leakages
    for each key hypothesis (vectorized).

    traces:              shape (N, M)
    hypothetical_values: shape (N, K)

    Returns:
        R_matrix: shape (K, M)
    """
    N, M = traces.shape
    N_h, K = hypothetical_values.shape
    if N != N_h:
        raise ValueError(f"Mismatch: traces have {N} rows, hypothetical_values have {N_h} rows")

    # Convert once (float32 is usually much faster and enough for CPA)
    T = np.asarray(traces)
    H = np.asarray(hypothetical_values)

    # Optional: keep your global sanity checks, but do them ONCE
    if np.any(~np.isfinite(T)):
        raise ValueError("Non-finite values detected in traces")
    if np.any(~np.isfinite(H)):
        raise ValueError("Non-finite values detected in hypothetical_values")

    # Center columns
    Tm = T.mean(axis=0, keepdims=True)      # (1, M)
    Hm = H.mean(axis=0, keepdims=True)      # (1, K)
    Tc = T - Tm                              # (N, M)
    Hc = H - Hm                              # (N, K)

    # Sum of squares (variance numerator) per column
    T_sumsq = np.sum(Tc * Tc, axis=0)        # (M,)
    H_sumsq = np.sum(Hc * Hc, axis=0)        # (K,)

    # Covariance numerator for all pairs (K, M)
    # (Hc.T @ Tc) does: for each hypothesis k and time sample t, sum_i Hc[i,k]*Tc[i,t]
    cov = Hc.T @ Tc                          # (K, M)

    # Denominator: sqrt(H_sumsq[k]) * sqrt(T_sumsq[t])
    denom = np.sqrt(H_sumsq + eps)[:, None] * np.sqrt(T_sumsq + eps)[None, :]

    R = cov / denom

    # If any column had zero variance, correlation is undefined -> set to 0
    # (matches your "skip if std==0" behavior)
    zero_h = H_sumsq <= eps
    zero_t = T_sumsq <= eps
    if np.any(zero_h):
        R[zero_h, :] = 0
    if np.any(zero_t):
        R[:, zero_t] = 0

    return R

#TODO : verificare se effettivamente col binario è piu' rapido. 