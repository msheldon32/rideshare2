import random
import math
import csv

from util import *

class Spawner:
    def __init__(self):
        self.rates = [[[0 for i in range(N_CLUSTERS)] for j in range(N_CLASSES)] for k in range(N_PERIODS)]
        self.total_period_rates = [0 for k in range(N_PERIODS)]
        with open("data/new_arrival_rates.csv") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                period = int(row["period"])
                cluster = int(row["start"])
                rate = float(row["new_arrivals"])
                self.rates[period][cluster][cluster] = rate
                self.total_period_rates[period] += rate

    def get_cluster_class(self, period):
        prob = random.random()
        acc = 0

        tprob = self.total_period_rates[period]

        for _class in range(N_CLASSES):
            for cluster in range(N_CLUSTERS):
                acc += self.rates[period][_class][cluster]/tprob

                if acc >= prob:
                    return (_class, cluster)

    def get_spawn(self, start_t):
        period = get_period(start_t)
        # generate an exponential distribution with total_period_rate
        rate = self.total_period_rates[period]
        delta_t = -math.log(random.random())/rate

        end_t = start_t + delta_t

        _class, cluster = self.get_cluster_class(period)

        return (end_t, "s", Spawn(end_t, cluster, _class))
