import argparse
import csv
import os

import numpy as np

import trip_reqs
import simulator as sim_module

FIELDNAMES = [
    "controller_type", "alpha", "ptg", "seed",
    "total_reward", "profit", "total_revenue",
    "total_trips", "total_requests",
    "total_waiting_cost", "total_travel_cost", "total_exit_cost", "total_subsidy",
]

ALL_SEEDS = [x for x in range(1,51)]
ALPHAS = [round(x, 2) for x in np.linspace(0.0, 1.0, 5)]   # [0.0, 0.25, 0.5, 0.75, 1.0]
PTGS  = [round(x, 2) for x in np.linspace(0.1, 0.5, 5)]    # [0.1, 0.2, 0.3, 0.4, 0.5]


def build_configs(seeds):
    configs = []
    for seed in seeds:
        configs.append({"controller_type": "baseline", "alpha": 0.0, "ptg": 0.0, "seed": seed})
        for ptg in PTGS:
            configs.append({"controller_type": "fixed", "alpha": 0.0, "ptg": ptg, "seed": seed})
        for alpha in ALPHAS:
            configs.append({"controller_type": "method",   "alpha": alpha, "ptg": 0.0, "seed": seed})
            configs.append({"controller_type": "smoothed", "alpha": alpha, "ptg": 0.0, "seed": seed})
    return configs


def config_key(cfg):
    return (cfg["controller_type"], cfg["alpha"], cfg["ptg"])


def results_file(seed):
    return f"results/experiment_results_seed{seed}.csv"


def load_completed(path):
    done = set()
    if not os.path.exists(path):
        return done
    with open(path) as f:
        for row in csv.DictReader(f):
            done.add((row["controller_type"], float(row["alpha"]), float(row["ptg"])))
    return done


def run_experiment(reqs, epoch, exit_probs, cfg, use_empirical=True):
    s = sim_module.Simulator(
        reqs, 16, 16, 8, epoch, exit_probs,
        seed=cfg["seed"],
        controller_type=cfg["controller_type"],
        alpha=cfg["alpha"],
        ptg=cfg["ptg"],
        use_empirical=use_empirical,
    )
    while not s.is_stopped():
        s.step()
    obs = s.observer
    return {
        **cfg,
        "total_reward":       obs.total_reward,
        "profit":             obs.profit,
        "total_revenue":      obs.total_revenue,
        "total_trips":        obs.total_trips,
        "total_requests":     obs.total_requests,
        "total_waiting_cost": obs.total_waiting_cost,
        "total_travel_cost":  obs.total_travel_cost,
        "total_exit_cost":    obs.total_exit_cost,
        "total_subsidy":      obs.total_subsidy,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-seed", type=int, default=min(ALL_SEEDS))
    parser.add_argument("--end-seed",   type=int, default=max(ALL_SEEDS))
    args = parser.parse_args()

    seeds = [s for s in ALL_SEEDS if args.start_seed <= s <= args.end_seed]
    if not seeds:
        raise ValueError(f"No seeds in range [{args.start_seed}, {args.end_seed}]. Available: {ALL_SEEDS}")

    print(f"Running seeds: {seeds}")

    reqs, epoch = trip_reqs.get_trip_requests()
    exit_probs = sim_module.get_exit_probs()

    os.makedirs("results", exist_ok=True)

    for seed in seeds:
        out_file = results_file(seed)
        configs = build_configs([seed])
        completed = load_completed(out_file)
        remaining = [c for c in configs if config_key(c) not in completed]

        write_header = not os.path.exists(out_file)
        print(f"\n=== Seed {seed}: {len(completed)} done, {len(remaining)} remaining → {out_file} ===")

        with open(out_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            if write_header:
                writer.writeheader()

            for i, cfg in enumerate(remaining):
                print(f"\n  [{i+1}/{len(configs)}] {cfg}")
                result = run_experiment(reqs, epoch, exit_probs, cfg)
                writer.writerow(result)
                f.flush()
                print(f"  -> total_reward={result['total_reward']:.0f}  profit={result['profit']:.0f}  trips={result['total_trips']}")

    print("\nDone.")
