"""
Configuration file for plot styling and parameters.
Ensures consistent formatting across all plots for IEEE paper submission.
"""

import matplotlib.pyplot as plt
from matplotlib import rcParams

# Font configuration
FONT_FAMILY = 'Times New Roman'
FONT_SIZE_TITLE = 10
FONT_SIZE_LABEL = 9
FONT_SIZE_TICK = 8
FONT_SIZE_LEGEND = 8

# Figure size for IEEE single column (3.5 inches) with 3 subplots
# Using height that accommodates 1 row of 3 plots
FIGURE_WIDTH_INCHES = 7.16 / 2 # IEEE double column width
FIGURE_HEIGHT_INCHES = 2.5  # Compact height for 1 row

# Line widths
LINE_WIDTH_MEAN = 1.5
LINE_WIDTH_INDIVIDUAL = 0.6

# Transparency
ALPHA_CI = 0.25
ALPHA_INDIVIDUAL = 0.2

# Colors
COLOR_SIMULATION = '#1f77b4'  # Blue
COLOR_MEASURED = '#d62728'     # Red

# Grid
GRID_ALPHA = 0.3
GRID_LINESTYLE = '-'
GRID_LINEWIDTH = 0.5

# Legend
LEGEND_FRAMEON = True
LEGEND_FRAMEALPHA = 0.9
LEGEND_EDGECOLOR = 'black'
LEGEND_FACECOLOR = 'white'

# DPI for saving
DPI_SAVE = 300

# Layout
SUBPLOT_LEFT = 0.08
SUBPLOT_RIGHT = 0.98
SUBPLOT_TOP = 0.92
SUBPLOT_BOTTOM = 0.15
SUBPLOT_WSPACE = 0.25
SUBPLOT_HSPACE = 0.35

# LaTeX text rendering (default). Disable with --no-latex to use matplotlib's
# built-in mathtext instead, which needs no TeX installation.
USE_LATEX = True


def add_latex_argument(parser):
    """Register the --no-latex flag on an argparse parser."""
    parser.add_argument(
        "--no-latex",
        dest="latex",
        action="store_false",
        help="Render text with matplotlib mathtext instead of LaTeX (no TeX install needed)",
    )


def set_use_latex(enabled):
    """Select LaTeX or mathtext rendering for subsequent configure_plot_style() calls."""
    global USE_LATEX
    USE_LATEX = enabled


def label(text):
    """Adapt LaTeX-only escapes (\\%, \\#, \\&) when LaTeX rendering is disabled."""
    if USE_LATEX:
        return text
    for escaped in (r"\%", r"\#", r"\&"):
        text = text.replace(escaped, escaped[1:])
    return text


def configure_plot_style():
    """
    Configure matplotlib to use Times New Roman with Type 1 fonts.
    Must be called before creating any plots.
    """
    # Use Type 1 fonts (PostScript) instead of Type 3
    rcParams['pdf.fonttype'] = 42  # TrueType
    rcParams['ps.fonttype'] = 42   # TrueType
    
    # Note: For true Type 1 fonts, you may need to use:
    # rcParams['pdf.fonttype'] = 42
    # and ensure Times New Roman is installed as a Type 1 font
    
    # Font settings
    rcParams['font.family'] = 'serif'
    rcParams['font.serif'] = [FONT_FAMILY, 'STIXGeneral']  # STIX is bundled and Times-like
    rcParams['font.size'] = FONT_SIZE_TICK
    
    # Text settings - LaTeX rendering unless disabled via --no-latex
    rcParams['text.usetex'] = USE_LATEX
    if USE_LATEX:
        rcParams['text.latex.preamble'] = r'\usepackage{amsmath} \usepackage{amssymb} \usepackage{newtxtext} \usepackage{newtxmath}'
    
    # Math text settings - use STIX fonts to match Times Roman
    rcParams['mathtext.fontset'] = 'stix'  # STIX fonts match Times for math
    rcParams['mathtext.rm'] = 'Times New Roman'
    rcParams['mathtext.it'] = 'Times New Roman:italic'
    rcParams['mathtext.bf'] = 'Times New Roman:bold'
    
    # Axes settings
    rcParams['axes.titlesize'] = FONT_SIZE_TITLE
    rcParams['axes.labelsize'] = FONT_SIZE_LABEL
    rcParams['axes.linewidth'] = 0.8
    
    # Tick settings
    rcParams['xtick.labelsize'] = FONT_SIZE_TICK
    rcParams['ytick.labelsize'] = FONT_SIZE_TICK
    rcParams['xtick.major.width'] = 0.8
    rcParams['ytick.major.width'] = 0.8
    
    # Legend settings
    rcParams['legend.fontsize'] = FONT_SIZE_LEGEND
    rcParams['legend.frameon'] = LEGEND_FRAMEON
    rcParams['legend.framealpha'] = LEGEND_FRAMEALPHA
    rcParams['legend.edgecolor'] = LEGEND_EDGECOLOR
    rcParams['legend.facecolor'] = LEGEND_FACECOLOR
    
    # Grid settings
    rcParams['grid.alpha'] = GRID_ALPHA
    rcParams['grid.linestyle'] = GRID_LINESTYLE
    rcParams['grid.linewidth'] = GRID_LINEWIDTH
    
    # Figure settings
    rcParams['figure.dpi'] = 100  # Display DPI
    rcParams['savefig.dpi'] = DPI_SAVE
    rcParams['savefig.bbox'] = 'tight'
    rcParams['savefig.pad_inches'] = 0.05
