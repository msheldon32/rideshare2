import csv
import os

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

    def reward_printout(self, t):
        if t < 100:
            return
        print(f"Net profit: {self.profit/t:.2f}")
        print(f"Total reward: {self.total_reward/t:.2f}")
        print(f"Total revenue: {self.total_revenue/t:.2f}")
        print(f"Total waiting_cost: {self.total_waiting_cost/t:.2f}")
        print(f"Total travel cost: {self.total_travel_cost/t:.2f}")
        print(f"total trips: {self.total_trips/t:.2f}")
        print(f"total requests: {self.total_requests/t:.2f}")
        print(f"total exit cost: {self.total_exit_cost/t:.2f}")
        print("Reward by period:")
        for p in range(len(self.reward_by_period)):
            print(f"  period {p}: reward={self.reward_by_period[p]/t:.2f}, profit={self.profit_by_period[p]/t:.2f}")

    def write_reward_csv(self, fname, t):
        header = ["t", "net_profit", "total_reward", "total_revenue",
                  "total_waiting_cost", "total_travel_cost", "total_trips",
                  "total_requests", "total_exit_cost"]
        for p in range(N_PERIODS):
            header.append(f"reward_period_{p}")
            header.append(f"profit_period_{p}")

        row = [t, self.profit, self.total_reward, self.total_revenue,
               self.total_waiting_cost, self.total_travel_cost, self.total_trips,
               self.total_requests, self.total_exit_cost]
        for p in range(N_PERIODS):
            row.append(self.reward_by_period[p])
            row.append(self.profit_by_period[p])

        write_header = not os.path.exists(fname)
        with open(fname, "a") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(header)
            writer.writerow(row)
