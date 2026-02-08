import csv

from util import *

class Observer:
    def __init__(self):
        self.total_requests = 0
        self.profit = 0
        self.total_reward = 0
        self.total_trips = [0]

        self.trips_in_cluster = [[0 for i in range(N_CLUSTERS)] for j in range(N_PERIODS)]
    
    def observe_request(self, request, remuneration, admitted):
        self.total_requests.append(self.total_requests[-1]+1)
        if admitted:
            self.total_trips.append(self.total_trips[-1]+1)

            self.profit.append(self.profit[-1]+((request.net_fare_cents/100)-remuneration))

            self.trips_in_cluster[request.period][request.start_cluster] += 1

    def observe_reward(self, total_reward, profit):
        self.total_reward += total_reward
        self.profit += profit

    def reset(self):
        self.total_requests = 0
        self.profit = 0
        self.total_trips = 0
        self.trips_in_cluster = [[0 for i in range(N_CLUSTERS)] for j in range(N_PERIODS)]

    def save_trip_counts(self, fname):
        with open(fname, "w") as f:
            writer = csv.writer(f)
            writer.writerow(["period", "cluster", "total_trips"])
            for period in range(N_PERIODS):
                for cluster in range(N_CLUSTERS):
                    writer.writerow([period, cluster, self.trips_in_cluster[period][cluster]])
