from bokeh.plotting import figure, show
from bokeh.io import output_notebook
from bokeh.models import CrosshairTool
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import holoviews as hv
from holoviews.operation.datashader import datashade, shade, dynspread, rasterize
from holoviews.operation import decimate
import chipwhisperer.analyzer as cwa

class sca_plot:
    
    def __init__(self):
        pass
       
    def byte_to_color(self, idx):
          cmap = cm.get_cmap('cividis')  # Colormap with 40 colors
          return cmap(idx / 40.0)

    def power_traces_overlapped(self, resolution, traces, start=0, finish=None):
        """Plot overlapped power traces with matplotlib.

            resolution: sampling interval in seconds
            traces: list of power traces as numpy arrays
            start: initial sample to plot
            finish: final sample to plot
        
        """
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

    def snr_vs_traces_plot(self, resolution, project, leak_model, start=0, finish=None, db_flag=False):
        """ Plot SNR vs traces with matplotlib.

            resolution: sampling interval in seconds
            traces: list of power traces as numpy arrays
            start: initial sample to plot
            finish: final sample to plot
            db_flag: if True, SNR is in dB. Otherwise, SNR is in linear scale.
            leak_model: leakage model to calculate SNR    

        """
        # Create the figure and subplots
        fig, (ax1, ax2) = plt.subplots(2, 1)  # 2 rows, 1 column
        ax1.grid(axis='both', alpha=0.2)
        ax2.grid(axis='both', alpha=0.2)
        plt.title("Power traces and SNR")

        if finish is None:
            finish = len(project.traces)

        xticks_samples = range(len(project.traces[0]))
        xfocus_window = xticks_samples[start:finish]
        xtick_us = [x*resolution*1E6 for x in xfocus_window]

        # Plot the power traces
        ax1.set_xlabel("Time (us)")
        ax1.set_ylabel("Voltage (mV)")
        for i in range(40):
            ax1.plot(xfocus_window, (project.waves[i][start:finish]*1000), color=self.byte_to_color(i), alpha=0.5)
        ax1.legend()

        ## Plot the SNR
        ax2.set_xlabel("Time (us)")
        ax2.set_ylabel("SNR")
        snr = cwa.calculate_snr(project.traces, leak_model=leak_model, db=db_flag)
        ax2.plot(xtick_us, snr[start:finish], color='orange', alpha=0.5)

        # Adjust layout (optional)
        #plt.tight_layout()
        return plt

        #def correlation_plot():

    def PGE_vs_traces(results, key):
        """
        Plots the PGE trends for all the 16 correct key guesses with matplotlib

            results: the results object from the attack
            key: the correct key
        """
        plot_data = cwa.analyzer_plots(results)
        pges = [plot_data.pge_vs_trace(i) for i,_ in enumerate(key)]
        fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[14,10])
        plt.grid(which='major', axis='both', alpha=0.2)

        x_axis = plot_data.pge_vs_trace(0)[0]
        step = 100
        for i, bnum in enumerate(key):
            plt.plot(pges[i][0], pges[i][1], linewidth=1, label=f"Byte #{i}")
        plt.plot(pges[i][0], [10 for _ in range(len(pges[i][0]))], linewidth=1, linestyle="dashed",  color="black", label=f"max(PGE) < {10}")

        plt.legend(title=f"Known Key", fontsize=12, loc="upper right")
        plt.title("AES - PGE", fontsize=18)
        ax1.set_xticks(range(0, x_axis[-1], step))
        # clip_min_y = 0
        # clip_max_y = 300
        # ax1.set_yticks(list(range(clip_min_y, clip_max_y+1, 10)))
        ax1.set_ylabel('Partial Guessing Entropy (PGE)', fontsize=16)
        ax1.set_xlabel('Traces', fontsize=16)
        return plt

def corr_trend_correctKey():
    """
    Plots the various correlations of both the correct key guesses and the wrong ones
    """
    # 16 subkey
    bnum_it = range(16)

    fig, ax1 = plt.subplots(nrows=1, ncols=1, sharex=True, figsize=[18,12])
    plt.grid(which='major', axis='both', alpha=0.2)

    # Plot correlation trends of wrong key guesses (
    for bnum in bnum_it:
        data = np.array(plot_data.corr_vs_trace(bnum)[1])
        xrangelist = plot_data.corr_vs_trace(bnum)[0]
        wrong_results = data[[i != key for i in range(256)]]
        ax1.plot(xrangelist, np.amax(wrong_results, 0), linewidth=2, linestyle ="dotted", color=byte_to_color(bnum))

    # Plot correct key_guesses on top of wrong ones
    for bnum in bnum_it:
        data = np.array(plot_data.corr_vs_trace(bnum)[1])
        xrangelist = plot_data.corr_vs_trace(bnum)[0]
        key = results.known_key[bnum]
        wrong_results = data[[i != key for i in range(256)]]
        ax1.plot(xrangelist, data[key], linewidth=1, label=f"Byte #{bnum}", color=byte_to_color(bnum))


    ax1.legend(title=f"Known Key", fontsize=12, loc="upper right")
    plt.title(" AES SBOX Freyre 2 - Correlations", fontsize=18)

    step = 200
    ax1.set_xticks(range(0, xrangelist[-1], step))
    ax1.set_ylabel('Correlation', fontsize=16)
    ax1.set_xlabel('Traces', fontsize=16)

    #plt.show()
    plt.savefig("Figures/correlations_Freyre_2.png")
    plt.close(fig)
