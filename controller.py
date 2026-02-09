from util import *

class Controller:
    def __init__(self):
        pass

    def get_price(self, period, _class, start_cluster, end_cluster, fare, driver_ct, time, waiting_time):
        # this is in dollars.
        if (fare/100) > 100:
            print(f"fare: {fare/100}")
            raise Exception("stop, invalid fare.")
        return fare/100

    def get_subsidy(self, period, _class, start, end):
        return 0

    def report_event(self, cluster, time, driver_ct):
        pass

    def reset(self, t):
        pass

class MethodController:
    def __init__(self, alpha, grid):
        self.alpha = alpha
        self.last_t = [0 for i in range(N_CLUSTERS)]
        self.grid = grid
        self.last_tax = [0 for i in range(N_CLUSTERS)]

        self.beta = 0.9

    def get_price(self, period, _class, start_cluster, end_cluster, fare, driver_ct, time, waiting_time):
        total_opt = (fare/100) - self.last_tax[start_cluster]*RESERVATION
        profit_max = waiting_time + self.grid.get_travel_cost(_class, end_cluster, period) - self.grid.get_travel_cost(_class, start_cluster, period)

        return (1-self.alpha)*total_opt + self.alpha*profit_max

    def get_subsidy(self, period, _class, start, end):
        return self.alpha * self.grid.get_prepaid_cost(_class, start, end, period)

    def report_event(self, cluster, time, driver_ct):
        tax = ((time-self.last_t[cluster]) * (driver_ct**2))
        self.last_tax[cluster] = (1-self.beta)*tax + (self.beta*self.last_tax[cluster])

        self.last_t[cluster] = time

    def reset(self, t):
        self.last_t = [t for i in range(N_CLUSTERS)]
