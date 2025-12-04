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





#import numpy as np
#
#def ascon_cpa(traces, hypothetical_values):
#    """
#    This function performs the correlation power analysis on the ASCON cipher.
#    It computes the correlation between the traces and the leakage model for each key hypothesis.
#    

#    
#    # Initialize the correlations array (R matrix)
#    R_matrix = np.zeros((hypothetical_values.shape[1], traces.shape[1]), dtype=np.float64)
#
#    # Sanity check for NaN or Inf values in traces and hypothetical values
#    if np.any(np.isnan(traces)):
#        print("[WARN] NaN detected in traces input")
#    if np.any(np.isnan(hypothetical_values)):
#        print("[WARN] NaN detected in hypothetical values input")
#    if np.any(np.isinf(traces)):
#        print("[WARN] Inf detected in traces input")
#    if np.any(np.isinf(hypothetical_values)):
#        print("[WARN] Inf detected in hypothetical values input")
#
#    # Loop over each sample in the traces and over each key hypothesis
#    for hypothesis_index in range(hypothetical_values.shape[1]):
#        if np.std(y) == 0:
#            R_matrix[hypothesis_index, sample_index] = 0.0
#            break  # No need to continue for this hypothesis, all values are constant
#        for sample_index in range(traces.shape[1]):
#            x = traces[:, sample_index]  # all traces at time sample $t$ (a column)
#            y = hypothetical_values[:, hypothesis_index] # predicted leakage across traces for key hypothesis $k$
#            # These checks are performed individually to determine the exact reason for invalid correlation (used for debugging)
#            # Check for NaN separately
#            #if np.any(np.isnan(x)):
#            #    print(f"[WARN] NaN detected in traces at sample index {sample_index}")
#            #    R_matrix[hypothesis_index, sample_index] = 0.0
#            #elif np.any(np.isnan(y)):
#            #    print(f"[WARN] NaN detected in hypothetical values for hypothesis index {hypothesis_index}")
#            #    R_matrix[hypothesis_index, sample_index] = 0.0
#            ## Check for Inf separately
#            #elif np.any(np.isinf(x)):
#            #    R_matrix[hypothesis_index, sample_index] = 0.0
#            #elif np.any(np.isinf(y)):
#            #    R_matrix[hypothesis_index, sample_index] = 0.0
#            # Check for constant input (zero stddev) separately
#            #If all $N$ traces have exactly the same value at that time index, the standard deviation is 0 → correlation is undefined (division by zero), so it stores 0.0.
#            # this time sample is not dependent on the key hypothesis hence the correlation is 0
#            if np.std(x) == 0:
#                R_matrix[hypothesis_index, sample_index] = 0.0
#                print(f"[WARN] Constant value detected in traces at sample index {sample_index}")
#            # if the leakage prediction is constant across traces for that key hypothesis, then the hypothesized value 
#            # is independent of the actual key → correlation is 0
#            else:
#                R_matrix[hypothesis_index, sample_index] = np.corrcoef(x, y)[0, 1]
#
#    return R_matrix
#