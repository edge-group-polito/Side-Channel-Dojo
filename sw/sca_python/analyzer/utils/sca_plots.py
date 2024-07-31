from bokeh.plotting import figure, show
from bokeh.io import output_notebook
from bokeh.models import CrosshairTool
import numpy as np
import matplotlib.pyplot as plt
import holoviews as hv
from holoviews.operation.datashader import datashade, shade, dynspread, rasterize
from holoviews.operation import decimate
import matplotlib.cm as cm

class sca_plot:
    
    def __init__(self):
        pass
       
    def byte_to_color(self, idx):
          cmap = cm.get_cmap('cividis')  # Colormap with 40 colors
          return cmap(idx / 40.0)

    def power_traces_overlapped(self, resolution, traces, start=0, finish=None):
        """Plot overlapped power traces."""
        if finish is None:
            finish = len(traces)

        fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[18,12])

        xticks_samples = range(len(traces[0]))
        xfocus_window = xticks_samples[start:finish]
        xtick_us = [x*resolution*1E6 for x in xfocus_window]

        plt.title("40 captured power traces overlapped")
        ax1.set_xlabel("Time (us)")
        ax1.set_ylabel("Voltage (mV)")

        for i in range(40):
            ax1.plot(xfocus_window, (traces[i][start:finish]*1000), color=self.byte_to_color(i), alpha=0.5)
    
        return plt
        #plt.show()
        # Ensure the Figures directory exists
        #os.makedirs("Figures", exist_ok=True)
        #plt.savefig("Figures/power_traces_overlapped.png")
        #plt.close(fig)

#def snr_plot():

#def snr_vs_traces_plot():

#def correlation_plot():

