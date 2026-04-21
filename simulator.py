import pandas as pd

import random
import heapq
import math
import csv
from datetime import timedelta

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
import estimator_ewma
import estimator_empirical
import estimator_synthetic
import policy
from util import *

class Simulator:
    def __init__(self, requests, n_classes, n_clusters, n_periods, epoch, exit_probs,
                 controller_type="smoothed", alpha=0, ptg=0.2, seed=None, update_timestep=0.1, policy_smoothing=1.0,
                 use_empirical=False, use_agg=False, reevaluate=False, clear_at_1=True):
        #input("to do: have custom fare adjustments for different values of alpha")
        if seed is not None:
            random.seed(seed)

        self.reevaluate=reevaluate
        self.clear_at_1 = clear_at_1

        self.policy_update_window = 72
        self.policy_smoothing = policy_smoothing
        self.inactive_cleared = False

        self.requests = requests
        self.n_classes = n_classes
        self.n_clusters = n_clusters
        self.n_periods = n_periods
        self.exit_probs = exit_probs

        self.epoch = epoch

        self.warmup_period = 2000 
        self.tax_warmup = 1


        self.grid = grid.Grid()
        self.empirical_tt = empirical_tt.EmpiricalTravel(self.grid, self.requests)

        self.controller_type = controller_type
        self.rate_tracker = estimator_ewma.RateTracker(n_clusters)

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
        use_fare_tax = controller_type in ["method", "smoothed", "baseline"]
        self.use_agg_queue_policy = use_agg#controller_type in ["method", "smoothed"]

        # spawner / requester are needed up front so the estimators can read
        # the underlying rate sources (trace or synthetic generators)
        self.spawner = spawner.Spawner(epoch)
        self.requester = requester.Requester(self.grid, epoch)

        # one estimator per period
        #self.estimators = [estimator_mean.Estimator(self.rate_tracker, self.grid, period, self.controller, use_fare_tax=use_fare_tax, alpha=alpha) for period in range(n_periods)]
        self.empirical_estimator = use_empirical
        decay_tax = controller_type != "fixed"
        if use_empirical:
            self.trace_stats = estimator_empirical.TraceStatistics(requests, self.spawner.spawn_events, epoch)
            EstimatorClass = estimator_empirical.Estimator
        else:
            self.trace_stats = estimator_synthetic.ConstantStatistics(self.requester, self.spawner)
            EstimatorClass = estimator_synthetic.Estimator
        self.estimators = [EstimatorClass(self.rate_tracker, self.grid, period, self.controller, self.trace_stats, use_fare_tax=use_fare_tax, alpha=alpha, decay_tax=decay_tax, swap_reward_fare=self.swap_reward_fare, ptg=ptg) for period in range(n_periods)]

        self.update_timestep = update_timestep
        self.last_ewma_update = 0.0

        # default policy: always enter the queue at the current location
        default_policy = [([0.0] * i + [0] + [0] * (n_clusters - i)) for i in range(n_clusters)]
        for i in range(n_clusters):
            default_policy[i][-1] = 1.0
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

        self.observer = observer.Observer()
        self.observer_reset = False

        self.use_empirical = use_empirical
        self.next_events = []
        self.next_req = 1

        self.epoch_hour = self.epoch.hour

        print("building requests")
        if use_empirical:
            for req in self.requests:
                heapq.heappush(self.next_events, (req.time, "r", req))
            max_t = max(req.time for req in self.requests) if self.requests else 0
            #max_t = 5000
        else:
            max_t = 0
            while max_t < 7500:
                req_event = self.requester.get_request_poisson(max_t)
                max_t = req_event[0]
                heapq.heappush(self.next_events, req_event)
        self.max_t = max_t

        print("building spawns")
        if use_empirical:
            while True:
                spawn = self.spawner.get_spawn_data(0)
                if spawn[0] >= 1e9:
                    break
                heapq.heappush(self.next_events, spawn)
        else:
            spawn_t = 0
            while spawn_t < max_t:
                spawn = self.spawner.get_spawn_poisson(spawn_t)
                spawn_t = spawn[0]
                heapq.heappush(self.next_events, spawn)
        print("done.")
        print("computing initial WE policy from default estimator values...")
        self.update_policies()
        print("done.")

    def update_policies(self):
        if self.empirical_estimator or True:
            for est in self.estimators:
                est.flush(self.t)
            self.rate_tracker.flush(self.t)

        if self.t < self.warmup_period:
            self.observer.reward_printout(self.t)
        else:
            self.observer.reward_printout(self.t-self.warmup_period)
            agg_tag = "agg" if self.use_agg_queue_policy else "noagg"
            self.observer.write_reward_csv(f"rewards_{self.controller_type}_{agg_tag}.csv", self.t)

        for period in range(self.n_periods):
            config = self.estimators[period].get_config(self.exit_probs[period])
            print("-----------------------------------------------")
            print(f"({period}) updating policy")
            print(f"arrival_rates: {config.arrival_rates}")
            print(f"service_rates: {config.service_rates}")
            print(f"vehicle_rewards: {config.vehicle_rewards}")

            prev_policies = [self.models[period][_class].policy for _class in range(self.n_classes)]
            if self.use_agg_queue_policy:
                new_policies = policy.get_policies_agg_queue(config, prev_policies=prev_policies)
            else:
                new_policies = policy.get_policies(config, prev_policies=prev_policies)

            est_reward = policy.estimate_total_reward(config, new_policies)
            print(f"estimated total reward rate: {est_reward:.4f}")
            #print(f"new_policy sample (5,7): {new_policies[5][5]}")
            #print(f"new_policy sample: {new_policies[5][7]}")

            for _class in range(self.n_classes):
                old_policy = self.models[period][_class].policy
                blended = [
                    [(1 - self.policy_smoothing) * old_policy[i][a] + self.policy_smoothing * new_policies[_class][i][a]
                     for a in range(len(old_policy[i]))]
                    for i in range(self.n_clusters)
                ]
                self.models[period][_class] = model.DriverModel(blended, self.exit_probs[period])

        if not self.empirical_estimator and False:
            for est in self.estimators:
                est.flush(self.t)
            self.rate_tracker.flush(self.t)
        input("Continue? ")

        self.last_policy_update = self.t

    def is_stopped(self):
        #return self.next_req >= 10000
        #return self.next_req == len(self.requests)
        return self.t >= self.max_t

    def get_period(self):
        return get_period(self.t + self.epoch_hour)

    def is_active_day(self, t):
        # True if simulation time t falls on Mon, Tue, or Wed (weekday 0-2).
        return (self.epoch + timedelta(hours=t)).weekday() <= 2

    def clear_all_drivers(self):
        for cluster in range(self.n_clusters):
            for _class in range(self.n_classes):
                self.drivers[cluster][_class] = []
        for i in range(self.n_clusters):
            for j in range(self.n_clusters):
                for k in range(self.n_classes):
                    self.transiters[i][j][k] = 0

    def reevaluate_queues(self):
        # Pop every queued driver and re-run decide() under the current period's policy.
        queued = []
        for cluster in range(self.n_clusters):
            for _class in range(self.n_classes):
                for _ in self.drivers[cluster][_class]:
                    queued.append((cluster, _class))
                self.drivers[cluster][_class] = []
        for cluster, _class in queued:
            self.decide(cluster, _class)

    def empty_queues(self):
        queued = []
        for cluster in range(self.n_clusters):
            for _class in range(self.n_classes):
                self.drivers[cluster][_class] = []


    def get_queue_lengths(self):
        return [sum(len(self.drivers[cluster][_class]) for _class in range(self.n_classes)) for cluster in range(self.n_clusters)]

    def clean_queue(self, cluster, time):
        old_driver_ct = 0
        period = get_period(time + self.epoch_hour)
        new_driver_ct = 0
        # remove any drivers that have been in the queue for more than 2 hours
        for _class in range(len(self.drivers[cluster])):
            old_driver_ct += len(self.drivers[cluster][_class])
            expelled_drivers = [x for x in self.drivers[cluster][_class] if (time-x) >= 2]
            #self.drivers[cluster][_class] = [x for x in self.drivers[cluster][_class] if (time-x) < 2]
            new_driver_ct += len(self.drivers[cluster][_class])

    def process_request(self, request):
        if not self.observer_reset and self.t >= self.warmup_period:
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

        #if new_tax is not None:
        #    self.estimators[self.get_period()].observe_tax(driver_class, request.start_cluster, new_tax)

        # expel a random driver from the queue
        driver_idx = random.randrange(len(self.drivers[request.start_cluster][driver_class]))
        waiting_time = self.t - self.drivers[request.start_cluster][driver_class][driver_idx]
        del self.drivers[request.start_cluster][driver_class][driver_idx]
        self.estimators[self.get_period()].observe_queue_lengths(self.t, self.get_queue_lengths())

        self.clean_queue(request.start_cluster, request.time)

        if False: 
            print("-------------------")
            print(f"n_drivers: {n_drivers}")
            print(f"tax: {self.controller.last_tax[request.start_cluster]*RESERVATION}")
            #est_tax = self.estimators[request.period].waiting_time_estimates[request.start_cluster]*self.estimators[request.period].queue_length_estimates[request.start_cluster]*RESERVATION
            arrival_rate = self.estimators[request.period].get_queue_arrival_rates()[request.start_cluster]
            service_rate = self.estimators[request.period].get_service_rates()[request.start_cluster]
            if service_rate == arrival_rate:
                est_tax = 0
            else:
                est_tax = RESERVATION*(arrival_rate/((service_rate-arrival_rate)**2))
            print(f"est_tax: {est_tax},  est arrival: {arrival_rate}, service: {service_rate}")
            print("-------------------")

        # pm: class specific reward interpreted on a sliding scale based on alpha
        remuneration, tr, pm, tax = self.controller.get_price(request.period, driver_class, request.start_cluster, request.end_cluster, request.gross_fare_cents, request.net_fare_cents, n_drivers, request.time, waiting_time)

        fare = request.net_fare_cents / 100

        # estimator observations
        self.estimators[self.get_period()].observe_reward(driver_class, request.start_cluster, pm)
        self.estimators[self.get_period()].observe_tax(driver_class, request.start_cluster, tax)
        if self.swap_reward_fare:
            # need to swap these since for the fixed controller we're using a global fare adjustment
            #self.estimators[self.get_period()].observe_fare(driver_class, request.start_cluster, remuneration)
            #self.estimators[self.get_period()].observe_fare(driver_class, request.start_cluster, fare)
            #self.estimators[self.get_period()].observe_tax(driver_class, request.start_cluster, fare-remuneration)
            pass
        else:
            self.estimators[self.get_period()].observe_fare(driver_class, request.start_cluster, fare)

        self.observer.observe_reward(fare, fare-remuneration, self.get_period())
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
                self.observer.observe_reward(-cost, 0, period)
                self.observer.total_exit_cost += cost
            return
        if action == cluster:
            driver_counts = [len(x) for x in self.drivers[cluster]]
            n_drivers = sum(driver_counts)
            print(f"reporting arrival, ct: {n_drivers}")
            self.drivers[cluster][_class].append(self.t)
            new_tax = self.controller.report_event(cluster, self.t, n_drivers, "arrival")
            #if new_tax is not None:
            #    self.estimators[self.get_period()].observe_tax(_class, cluster, new_tax)
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
                self.observer.observe_reward(-cost, 0, period)
                self.observer.total_exit_cost += cost
            return

        driver_class = event._class
        start = event.start_cluster
        end = event.cluster

        #self.transiters[event.start_cluster][event.cluster][event._class] -= 1

        cost = self.grid.distance_costs[period][event.start_cluster][event.cluster]

        subsidy = self.controller.get_subsidy(period, driver_class, start, end)
        self.estimators[self.get_period()].observe_subsidy(driver_class, start, end, subsidy)

        self.observer.observe_reward(0, -subsidy, period)
        self.observer.total_subsidy += subsidy

        # let the driver decide where to spawn
        self.decide(event.cluster, driver_class)

    def process_transit(self, event):
        self.transiters[event.start_cluster][event.cluster][event._class] -= 1

        # accumulate mileage cost
        period = get_period(event.time + self.epoch_hour)
        cost = self.grid.distance_costs[period][event.start_cluster][event.cluster]
        self.observer.observe_reward(-cost, 0, period)
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
        self.observer.observe_reward(-cost, 0, self.get_period())

        self.observer.total_waiting_cost += waiting_cost
        self.observer.total_travel_cost += transit_cost

    def step(self):
        event_t, event_type, event = heapq.heappop(self.next_events)


        print(f"({event_t}): {event}")

        if (not self.is_active_day(event_t) or event_t - self.t > 24) and self.use_empirical:
            # skipping inactive days (Thu-Sun) or any gap longer than a day
            if not self.inactive_cleared:
                # finalize pre-gap state: consume buffers, EWMA-flush, recompute
                # policies, and clear driver state so nothing leaks across the gap.
                for est in self.estimators:
                    est.update_estimator()
                self.update_policies()
                self.clear_all_drivers()
                self.inactive_cleared = True

            self.rate_tracker.reset(event_t)
            self.controller.reset(event_t)

            # keep the update timers pinned to sim time so the first active-day
            # event doesn't see a multi-day delta and fire on empty buffers.
            self.last_ewma_update = event_t
            self.last_policy_update = event_t

            self.t = event_t
            return
        else:
            self.inactive_cleared = False
            self.estimators[self.get_period()].observe_queue_lengths(self.t, self.get_queue_lengths())
            old_period = self.get_period()
            self.accumulate_rewards(event_t)

            self.t = event_t

            if self.t - self.last_ewma_update >= self.update_timestep:
                for est in self.estimators:
                    est.update_estimator()
                self.last_ewma_update = self.t

            # recompute policies periodically
            if self.t - self.last_policy_update >= self.policy_update_window:
                self.update_policies()

            if self.get_period() != old_period and self.reevaluate:
                self.reevaluate_queues()
            if self.get_period() != old_period and self.clear_at_1 and self.get_period() == 1:
                self.empty_queues()

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

        for cluster_idx in range(N_CLUSTERS//4):
            cluster = probs[cluster_idx][1]
            num += exit_rates[period][cluster]
            denom += arrival_rates[period][cluster]
        
        #exit_probs[period] = probs[0][0]#num/denom
        exit_probs[period] = num/denom
    
    return exit_probs


if __name__ == "__main__":
    reqs, epoch = trip_reqs.get_trip_requests()
    exit_probs = get_exit_probs()
    print(exit_probs)
    input("continue")

    input("Need to fix two things: 1. the pm adjustment for total reward, 2. diagnose underperformance")

    controller_type = "method"
    use_empirical = True
    use_agg = False

    simulator = Simulator(reqs, 16, 16, 8, epoch, exit_probs, seed=3, controller_type=controller_type, alpha=0, use_empirical=use_empirical, use_agg=use_agg)
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
    print("Reward by period:")
    for p in range(len(sim_observer.reward_by_period)):
        print(f"  period {p}: reward={sim_observer.reward_by_period[p]:.2f}, profit={sim_observer.profit_by_period[p]:.2f}")
    if controller_type == "baseline":
        sim_observer.save_trip_counts("trip_counts.csv")
