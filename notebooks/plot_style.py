from pathlib import Path
import matplotlib as mpl
import matplotlib.pyplot as plt

SINGLE_COL = (3.50, 2.45)
SINGLE_COL_TALL = (3.50, 3.15)
DOUBLE_COL = (7.16, 2.85)
DOUBLE_COL_TALL = (7.16, 4.25)
THREE_PANEL = (7.16, 2.75)
THREE_PANEL_TALL = (7.16, 3.35)

CLASS_ORDER = ["enterprise", "premium", "freemium"]

CLASS_LABELS = {
    "enterprise": "Enterprise",
    "premium": "Premium",
    "freemium": "Freemium",
}

SCHEDULER_LABELS = {
    "round_robin": "Round Robin",
    "least_loaded": "Least Loaded",
    "plb_nclass": "N-class PLB",
    "global_target_repair_neutral": "Target-repair v1",
    "global_target_repair_target_only": "Target-repair v2",
    "global_target_repair_target_only_init_4_2_2": "Target-repair v2, init 4-2-2",
    "global_target_repair_nomixed": "Target-repair v3",
    "global_target_repair_v4": "Target-repair v4",
    "global_target_repair_nomixed_balance": "No-Mixed + Balance",
    "global_target_repair_v2_nomixed_init_4_2_2": "v2 no-Mixed, init 4-2-2",
}

SCHEDULER_STYLE = {
    "round_robin": {
        "color": "#000000",
        "linestyle": "-",
        "marker": "o",
        "linewidth": 1.35,
        "markersize": 3.0,
    },
    "least_loaded": {
        "color": "#7F7F7F",
        "linestyle": "--",
        "marker": "s",
        "linewidth": 1.25,
        "markersize": 3.0,
    },
    "plb_nclass": {
        "color": "#0072B2",
        "linestyle": "-",
        "marker": "o",
        "linewidth": 1.45,
        "markersize": 3.2,
    },
    "global_target_repair_neutral": {
        "color": "#E69F00",
        "linestyle": "--",
        "marker": "v",
        "linewidth": 1.35,
        "markersize": 3.2,
    },
    "global_target_repair_target_only": {
        "color": "#009E73",
        "linestyle": "-",
        "marker": "s",
        "linewidth": 1.50,
        "markersize": 3.2,
    },
    "global_target_repair_target_only_init_4_2_2": {
        "color": "#56B4E9",
        "linestyle": "--",
        "marker": "P",
        "linewidth": 1.45,
        "markersize": 3.2,
    },
    "global_target_repair_nomixed": {
        "color": "#D55E00",
        "linestyle": "-.",
        "marker": "^",
        "linewidth": 1.45,
        "markersize": 3.2,
    },
    "global_target_repair_v4": {
        "color": "#CC79A7",
        "linestyle": ":",
        "marker": "D",
        "linewidth": 1.55,
        "markersize": 3.2,
    },
    "global_target_repair_nomixed_balance": {
        "color": "#F0E442",
        "linestyle": "--",
        "marker": "X",
        "linewidth": 1.40,
        "markersize": 3.2,
    },
    "global_target_repair_v2_nomixed_init_4_2_2": {
        "color": "#332288",
        "linestyle": ":",
        "marker": "d",
        "linewidth": 1.50,
        "markersize": 3.2,
    },
}

CLASS_STYLE = {
    "enterprise": {
        "color": "#0072B2",
        "linestyle": "-",
        "marker": "o",
        "linewidth": 1.45,
        "markersize": 3.2,
    },
    "premium": {
        "color": "#E69F00",
        "linestyle": "--",
        "marker": "s",
        "linewidth": 1.45,
        "markersize": 3.2,
    },
    "freemium": {
        "color": "#009E73",
        "linestyle": "-.",
        "marker": "^",
        "linewidth": 1.45,
        "markersize": 3.2,
    },
}


def apply_paper_style():
    mpl.rcParams.update({
        "figure.dpi": 120,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "font.family": "serif",
        "font.size": 8.0,
        "axes.titlesize": 8.0,
        "axes.labelsize": 8.0,
        "xtick.labelsize": 7.0,
        "ytick.labelsize": 7.0,
        "legend.fontsize": 7.0,
        "axes.linewidth": 0.7,
        "lines.linewidth": 1.4,
        "grid.linewidth": 0.45,
        "grid.alpha": 0.25,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 3.0,
        "ytick.major.size": 3.0,
        "legend.frameon": False,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def scheduler_label(name):
    if name.startswith("static_"):
        return "Static " + name.removeprefix("static_").replace("_", "-")
    return SCHEDULER_LABELS.get(name, name)


def scheduler_style(name):
    if name.startswith("static_"):
        return {
            "color": "#999999",
            "linestyle": ":",
            "marker": None,
            "linewidth": 1.0,
        }
    return dict(SCHEDULER_STYLE.get(name, {
        "linestyle": "-",
        "marker": "o",
        "linewidth": 1.3,
        "markersize": 3.0,
    }))


def save_figure(fig, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
