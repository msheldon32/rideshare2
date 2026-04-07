import csv
import os

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

RESULTS_DIR = "results"
VIZ_DIR = "viz"
ALL_SEEDS = list(range(1, 51))

# ── load ──────────────────────────────────────────────────────────────────────

def load_results():
    frames = []
    missing = []
    for seed in ALL_SEEDS:
        path = os.path.join(RESULTS_DIR, f"experiment_results_seed{seed}.csv")
        if not os.path.exists(path):
            missing.append(seed)
            continue
        df = pd.read_csv(path)
        frames.append(df)
    if missing:
        print(f"Skipping {len(missing)} missing seed files: {missing}")
    if not frames:
        raise FileNotFoundError("No result files found.")
    return pd.concat(frames, ignore_index=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def savefig(name):
    os.makedirs(VIZ_DIR, exist_ok=True)
    path = os.path.join(VIZ_DIR, name)
    plt.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  saved {path}")


# ── plots ─────────────────────────────────────────────────────────────────────

def plot_reward_by_controller(df):
    """Box plot of total_reward for each controller type (collapsed over alpha/ptg)."""
    order = ["baseline", "fixed", "method", "smoothed"]
    fig, ax = plt.subplots(figsize=(8, 5))
    sns.boxplot(data=df, x="controller_type", y="total_reward", order=order, ax=ax)
    ax.set_title("Total Reward by Controller Type")
    ax.set_xlabel("Controller")
    ax.set_ylabel("Total Reward")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e3:.0f}k"))
    savefig("reward_by_controller.png")


def plot_alpha_sensitivity(df):
    """Mean ± std of total_reward vs alpha for method and smoothed."""
    sub = df[df["controller_type"].isin(["method", "smoothed"])]
    grouped = sub.groupby(["controller_type", "alpha"])["total_reward"].agg(["mean", "std"]).reset_index()

    fig, ax = plt.subplots(figsize=(8, 5))
    for ct, grp in grouped.groupby("controller_type"):
        ax.errorbar(grp["alpha"], grp["mean"], yerr=grp["std"], marker="o", label=ct, capsize=4)

    ax.set_title("Total Reward vs Alpha")
    ax.set_xlabel("Alpha")
    ax.set_ylabel("Total Reward (mean ± std)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e3:.0f}k"))
    ax.legend()
    savefig("alpha_sensitivity.png")


def plot_ptg_sensitivity(df):
    """Mean ± std of total_reward vs ptg for fixed controller."""
    sub = df[df["controller_type"] == "fixed"]
    grouped = sub.groupby("ptg")["total_reward"].agg(["mean", "std"]).reset_index()

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.errorbar(grouped["ptg"], grouped["mean"], yerr=grouped["std"], marker="o", color="C2", capsize=4)
    ax.set_title("Total Reward vs Platform Take Rate (Fixed Controller)")
    ax.set_xlabel("ptg (platform take fraction of gross fare)")
    ax.set_ylabel("Total Reward (mean ± std)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x/1e3:.0f}k"))
    savefig("ptg_sensitivity.png")


def plot_profit_vs_reward(df):
    """Scatter of profit vs total_reward, coloured by controller type."""
    palette = {"baseline": "C0", "fixed": "C2", "method": "C1", "smoothed": "C3"}
    fig, ax = plt.subplots(figsize=(8, 6))
    for ct, grp in df.groupby("controller_type"):
        ax.scatter(grp["total_reward"], grp["profit"], label=ct,
                   color=palette.get(ct), alpha=0.6, s=30)
    # diagonal reference (profit = total_reward)
    lims = [min(ax.get_xlim()[0], ax.get_ylim()[0]),
            max(ax.get_xlim()[1], ax.get_ylim()[1])]
    ax.plot(lims, lims, "k--", linewidth=0.8, label="profit = reward")
    ax.set_title("Profit vs Total Reward")
    ax.set_xlabel("Total Reward")
    ax.set_ylabel("Profit")
    fmt = mticker.FuncFormatter(lambda x, _: f"{x/1e3:.0f}k")
    ax.xaxis.set_major_formatter(fmt)
    ax.yaxis.set_major_formatter(fmt)
    ax.legend()
    savefig("profit_vs_reward.png")


def plot_trips_by_controller(df):
    """Box plot of total trips served per controller type."""
    order = ["baseline", "fixed", "method", "smoothed"]
    fig, ax = plt.subplots(figsize=(8, 5))
    sns.boxplot(data=df, x="controller_type", y="total_trips", order=order, ax=ax)
    ax.set_title("Total Trips Served by Controller Type")
    ax.set_xlabel("Controller")
    ax.set_ylabel("Total Trips")
    savefig("trips_by_controller.png")


def print_summary(df):
    print("\n=== Summary (mean across seeds) ===")
    cols = ["total_reward", "profit", "total_trips", "total_revenue"]
    print(df.groupby("controller_type")[cols].mean().to_string())
    print()
    print("=== Method: mean by alpha ===")
    print(df[df["controller_type"] == "method"].groupby("alpha")["total_reward"].mean().to_string())
    print()
    print("=== Smoothed: mean by alpha ===")
    print(df[df["controller_type"] == "smoothed"].groupby("alpha")["total_reward"].mean().to_string())
    print()
    print("=== Fixed: mean by ptg ===")
    print(df[df["controller_type"] == "fixed"].groupby("ptg")["total_reward"].mean().to_string())


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    df = load_results()
    print(f"Loaded {len(df)} rows from {df['seed'].nunique()} seeds.")

    print_summary(df)

    print("\nGenerating plots...")
    plot_reward_by_controller(df)
    plot_alpha_sensitivity(df)
    plot_ptg_sensitivity(df)
    plot_profit_vs_reward(df)
    plot_trips_by_controller(df)

    print("Done.")
