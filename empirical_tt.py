from util import *

import math
import random

class EmpiricalTravel:
    def __init__(self, grid, trip_reqs):
        self.travel_times = [[[[] for j in range(N_CLUSTERS)] for i in range(N_CLUSTERS)] for j in range(N_PERIODS)]
        self.grid = grid

        for req in trip_reqs:
            if not math.isnan(req.travel_time):
                self.travel_times[req.period][req.start_cluster][req.end_cluster].append(req.travel_time)

    def get_sample(self, period, start, end):
        if len(self.travel_times[period][start][end]) == 0 or True:
            return self.grid.get_travel_time(start, end, period)
        return random.choice(self.travel_times[period][start][end])
