# This file contains the correlation power analysis funcitions for 
# the attack on the ASCON cipher.

import numpy as np

def ascon_cpa(traces, hypothetical_values):
    """
    This function performs the correlation power analysis on the ASCON cipher.
    It computes the correlation between the traces and the leakage model for each key hypothesis.
    
    Inputs:
        traces (numpy array): The captured traces, shape (N, M) where N is the number of traces 
        and M is the number of samples.

        hypothetical_values (numpy array): The hypothetical values for the linearly diffusion layer output.
        Shape (N, K) where N is the number of traces and K is the number of key hypotheses.

        debug (bool): If True, prints debug information.
        
    Returns:
        correlations (numpy array): The correlation values between the traces and the hypothetical values
        provided by the leakage model. Shape (M, K) where M is the number of samples and K is the number 
        of key hypotheses.
    """
    
    # Initialize the correlations array (R matrix)
    R_matrix = np.zeros((hypothetical_values.shape[1], traces.shape[1]), dtype=np.float64)

    # Loop over each sample in the traces and over each key hypothesis
    for hypothesis_index in range(hypothetical_values.shape[1]):
        for sample_index in range(traces.shape[1]):
            x = traces[:, sample_index]
            y = hypothetical_values[:, hypothesis_index]
            # These checks are performed individually to determine the exact reason for invalid correlation (used for debugging)
            # Check for NaN separately
            if np.any(np.isnan(x)):
                R_matrix[hypothesis_index, sample_index] = 0.0
            elif np.any(np.isnan(y)):
                R_matrix[hypothesis_index, sample_index] = 0.0
            # Check for Inf separately
            elif np.any(np.isinf(x)):
                R_matrix[hypothesis_index, sample_index] = 0.0
            elif np.any(np.isinf(y)):
                R_matrix[hypothesis_index, sample_index] = 0.0
            # Check for constant input (zero stddev) separately
            elif np.std(x) == 0:
                R_matrix[hypothesis_index, sample_index] = 0.0
            elif np.std(y) == 0:
                R_matrix[hypothesis_index, sample_index] = 0.0
            else:
                R_matrix[hypothesis_index, sample_index] = np.corrcoef(x, y)[0, 1]

    return R_matrix
