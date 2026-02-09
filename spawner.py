import random
import math
import csv
from datetime import datetime

from util import *

class Spawner:
    def __init__(self, epoch):
        self.rates = [[[0 for i in range(N_CLUSTERS)] for j in range(N_CLASSES)] for k in range(N_PERIODS)]
        #input("5x rates")
        self.total_period_rates = [0 for k in range(N_PERIODS)]
        with open("data/new_arrival_rates.csv") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                period = int(row["period"])
                cluster = int(row["start"])
                rate = float(row["new_arrivals"])
                self.rates[period][cluster][cluster] = rate
                self.total_period_rates[period] += rate

        self.spawn_events = []
        self.next_spawn = 0

        with open("data/spawns.csv") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                dt = datetime.fromisoformat(row["time"])
                t = (dt-epoch).total_seconds()/3600
                t = t - 0.25 # arrive 15 minutes early
                self.spawn_events.append((t, int(row["period"]), int(row["cluster"])))

        #self.spawn_events.sort()



    def get_cluster_class(self, period):
        prob = random.random()
        acc = 0

        norm = self.total_period_rates[period]

        for _class in range(N_CLASSES):
            for cluster in range(N_CLUSTERS):
                acc += self.rates[period][_class][cluster]/norm

                if acc >= prob:
                    return (_class, cluster)
    def reset(self):
        self.next_spawn = 0

    def get_spawn_poisson(self, start_t):
        period = get_period(start_t)
        # generate an exponential distribution with total_period_rate
        rate = self.total_period_rates[period]
        delta_t = -math.log(random.random())/rate

        end_t = start_t + delta_t

        _class, cluster = self.get_cluster_class(period)

        return (end_t, "s", Spawn(end_t, cluster, _class))

    def get_spawn_data(self, start_t):
        if self.next_spawn < len(self.spawn_events):
            spawn_event = self.spawn_events[self.next_spawn]
            self.next_spawn += 1

            t = spawn_event[0]
            cluster = spawn_event[2]

            return (t, "s", Spawn(t, cluster, cluster))

        return (1e10, 0,Spawn(1e10, 0,0))

    def get_spawn(self, start_t):
        return self.get_spawn_data(start_t)

    def get_spawn_event(self, spawn):
        t = spawn[0]
        cluster = spawn[2]

        return (t, "s", Spawn(t, cluster, cluster))
