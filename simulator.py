import pandas as pd

import random
import heapq
import math
import csv

import trip_reqs
import spawner
import controller
import observer
import grid
import empirical_tt
import model_alt
import estimator
import policy
from util import *

class Simulator:
    def __init__(self, requests, n_classes, n_clusters, n_periods, epoch, exit_probs,
                 controller_type="smoothed", alpha=0, seed=None):
        if seed is not None:
            random.seed(seed)

        self.requests = requests
        self.n_classes = n_classes
        self.n_clusters = n_clusters
        self.n_periods = n_periods
        self.exit_probs = exit_probs

        self.epoch = epoch

        self.epoch_hour = self.epoch.hour


        self.grid = grid.Grid()
        self.empirical_tt = empirical_tt.EmpiricalTravel(self.grid, self.requests)

        self.rate_tracker = estimator.RateTracker(n_clusters)

        if controller_type == "baseline":
            self.controller = controller.Controller()
        elif controller_type == "method":
            self.controller = controller.MethodController(alpha, self.grid)
        elif controller_type == "buffer":
            self.controller = controller.BufferController(self.grid)
        elif controller_type == "smoothed":
            self.controller = controller.SmoothedController(alpha, self.grid)
        else:
            raise ValueError(f"Unknown controller type: {controller_type}")

        # one estimator per period
        self.estimators = [estimator.Estimator(self.rate_tracker, self.grid, period, self.controller) for period in range(n_periods)]

        # default policy: always enter the queue at the current location
        default_policy = [([0.0] * i + [1.0] + [0.0] * (n_clusters - i)) for i in range(n_clusters)]
        #self.models = [[model.DriverModel(default_policy, exit_probs[period]) for _class in range(n_classes)] for period in range(n_periods)]

        self.exploration = [[model_alt.Exploration() for _class in range(n_classes)] for period in range(n_periods)]
        self.models = [[model_alt.DriverModel(self.grid, 
                                              period, 
                                              _class, 
                                              self.estimators[period], 
                                              self.exit_probs[period], 
                                              self.exploration[period][_class]) for _class in range(n_classes)] for period in range(n_periods)]

        self.drivers = [[[] for i in range(n_classes)] for j in range(n_clusters)] # contains the time entered for each driver of each class

        self.transiters = [[[0 for k in range(n_classes)] for j in range(n_clusters)] for l in range(n_clusters)]

        self.t = 0
        self.last_policy_update = 0

        self.spawner = spawner.Spawner(epoch)
        self.observer = observer.Observer()

        self.next_events = []#(0, "r", self.requests[0])]
        self.next_req = 1

        for spawn in self.spawner.spawn_events:
            heapq.heappush(self.next_events, self.spawner.get_spawn_event(spawn))

        for req in self.requests:
            heapq.heappush(self.next_events, (req.time, "r", req))

    def update_policies(self):
        for period in range(self.n_periods):
            config = self.estimators[period].get_config(self.exit_probs[period])
            print("-----------------------------------------------")
            print(f"({period}) updating policy")
            print(f"arrival_rates: {config.arrival_rates}")
            print(f"service_rates: {config.service_rates}")

            new_policies = policy.get_policies(config)
            for _class in range(self.n_classes):
                self.models[period][_class] = model.DriverModel(new_policies[_class], self.exit_probs[period])
        self.last_policy_update = self.t

    def is_stopped(self):
        #return self.next_req >= 10000
        return self.next_req == len(self.requests)

    def get_period(self):
        return get_period(self.t + self.epoch_hour)

    def get_queue_lengths(self):
        return [sum(len(self.drivers[cluster][_class]) for _class in range(self.n_classes)) for cluster in range(self.n_clusters)]

    def clean_queue(self, cluster, time):
        old_driver_ct = 0
        period = get_period(time + self.epoch_hour)
        new_driver_ct = 0
        # remove any drivers that have been in the queue for more than 5 hours
        for _class in range(len(self.drivers[cluster])):
            old_driver_ct += len(self.drivers[cluster][_class])
            #expelled_drivers = [x for x in self.drivers[cluster][_class] if (time-x) >= 5]
            #self.drivers[cluster][_class] = [x for x in self.drivers[cluster][_class] if (time-x) < 5]
            #new_driver_ct += len(self.drivers[cluster][_class])

    def process_request(self, request):
        self.clean_queue(request.start_cluster, self.t)
        self.estimators[self.get_period()].observe_service(request.start_cluster, self.t)
        self.estimators[self.get_period()].observe_transition(request.start_cluster, request.end_cluster)

        if self.next_req < len(self.requests):
            #next_request = self.requests[self.next_req]
            #heapq.heappush(self.next_events, (next_request.time, "r", next_request))
            self.next_req += 1

        # check if a driver is available, and find the class if so
        driver_counts = [len(x) for x in self.drivers[request.start_cluster]]
        n_drivers = sum(driver_counts)

        self.controller.report_event(request.start_cluster, request.time, n_drivers, "departure")

        if n_drivers == 0:
            self.observer.observe_request(request, None, False)
            return
        driver_class = random.choices(range(self.n_clusters), driver_counts, k=1)[0]

        # expel a random driver from the queue
        driver_idx = random.randrange(len(self.drivers[request.start_cluster][driver_class]))
        waiting_time = self.t - self.drivers[request.start_cluster][driver_class][driver_idx]
        del self.drivers[request.start_cluster][driver_class][driver_idx]
        self.estimators[self.get_period()].observe_queue_lengths(self.get_queue_lengths())

        self.clean_queue(request.start_cluster, request.time)

        remuneration = self.controller.get_price(request.period, driver_class, request.start_cluster, request.end_cluster, request.net_fare_cents, n_drivers, request.time, waiting_time)

        fare = request.net_fare_cents / 100

        # estimator observations
        self.estimators[self.get_period()].observe_reward(driver_class, request.start_cluster, remuneration)
        self.estimators[self.get_period()].observe_fare(driver_class, request.start_cluster, fare)

        self.observer.observe_reward(fare, fare-remuneration)
        self.observer.total_revenue += fare

        #end_time = request.time + self.grid.get_travel_time(request.start_cluster, request.end_cluster, self.get_period())
        end_time = request.time + self.empirical_tt.get_sample(self.get_period(), request.start_cluster, request.end_cluster)

        #self.transiters[request.start_cluster][request.end_cluster][driver_class] += 1
        arrival = Arrival(end_time, request.start_cluster, request.end_cluster, driver_class)
        heapq.heappush(self.next_events, (end_time, "a", arrival))

        self.observer.observe_request(request, remuneration, True)

    def decide(self, cluster, _class):
        period = self.get_period()
        self.clean_queue(cluster, self.t)
        self.estimators[self.get_period()].clean_rewards(self.t)
        action = self.models[period][_class].decide(cluster, self.t)

        if action == -1:
            # vehicle leaves the system
            print(f"leaving the system.")
            if cluster != _class:
                cost = self.grid.get_travel_cost(cluster, _class, period)
                self.observer.observe_reward(-cost, 0)
                self.observer.total_exit_cost += cost
            return
        if action == cluster:
            self.drivers[cluster][_class].append(self.t)
            driver_counts = [len(x) for x in self.drivers[cluster]]
            n_drivers = sum(driver_counts)
            self.controller.report_event(cluster, self.t, n_drivers, "arrival")
            self.estimators[self.get_period()].observe_queue_lengths(self.get_queue_lengths())
            self.estimators[self.get_period()].observe_arrival(cluster, self.t)
            print(f"chose to enter queue: {cluster}")
        else:
            print(f"moving to {action}.")
            #end_time = self.t + self.grid.get_travel_time(cluster, action, self.get_period())
            end_time = self.t + self.empirical_tt.get_sample(self.get_period(), cluster, action)

            self.transiters[cluster][action][_class] += 1

            arrival = Arrival(end_time, cluster, action, _class)
            heapq.heappush(self.next_events, (end_time, "t", arrival))

    def process_arrival(self, event):
        period = get_period(event.time + self.epoch_hour)

        # check if the vehicle auto-exits
        if self.models[self.get_period()][event._class].decide_exit():
            if event.cluster != event._class:
                cost = self.grid.get_travel_cost(event.cluster, event._class, period)
                self.observer.observe_reward(-cost, 0)
                self.observer.total_exit_cost += cost
            return

        driver_class = event._class
        start = event.start_cluster
        end = event.cluster

        #self.transiters[event.start_cluster][event.cluster][event._class] -= 1

        cost = self.grid.distance_costs[period][event.start_cluster][event.cluster]

        subsidy = self.controller.get_subsidy(period, driver_class, start, end)
        self.estimators[self.get_period()].observe_subsidy(driver_class, start, end, subsidy)

        self.observer.observe_reward(0, -subsidy)
        self.observer.total_subsidy += subsidy

        # let the driver decide where to spawn
        self.decide(event.cluster, driver_class)

    def process_transit(self, event):
        self.transiters[event.start_cluster][event.cluster][event._class] -= 1

        # accumulate mileage cost
        period = get_period(event.time + self.epoch_hour)
        cost = self.grid.distance_costs[period][event.start_cluster][event.cluster]
        self.observer.observe_reward(-cost, 0)
        self.observer.total_travel_cost += cost

        self.decide(event.cluster, event._class)

    def process_spawn(self, event):
        self.estimators[self.get_period()].observe_spawn(event.cluster, self.t)
        self.decide(event.cluster, event._class)

    def accumulate_rewards(self, event_t):
        # actually accumulating *costs* here, instantaneous rewards are handled elsewhere
        transit_cost = 0
        dt = event_t - self.t
        for start_cluster, x in enumerate(self.transiters):
            for end_cluster, y in enumerate(x):
                for _class, n in enumerate(y):
                    transit_cost += dt*n*RESERVATION

        waiting_cost = 0
        total_waiting = 0
        for cluster, x in enumerate(self.drivers):
            for _class, y in enumerate(x):
                waiting_cost += dt*len(y)*RESERVATION
                total_waiting += len(y)
        cost = transit_cost + waiting_cost
        print(f"accumulating cost: {cost}")
        print(f"waiting cost: {waiting_cost}")
        print(f"transit cost: {transit_cost}")
        print(f"dt: {dt}, total waiting: {total_waiting}")
        self.observer.observe_reward(-cost, 0)

        self.observer.total_waiting_cost += waiting_cost
        self.observer.total_travel_cost += transit_cost

    def step(self):
        event_t, event_type, event = heapq.heappop(self.next_events)


        print(f"({event_t}): {event}")

        if event_t - self.t > 24:
            # skipping weekends
            self.rate_tracker.reset(event_t)
            self.controller.reset(event_t)
        else:
            self.accumulate_rewards(event_t)

        self.t = event_t

        # recompute policies every 100 ticks
        #if self.t - self.last_policy_update >= 100:
        #    self.update_policies()

        if event_type == "a":
            self.process_arrival(event)
        elif event_type == "s":
            self.process_spawn(event)
        elif event_type == "r":
            self.process_request(event)
        elif event_type == "t":
            self.process_transit(event)

