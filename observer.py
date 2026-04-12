import csv

from util import *

class Observer:
    def __init__(self):
        self.total_requests = 0
        self.profit = 0
        self.total_reward = 0
        self.total_trips = 0
        self.total_waiting_cost = 0
        self.total_travel_cost = 0
        self.total_revenue = 0
        self.total_subsidy = 0
        self.total_exit_cost = 0

        self.reward_by_period = [0.0 for _ in range(N_PERIODS)]
        self.profit_by_period = [0.0 for _ in range(N_PERIODS)]

        self.trips_in_cluster = [[0 for i in range(N_CLUSTERS)] for j in range(N_PERIODS)]

    def observe_request(self, request, remuneration, admitted):
        self.total_requests += 1
        if admitted:
            self.total_trips += 1

            self.trips_in_cluster[request.period][request.start_cluster] += 1

    def observe_reward(self, total_reward, profit, period):
        self.total_reward += total_reward
        self.profit += profit
        self.reward_by_period[period] += total_reward
        self.profit_by_period[period] += profit

    def reset(self):
        self.total_requests = 0
        self.profit = 0
        self.total_reward = 0
        self.total_trips = 0
        self.total_waiting_cost = 0
        self.total_travel_cost = 0
        self.total_revenue = 0
        self.total_subsidy = 0
        self.total_exit_cost = 0
        self.reward_by_period = [0.0 for _ in range(N_PERIODS)]
        self.profit_by_period = [0.0 for _ in range(N_PERIODS)]
        self.trips_in_cluster = [[0 for i in range(N_CLUSTERS)] for j in range(N_PERIODS)]

    def save_trip_counts(self, fname):
        with open(fname, "w") as f:
            writer = csv.writer(f)
            writer.writerow(["period", "cluster", "total_trips"])
            for period in range(N_PERIODS):
                for cluster in range(N_CLUSTERS):
                    writer.writerow([period, cluster, self.trips_in_cluster[period][cluster]])
