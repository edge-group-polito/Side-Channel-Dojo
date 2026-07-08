"""Shared plotting style for ASCON S-box analysis scripts."""

from __future__ import annotations

from pathlib import Path

from matplotlib.colors import LinearSegmentedColormap


SBOX_ORDER_SW = (
    "lut_ascon",
    "lut_bilgin",
    "lut_allouzi",
    "lut_lu_4",
    "lut_lu_5",
    "lut_lu_6",
    "lut_lu_7",
)

SBOX_ORDER_HW = ("hw",) + SBOX_ORDER_SW

SBOX_COLORS = {
    "hw": "#9B2226",
    "lut_ascon": "#005F73",
    "lut_bilgin": "#94D2BD",
    "lut_allouzi": "#AE2012",
    "lut_lu_4": "#CA6702",
    "lut_lu_5": "#EE9B00",
    "lut_lu_6": "#588157",
    "lut_lu_7": "#001219",
}

KEY_COLORS = {
    "k0": "#005F73",
    "k1": "#CA6702",
    "combined": "#AE2012",
    "wrong": "#E9D8A6",
    "muted": "#A9A9A9",
    "text": "#001219",
}

NAVY_CMAP = LinearSegmentedColormap.from_list(
    "ascon_navy",
    ["#f7fbff", "#deebf7", "#9ecae1", "#005F73", "#001219"],
)


def sbox_color(name: str) -> str:
    return SBOX_COLORS.get(str(name), "#000000")


def apply_plot_style(plt) -> None:
    """Apply the plotting defaults used by the ASCON plot notebooks."""
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
            "axes.labelsize": 13,
            "axes.titlesize": 14,
            "xtick.labelsize": 12,
            "ytick.labelsize": 12,
            "figure.titlesize": 16,
            "legend.fontsize": 11,
            "axes.edgecolor": KEY_COLORS["text"],
            "axes.labelcolor": KEY_COLORS["text"],
            "xtick.color": KEY_COLORS["text"],
            "ytick.color": KEY_COLORS["text"],
            "savefig.bbox": "tight",
            "savefig.dpi": 300,
        }
    )


def save_figure(fig, path, dpi: int = 300, tight: bool = True) -> Path:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if tight:
        fig.tight_layout()
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    return out_path
