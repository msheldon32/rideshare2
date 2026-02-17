from util import *

class Controller:
    def __init__(self):
        pass

    def get_price(self, period, _class, start_cluster, end_cluster, fare, driver_ct, time, waiting_time):
        # this is in dollars.
        #if (fare/100) > 100:
        #    print(f"fare: {fare/100}")
        #    raise Exception("stop, invalid fare.")
        return fare/100

    def get_subsidy(self, period, _class, start, end):
        return 0

    def report_event(self, cluster, time, driver_ct, event_type):
        pass

    def reset(self, t):
        pass

    def get_tax(self, cluster):
        return 0

class FixedController:
    def __init__(self, ptg):
        self.ptg = ptg

    def get_price(self, period, _class, start_cluster, end_cluster, fare, driver_ct, time, waiting_time):
        # this is in dollars.
        #if (fare/100) > 100:
        #    print(f"fare: {fare/100}")
        #    raise Exception("stop, invalid fare.")
        return (1-self.ptg)*(fare/100)

    def get_subsidy(self, period, _class, start, end):
        return 0

    def report_event(self, cluster, time, driver_ct, event_type):
        pass

    def reset(self, t):
        pass

    def get_tax(self, cluster):
        return 0

class MethodController:
    def __init__(self, alpha, grid):
        self.alpha = alpha
        self.last_t = [0 for i in range(N_CLUSTERS)]
        self.grid = grid
        self.last_tax = [0 for i in range(N_CLUSTERS)]

        self.beta = 0.95

        self.last_event_type = ["departure" for i in range(N_CLUSTERS)]
        self.last_length = [0 for i in range(N_CLUSTERS)]

    def get_price(self, period, _class, start_cluster, end_cluster, fare, driver_ct, time, waiting_time):
        total_opt = (fare/100) - self.last_tax[start_cluster]*RESERVATION
        profit_max = waiting_time*RESERVATION + self.grid.get_travel_cost(_class, end_cluster, period) - self.grid.get_travel_cost(_class, start_cluster, period)

        total_opt = min(max(total_opt, profit_max), fare/100)

        return (1-self.alpha)*total_opt + self.alpha*profit_max

    def get_subsidy(self, period, _class, start, end):
        return self.alpha * self.grid.get_prepaid_cost(_class, start, end, period)

    def report_event(self, cluster, time, driver_ct, event_type):
        #if event_type == "departure":
        #    self.last_t[cluster] = time
        #    return
        if self.last_event_type[cluster] == "arrival":
            Qminus = self.last_length[cluster]
            tax = ((time-self.last_t[cluster]) * (Qminus**2))
            self.last_tax[cluster] = (1-self.beta)*tax + (self.beta*self.last_tax[cluster])

        #print(f"setting tax to: {tax}")
        #print(f"smoothed tax: {self.last_tax[cluster]}")
        #print(f"time between events: {time-self.last_t[cluster]}")
        #print(f"driver_ct: {driver_ct}")
        if event_type == "arrival":
            self.last_t[cluster] = time
        #input("continue")

        self.last_event_type[cluster] = event_type
        self.last_length[cluster] = driver_ct

    def reset(self, t):
        self.last_t = [t for i in range(N_CLUSTERS)]

    def get_tax(self, cluster):
        return self.last_tax[cluster]

