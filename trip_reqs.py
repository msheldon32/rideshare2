import csv

from datetime import datetime
from dataclasses import dataclass

from grid import Grid

from util import *

def get_trip_requests():
    _grid = Grid()
    out_reqs = []
    with open("data/requests_with_clusters.csv") as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            t = datetime.fromisoformat(row["started_on"])
            start = int(row["start_cluster"])
            end = int(row["end_cluster"])

            period = get_period(t.hour)

            tip = float(row["tip"]) if len(row["tip"]) > 0 else 0

            if len(row["total_fare"]) == 0:
                continue

            total_fare = float(row["total_fare"]) + tip - BOOKING_FEE - _grid.get_travel_cost(start, end, period)

            total_fare = int(total_fare*100)

            out_reqs.append([t, start, end, period, total_fare])
            
    out_reqs.sort()

    epoch = out_reqs[0][0]

    out_reqs = [
            Request((r[0] - epoch).total_seconds()/(3600), r[1], r[2], r[3], r[4]) for r in out_reqs
            ]

    return out_reqs

