import pandas as pd

import random
import heapq
import math
import csv

import trip_reqs
import requester
import spawner
import controller
import observer
import grid
import empirical_tt
import model_alt
import model
import estimator_mean
import policy
from util import *

class Simulator:
    def __init__(self, requests, n_classes, n_clusters, n_periods, epoch, exit_probs,
                 controller_type="smoothed", alpha=0, ptg=0.2, seed=None, ewma_timestep=0.5):
        if seed is not None:
            random.seed(seed)

        self.requests = requests
        self.n_classes = n_classes
        self.n_clusters = n_clusters
        self.n_periods = n_periods
        self.exit_probs = exit_probs

        self.epoch = epoch


        self.grid = grid.Grid()
        self.empirical_tt = empirical_tt.EmpiricalTravel(self.grid, self.requests)

        self.controller_type = controller_type
        self.rate_tracker = estimator_mean.RateTracker(n_clusters)

        if controller_type == "baseline":
            self.controller = controller.Controller()
        elif controller_type == "method":
            self.controller = controller.MethodController(alpha, self.grid)
        elif controller_type == "buffer":
            self.controller = controller.BufferController(self.grid)
        elif controller_type == "smoothed":
            self.controller = controller.SmoothedController(alpha, self.grid)
        elif controller_type == "fixed":
            self.controller = controller.FixedController(ptg)
        else:
            raise ValueError(f"Unknown controller type: {controller_type}")

        use_tax = controller_type in ["smoothed"]
        self.swap_reward_fare = controller_type == "fixed"
        use_fare_tax = controller_type in ["method", "smoothed"]

        # one estimator per period
        self.estimators = [estimator_mean.Estimator(self.rate_tracker, self.grid, period, self.controller, use_fare_tax=use_fare_tax) for period in range(n_periods)]

        self.ewma_timestep = ewma_timestep
        self.last_ewma_update = 0.0

        # default policy: always enter the queue at the current location
        default_policy = [([0.0] * i + [1.0] + [0.0] * (n_clusters - i)) for i in range(n_clusters)]
        self.models = [[model.DriverModel(default_policy, exit_probs[period]) for _class in range(n_classes)] for period in range(n_periods)]

        """self.exploration = [[model_alt.Exploration() for _class in range(n_classes)] for period in range(n_periods)]
        self.models = [[model_alt.DriverModel(self.grid,
                                              period,
                                              _class,
                                              self.estimators[period],
                                              self.exit_probs[period],
                                              self.exploration[period][_class],
                                              use_tax=use_tax) for _class in range(n_classes)] for period in range(n_periods)]"""

        self.drivers = [[[] for i in range(n_classes)] for j in range(n_clusters)] # contains the time entered for each driver of each class

        self.transiters = [[[0 for k in range(n_classes)] for j in range(n_clusters)] for l in range(n_clusters)]

        self.t = 0
        self.last_policy_update = 0

        self.spawner = spawner.Spawner(epoch)
        self.requester = requester.Requester(epoch)
        self.observer = observer.Observer()
        self.observer_reset = False

        self.next_events = []#(0, "r", self.requests[0])]
        self.next_req = 1

        self.epoch_hour = self.epoch.hour

        max_t = 0
        print("building requests")

        while max_t < 7300:
            req_event = self.requester.get_request_poisson(max_t)
            max_t = req_event[0]
            heapq.heappush(self.next_events, req_event)
        self.max_t = max_t

        #for req in self.requests:
        #    max_t = max(max_t, req.time)
        #    heapq.heappush(self.next_events, (req.time, "r", req))

        #for spawn in self.spawner.spawn_events:
        #    # add Gaussian (-0.5, 1.0) noise to the spawn time
        #    new_t = spawn[0] + random.gauss(-0.5, 1.0)
        #    spawn = (new_t, spawn[1], spawn[2])
        #    heapq.heappush(self.next_events, self.spawner.get_spawn_event(spawn))
        spawn_t = 0
        print("building spawns")
        while spawn_t < max_t:
            spawn = self.spawner.get_spawn_poisson(spawn_t)
            spawn_t = spawn[0]
            heapq.heappush(self.next_events, spawn)
        print("done.")
        print("computing initial WE policy from default estimator values...")
        self.update_policies()
        print("done.")

    def update_policies(self):
        for period in range(self.n_periods):
            config = self.estimators[period].get_config(self.exit_probs[period])
            print("-----------------------------------------------")
            print(f"({period}) updating policy")
            print(f"arrival_rates: {config.arrival_rates}")
            print(f"service_rates: {config.service_rates}")
            print(f"vehicle_rewards: {config.vehicle_rewards}")

            new_policies = policy.get_policies(config)
            for _class in range(self.n_classes):
                self.models[period][_class] = model.DriverModel(new_policies[_class], self.exit_probs[period])

        for est in self.estimators:
            est.flush()
        self.rate_tracker.flush(self.t)

        self.last_policy_update = self.t

    def is_stopped(self):
        #return self.next_req >= 10000
        #return self.next_req == len(self.requests)
        return self.t >= self.max_t

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
        if not self.observer_reset and self.t >= 3000:
            self.observer.reset()
            self.observer_reset = True

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

        print(f"reporting departure, n_drivers: {n_drivers}")
        new_tax = self.controller.report_event(request.start_cluster, request.time, n_drivers, "departure")

        if n_drivers == 0:
            self.observer.observe_request(request, None, False)
            return
        driver_class = random.choices(range(self.n_clusters), driver_counts, k=1)[0]

        if new_tax is not None:
            self.estimators[self.get_period()].observe_tax(driver_class, request.start_cluster, new_tax)

        # expel a random driver from the queue
        driver_idx = random.randrange(len(self.drivers[request.start_cluster][driver_class]))
        waiting_time = self.t - self.drivers[request.start_cluster][driver_class][driver_idx]
        del self.drivers[request.start_cluster][driver_class][driver_idx]
        self.estimators[self.get_period()].observe_queue_lengths(self.t, self.get_queue_lengths())

        self.clean_queue(request.start_cluster, request.time)

        remuneration = self.controller.get_price(request.period, driver_class, request.start_cluster, request.end_cluster, request.gross_fare_cents, request.net_fare_cents, n_drivers, request.time, waiting_time)

        fare = request.net_fare_cents / 100

        # estimator observations
        self.estimators[self.get_period()].observe_reward(driver_class, request.start_cluster, remuneration)
        if self.swap_reward_fare:
            self.estimators[self.get_period()].observe_fare(driver_class, request.start_cluster, remuneration)
        else:
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
        #self.estimators[self.get_period()].clean_rewards(self.t)
        action = self.models[period][_class].decide(cluster)
        #action = self.models[period][_class].decide(cluster, self.t)  # model_alt

        if action == -1:
            # vehicle leaves the system
            print(f"leaving the system.")
            if cluster != _class:
                cost = self.grid.get_travel_cost(cluster, _class, period)
                self.observer.observe_reward(-cost, 0)
                self.observer.total_exit_cost += cost
            return
        if action == cluster:
            driver_counts = [len(x) for x in self.drivers[cluster]]
            n_drivers = sum(driver_counts)
            print(f"reporting arrival, ct: {n_drivers}")
            self.drivers[cluster][_class].append(self.t)
            new_tax = self.controller.report_event(cluster, self.t, n_drivers, "arrival")
            if new_tax is not None:
                self.estimators[self.get_period()].observe_tax(_class, cluster, new_tax)
            self.estimators[self.get_period()].observe_queue_lengths(self.t, self.get_queue_lengths())
            self.estimators[self.get_period()].observe_arrival(cluster, _class, self.t)
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
        self.estimators[self.get_period()].observe_queue_lengths(self.t, self.get_queue_lengths())
        event_t, event_type, event = heapq.heappop(self.next_events)


        print(f"({event_t}): {event}")

        if event_t - self.t > 24:
            # skipping weekends
            self.rate_tracker.reset(event_t)
            self.controller.reset(event_t)
        else:
            self.accumulate_rewards(event_t)

        self.t = event_t

        if self.t - self.last_ewma_update >= self.ewma_timestep:
            for est in self.estimators:
                est.update_estimator()
            self.last_ewma_update = self.t

        # recompute policies periodically
        if self.t - self.last_policy_update >= 100:
            self.update_policies()

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

        for cluster in range(N_CLUSTERS//4):
            num += exit_rates[period][cluster]
            denom += arrival_rates[period][cluster]
        
        exit_probs[period] = probs[0][0]#num/denom
    
    return exit_probs


if __name__ == "__main__":
    reqs, epoch = trip_reqs.get_trip_requests()
    exit_probs = get_exit_probs()
    print(exit_probs)
    input("continue")

    controller_type = "baseline"

    simulator = Simulator(reqs, 16, 16, 8, epoch, exit_probs, seed=0, controller_type=controller_type, alpha=0)
    while not simulator.is_stopped():
        simulator.step()
    sim_observer = simulator.observer
    print(f"For controller type: {controller_type}")
    print(f"Net profit: {sim_observer.profit}")
    print(f"Total reward: {sim_observer.total_reward}")
    print(f"Total revenue: {sim_observer.total_revenue}")
    print(f"Total waiting_cost: {sim_observer.total_waiting_cost}")
    print(f"Total travel cost: {sim_observer.total_travel_cost}")
    print(f"total trips: {sim_observer.total_trips}")
    print(f"total requests: {sim_observer.total_requests}")
    print(f"total exit cost: {sim_observer.total_exit_cost}")
    if controller_type == "baseline":
        sim_observer.save_trip_counts("trip_counts.csv")
