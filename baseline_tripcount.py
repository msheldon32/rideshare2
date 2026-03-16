import pandas as pd
import csv
from datetime import timedelta

from util import *

if __name__ == "__main__":
    warmup = 2000  # hours to skip from the start

    reqs = pd.read_csv("data/requests_with_clusters.csv")

    reqs["started_on"] = reqs["started_on"].apply(pd.Timestamp)

    epoch = reqs["started_on"].min()
    warmup_cutoff = epoch + timedelta(hours=warmup)

    print(f"epoch: {epoch.hour}")
    print(f"ignoring requests before {warmup_cutoff} (warmup={warmup}h)")

    trip_cts = [[0 for i in range(N_CLUSTERS)] for j in range(N_PERIODS)]
    req_cts = [[0 for i in range(N_CLUSTERS)] for j in range(N_PERIODS)]

    for i, row in reqs.iterrows():
        if row["started_on"] < warmup_cutoff:
            continue
        tip = row["tip"] if not pd.isna(row["tip"]) else 0
        if row["total_fare"] + tip > 100 or row["total_fare"] < 0.01:
            continue
        period = get_period(row["started_on"].hour)
        cluster = row["start_cluster"]
        if row["status"] == "b'DISPATCHED'":
            trip_cts[period][cluster] += 1
        req_cts[period][cluster] += 1

    out_file = f"data/trip_counts_baseline_w{warmup}.csv"
    with open(out_file, "w") as f:
        writer = csv.writer(f)

        writer.writerow(["period", "cluster", "total_trips", "total_reqs"])

        for period in range(N_PERIODS):
            for cluster in range(N_CLUSTERS):
                writer.writerow([period, cluster, trip_cts[period][cluster], req_cts[period][cluster]])

    print(f"written to {out_file}")
