import csv
import math
from collections import defaultdict
from datetime import datetime

from util import *

DISTANCE_CORRECTION = 1.45

# Median speeds (mph) by period, derived from RideAustin dispatched trips
PERIOD_SPEEDS = {
    0: 22.1,
    1: 35.7,
    2: 21.5,
    3: 22.8,
    4: 21.0,
    5: 17.0,
    6: 18.0,
    7: 19.9,
}


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def _compute_centroids():
    lats = defaultdict(list)
    lons = defaultdict(list)

    with open("data/requests_with_clusters.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row["start_location_lat"]:
                continue
            c = int(row["start_cluster"])
            lats[c].append(float(row["start_location_lat"]))
            lons[c].append(float(row["start_location_long"]))

    centroids = {}
    for c in sorted(lats.keys()):
        centroids[c] = (sum(lats[c]) / len(lats[c]), sum(lons[c]) / len(lons[c]))
    return centroids


class Grid:
    def __init__(self):
        centroids = _compute_centroids()

        self.costs = [[[0.0 for j in range(N_CLUSTERS)] for i in range(N_CLUSTERS)] for t in range(N_PERIODS)]
        self.times = [[[0.0 for j in range(N_CLUSTERS)] for i in range(N_CLUSTERS)] for t in range(N_PERIODS)]
        self.distance_costs = [[[0.0 for j in range(N_CLUSTERS)] for i in range(N_CLUSTERS)] for t in range(N_PERIODS)]

        for period in range(N_PERIODS):
            speed = PERIOD_SPEEDS[period]
            for i in range(N_CLUSTERS):
                for j in range(N_CLUSTERS):
                    dist = haversine_miles(*centroids[i], *centroids[j]) * DISTANCE_CORRECTION
                    time = dist / speed  # hours

                    self.times[period][i][j] = time
                    self.distance_costs[period][i][j] = dist * COST_PER_MILE
                    self.costs[period][i][j] = dist * COST_PER_MILE + time * RESERVATION

    def get_travel_time(self, start, end, period):
        return self.times[period][start][end]

    def get_travel_cost(self, start, end, period):
        return self.costs[period][start][end]

    def get_rebalance_cost(self, start, end, period):
        if start == end:
            return 0
        return self.costs[period][start][end]

    def get_prepaid_cost(self, _class, start, end, period):
        return self.costs[period][start][end] + self.costs[period][end][_class] - self.costs[period][start][_class]
