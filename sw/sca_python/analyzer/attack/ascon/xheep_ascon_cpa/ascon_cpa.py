# This file contains the correlation power analysis funcitions for 
# the attack on the ASCON cipher.

import numpy as np

def ascon_cpa(traces, hypothetical_values, debug=False):
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
    R_matrix = np.zeros((traces.shape[1], hypothetical_values.shape[1]))

    # Loop over each sample in the traces and over each key hypothesis
    for sample_index in range(traces.shape[1]):
        for hypothesis_index in range(hypothetical_values.shape[1]):
            # Compute the correlation between the traces and the hypothetical values
            R_matrix[sample_index, hypothesis_index] = np.corrcoef(traces[:, sample_index], 
                                                                    hypothetical_values[:, hypothesis_index])[0, 1]

    if debug:
        print("Correlation matrix R dimensions: ", R_matrix.shape)

    return R_matrix
