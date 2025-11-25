import numpy as np

class IncrementalStatsMath:
    def __init__(self):
        self.n = 0
        self.meanX = 0
        self.meanY = 0
        self.M2_X = 0
        self.M2_Y = 0
        self.C = 0
    
    def add_data(self, new_data_X, new_data_Y):
        """Aggiunge nuovi dati X (lista di liste) e Y (lista semplice) e aggiorna i calcoli."""
        for dataX, dataY in zip(new_data_X,new_data_Y):
            self.n += 1
            deltaX = dataX - self.meanX
            deltaY = dataY - self.meanY
            self.meanX += deltaX / self.n
            self.meanY += deltaY / self.n
            delta2X = dataX - self.meanX
            delta2Y = dataY - self.meanY
            self.M2_X += deltaX * delta2X
            self.M2_Y += deltaY * delta2Y
            self.C += deltaX * delta2Y
            
    def mean_X(self):
        """"Calcola la media di X"""
        return self.meanX
    
    def mean_Y(self):
        """"Calcola la media di Y"""
        return self.meanY
    
    def std_dev_X(self):
        """Calcola la deviazione standard attuale di X."""
        if self.n == 0:
            return float('nan')
        return np.sqrt(self.M2_X / (self.n - 1))
    
    def std_dev_Y(self):
        """Calcola la deviazione standard attuale di Y."""
        if self.n == 0:
            return float('nan')
        return np.sqrt(self.M2_Y / (self.n - 1))
    
    def covariance(self):
        """Calcola la covarianza attuale tra X e Y."""
        if self.n == 0:
            return float('nan')
        return self.C / (self.n - 1)