def get_exit_probs():
    exit_probs = [1.0] * N_PERIODS

    #with open("data/exit_probs.csv") as csvfile:
    #    reader = csv.DictReader(csvfile)
    #    for row in reader:
    #        exit_probs[int(row["period"])] = float(row["exit_prob"])
    #return [x/2 for x in exit_probs]

    arrival_rates = [[0 for i in range(N_CLUSTERS)] for j in range(N_PERIODS)]
    exit_rates = [[0 for i in range(N_CLUSTERS)] for j in range(N_PERIODS)]

    with open("data/arrival_rates.csv") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            period = int(row["period"])
            cluster = int(row["start"])
            arrival_rates[period][cluster] = float(row["arrivals"])

    with open("data/exit_rates.csv") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            period = int(row["period"])
            cluster = int(row["start"])
            exit_rates[period][cluster] = float(row["exits"])

    for period in range(N_PERIODS):
        probs = [0 for i in range(N_CLUSTERS)]

        for cluster in range(N_CLUSTERS):
            probs[cluster] = (exit_rates[period][cluster] / arrival_rates[period][cluster], cluster)

        probs.sort()

        num = 0
        denom = 0

        for idx in range(N_CLUSTERS//2):
            cluster = probs[idx][1]

            num += exit_rates[period][cluster]
            denom += arrival_rates[period][cluster]
        
        exit_probs[period] = num/denom
    
    return exit_probs


if __name__ == "__main__":
    reqs, epoch = trip_reqs.get_trip_requests()
    exit_probs = get_exit_probs()
    print(exit_probs)

    simulator = Simulator(reqs, 16, 16, 8, epoch, exit_probs, seed=0)
    while not simulator.is_stopped():
        simulator.step()
    sim_observer = simulator.observer
    print(f"Net profit: {sim_observer.profit}")
    print(f"Total reward: {sim_observer.total_reward}")
    print(f"Total revenue: {sim_observer.total_revenue}")
    print(f"Total waiting_cost: {sim_observer.total_waiting_cost}")
    print(f"Total travel cost: {sim_observer.total_travel_cost}")
    print(f"total trips: {sim_observer.total_trips}")
    print(f"total requests: {sim_observer.total_requests}")
    print(f"total exit cost: {sim_observer.total_exit_cost}")
    sim_observer.save_trip_counts("trip_counts.csv")
