import csv

from util import *

class Grid:
    def __init__(self):
        self.costs = [[[0 for j in range(N_CLUSTERS)] for i in range(N_CLUSTERS)] for t in range(N_PERIODS)]
        self.times = [[[0 for j in range(N_CLUSTERS)] for i in range(N_CLUSTERS)] for t in range(N_PERIODS)]

        input("To do: stochastic travel times")

        with open("data/distances.csv", "r") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                period = int(row["period"])
                start = int(row["start"])
                end = int(row["end"])
                distance = float(row["distance"])
                time = float(row["time"])

                cost = (distance*COST_PER_MILE) + (time*RESERVATION)
                self.costs[period][start][end] = cost
                self.times[period][start][end] = time

    def get_travel_time(self,start, end, period):
        return self.times[period][start][end]
    
    def get_travel_cost(self,start, end, period):
        return self.costs[period][start][end]
    
    def get_prepaid_cost(self, _class, start, end, period):
        return self.costs[period][start][end] + self.costs[period][end][_class] - self.costs[period][start][_class]
