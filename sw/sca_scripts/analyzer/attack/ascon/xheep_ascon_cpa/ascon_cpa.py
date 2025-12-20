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
