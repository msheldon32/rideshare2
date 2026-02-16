import argparse
import csv
import os
import statistics

import trip_reqs
import simulator


def run_single(controller_type, alpha, seed, ptg):
    """Run one simulation and return a metrics dict."""
    reqs, epoch = trip_reqs.get_trip_requests()
    exit_probs = simulator.get_exit_probs()

    sim = simulator.Simulator(reqs, 16, 16, 8, epoch, exit_probs,
                              controller_type=controller_type, alpha=alpha, seed=seed, ptg=ptg)
    while not sim.is_stopped():
        sim.step()

    obs = sim.observer
    return {
        "seed": seed,
        "controller": controller_type,
        "alpha": alpha,
        "profit": obs.profit,
        "total_reward": obs.total_reward,
        "total_revenue": obs.total_revenue,
        "total_waiting_cost": obs.total_waiting_cost,
        "total_travel_cost": obs.total_travel_cost,
        "total_subsidy": obs.total_subsidy,
        "total_exit_cost": obs.total_exit_cost,
        "total_trips": obs.total_trips,
        "total_requests": obs.total_requests,
    }, obs


def run_experiment(controller_type, alpha, seeds, ptg):
    """Run multiple seeds and return per-run results + summary stats."""
    results = []
    observers = []
    for seed in seeds:
        print(f"=== Running seed={seed} controller={controller_type} alpha={alpha} ===")
        metrics, obs = run_single(controller_type, alpha, seed, ptg)
        results.append(metrics)
        observers.append(obs)
    return results, observers


def save_results(results, observers, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    # Save per-run metrics
    fieldnames = list(results[0].keys())
    with open(os.path.join(output_dir, "runs.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    # Save per-run trip counts
    for i, obs in enumerate(observers):
        obs.save_trip_counts(os.path.join(output_dir, f"trip_counts_seed{results[i]['seed']}.csv"))

    # Save summary with mean/std
    numeric_keys = [k for k in fieldnames if k not in ("seed", "controller", "alpha")]
    summary_fieldnames = ["metric", "mean", "std"]
    with open(os.path.join(output_dir, "summary.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fieldnames)
        writer.writeheader()
        for key in numeric_keys:
            values = [r[key] for r in results]
            row = {
                "metric": key,
                "mean": statistics.mean(values),
                "std": statistics.stdev(values) if len(values) > 1 else 0,
            }
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Run rideshare simulation experiments")
    parser.add_argument("--controller", choices=["baseline", "method", "buffer", "smoothed", "fixed"],
                        default="smoothed")
    parser.add_argument("--alpha", type=float, default=0)
    parser.add_argument("--num-runs", type=int, default=5)
    parser.add_argument("--start-seed", type=int, default=0)
    parser.add_argument("--output-dir", default="results/")
    parser.add_argument("--ptg", type=float, default=0.3)
    args = parser.parse_args()

    seeds = list(range(args.start_seed, args.start_seed + args.num_runs))
    results, observers = run_experiment(args.controller, args.alpha, seeds, args.ptg)

    save_results(results, observers, args.output_dir)

    print(f"\n=== Summary ({len(results)} runs) ===")
    for r in results:
        print(f"  seed={r['seed']}: trips={r['total_trips']} profit={r['profit']:.2f} revenue={r['total_revenue']:.2f}")

    if len(results) > 1:
        trips = [r["total_trips"] for r in results]
        profits = [r["profit"] for r in results]
        print(f"\n  trips:  mean={statistics.mean(trips):.1f}  std={statistics.stdev(trips):.1f}")
        print(f"  profit: mean={statistics.mean(profits):.2f}  std={statistics.stdev(profits):.2f}")

    print(f"\nResults saved to {args.output_dir}")


if __name__ == "__main__":
    main()
