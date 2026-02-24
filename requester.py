import random
import math
import csv

from util import *

class Requester:
    def __init__(self, epoch):
        self.epoch_hour = epoch.hour
        self.rates = [[0.0 for _ in range(N_CLUSTERS)] for _ in range(N_PERIODS)]
        self.total_period_rates = [0.0 for _ in range(N_PERIODS)]

        with open("data/service_rates_alt.csv") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                period = int(row["period"])
                cluster = int(row["start"])
                rate = float(row["service_rate"])
                self.rates[period][cluster] = rate
                self.total_period_rates[period] += rate

        # Load precomputed fare tables: (period, start) -> cents
        self._net_rewards = {}
        with open("data/net_rewards.csv") as csvfile:
            for row in csv.DictReader(csvfile):
                self._net_rewards[(int(row["period"]), int(row["start"]))] = int(float(row["reward"]) * 100)

        self._gross_rewards = {}
        with open("data/gross_rewards.csv") as csvfile:
            for row in csv.DictReader(csvfile):
                self._gross_rewards[(int(row["period"]), int(row["start"]))] = int(float(row["reward"]) * 100)

        # Load destination distribution from trip probabilities
        _prob_rows = {}  # (period, start) -> {end: prob}
        with open("data/trip_probabilities.csv") as csvfile:
            for row in csv.DictReader(csvfile):
                key = (int(row["period"]), int(row["start"]))
                _prob_rows.setdefault(key, {})[int(row["end"])] = float(row["probability"])

        self._dest_ends = {}    # (period, start) -> [end_cluster, ...]
        self._dest_probs = {}   # (period, start) -> [prob, ...]
        for key, end_probs in _prob_rows.items():
            ends, probs = zip(*end_probs.items())
            self._dest_ends[key] = list(ends)
            self._dest_probs[key] = list(probs)

    def _sample_start(self, period):
        prob = random.random()
        acc = 0.0
        norm = self.total_period_rates[period]
        for cluster in range(N_CLUSTERS):
            acc += self.rates[period][cluster] / norm
            if acc >= prob:
                return cluster
        return N_CLUSTERS - 1

    def get_request_poisson(self, start_t):
        period = get_period(start_t + self.epoch_hour)
        rate = self.total_period_rates[period]
        delta_t = -math.log(random.random()) / rate
        end_t = start_t + delta_t

        start_cluster = self._sample_start(period)

        # sample destination from trip probability distribution
        dest_key = (period, start_cluster)
        if dest_key in self._dest_ends:
            end_cluster = random.choices(self._dest_ends[dest_key], self._dest_probs[dest_key])[0]
        else:
            end_cluster = random.randrange(N_CLUSTERS)

        # look up precomputed fares for (period, start)
        fare_key = (period, start_cluster)
        net_fare = self._net_rewards.get(fare_key, 1000)
        gross_fare = self._gross_rewards.get(fare_key, 1500)
        travel_time = 0.5

        req = Request(end_t, start_cluster, end_cluster, period, net_fare, gross_fare, travel_time)
        return (end_t, "r", req)