class BufferController:
    def __init__(self, grid):
        self.grid = grid

        self.last_t = [0 for i in range(N_CLUSTERS)]
        self.last_tax = [0 for i in range(N_CLUSTERS)]
        self.tax_buffer = [0 for i in range(N_CLUSTERS)]

        self.last_event_type = ["departure" for i in range(N_CLUSTERS)]
        self.last_length = [0 for i in range(N_CLUSTERS)]

    def get_price(self, period, _class, start_cluster, end_cluster, fare, driver_ct, time, waiting_time):
        # here we are accumulating the buffer to use on later jobs if it exceeds the estimated cost.
        #   this guarantees profitability without losing the right EV

        total_opt = (fare/100) - self.last_tax[start_cluster]*RESERVATION
        profit_max = waiting_time*RESERVATION + self.grid.get_travel_cost(_class, end_cluster, period) - self.grid.get_travel_cost(_class, start_cluster, period)

        price = max(total_opt, 0)

        self.tax_buffer[start_cluster] += price - total_opt
        excess = min((price)/2, self.tax_buffer[start_cluster])
        
        self.tax_buffer[start_cluster] -= excess
        price -= excess
        
        return price

    def get_subsidy(self, period, _class, start, end):
        return 0

    def report_event(self, cluster, time, driver_ct, event_type):
        #if event_type == "departure":
        #    self.last_t[cluster] = time
        #    return
        if self.last_event_type[cluster] == "arrival":
            Qminus = self.last_length[cluster]
            tax = ((time-self.last_t[cluster]) * (Qminus**2))
            self.last_tax[cluster] = tax

        #print(f"setting tax to: {tax}")
        #print(f"smoothed tax: {self.last_tax[cluster]}")
        #print(f"time between events: {time-self.last_t[cluster]}")
        #print(f"driver_ct: {driver_ct}")
        if event_type == "arrival":
            self.last_t[cluster] = time
        #input("continue")

        self.last_event_type[cluster] = event_type
        self.last_length[cluster] = driver_ct

    def reset(self, t):
        self.last_t = [t for i in range(N_CLUSTERS)]

    def get_tax(self, cluster):
        return self.last_tax[cluster]

class SmoothedController:
    def __init__(self, alpha, grid):
        # control variate scheme for smoothing
        self.alpha = alpha
        self.last_t = [0 for i in range(N_CLUSTERS)]
        
        self.grid = grid
        self.last_tax = [0 for i in range(N_CLUSTERS)]
        self.q_estimate = [0 for i in range(N_CLUSTERS)]

        self.beta = 0.9

        self.last_event_type = ["departure" for i in range(N_CLUSTERS)]
        self.last_length = [0 for i in range(N_CLUSTERS)]

    def get_price(self, period, _class, start_cluster, end_cluster, fare, driver_ct, time, waiting_time):
        total_opt = (fare/100) - self.last_tax[start_cluster]*RESERVATION
        profit_max = waiting_time*RESERVATION + self.grid.get_travel_cost(_class, end_cluster, period) - self.grid.get_travel_cost(_class, start_cluster, period)

        total_opt = min(max(total_opt, profit_max), fare/100)

        return (1-self.alpha)*total_opt + self.alpha*profit_max

    def get_subsidy(self, period, _class, start, end):
        return self.alpha * self.grid.get_prepaid_cost(_class, start, end, period)

    def report_event(self, cluster, time, driver_ct, event_type):
        #if event_type == "departure":
        #    self.last_t[cluster] = time
        #    return
        if self.last_event_type[cluster] == "arrival":
            Qminus = self.last_length[cluster]
            Qsquared_est = (Qminus - self.q_estimate[cluster])**2 + (self.q_estimate[cluster])**2
            tax = (time-self.last_t[cluster]) * Qsquared_est
            self.last_tax[cluster] = tax

            self.q_estimate[cluster] = (1-self.beta)*self.last_length[cluster] + self.beta*self.q_estimate[cluster]


        #print(f"setting tax to: {tax}")
        #print(f"smoothed tax: {self.last_tax[cluster]}")
        #print(f"time between events: {time-self.last_t[cluster]}")
        #print(f"driver_ct: {driver_ct}")
        if event_type == "arrival":
            self.last_t[cluster] = time
        #input("continue")

        self.last_event_type[cluster] = event_type
        self.last_length[cluster] = driver_ct

    def reset(self, t):
        self.last_t = [t for i in range(N_CLUSTERS)]

    def get_tax(self, cluster):
        return self.last_tax[cluster]
