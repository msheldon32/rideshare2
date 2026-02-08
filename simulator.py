import pandas as pd

import random
import heapq
import math

import trip_reqs
import spawner
import controller
import observer
import grid
import empirical_tt
import model
from util import *

class Simulator:
    def __init__(self, requests, n_classes, n_clusters, n_periods, epoch, models=None):
        self.requests = requests
        self.n_classes = n_classes
        self.n_clusters = n_clusters
        self.n_periods = n_periods
        
        self.grid = grid.Grid()
        self.empirical_tt = empirical_tt.EmpiricalTravel(self.grid, self.requests)
        last_t = [0 for i in range(N_CLUSTERS)]
        q_acc = [0 for i in range(N_CLUSTERS)]
        q_reports = [[] for i in range(N_CLUSTERS)]

        q_history = model.QHistory(q_reports)

        if models is None:
            self.w_estimates = [model.WEstimates(last_t, q_acc, q_history) for period in range(n_periods)]
            self.exploration = [model.Exploration() for period in range(n_periods)]
            self.models = [[model.DriverModel(self.grid, period, _class, self.w_estimates[period], self.exploration[period]) for _class in range(n_classes)] for period in range(n_periods)]
        else:
            self.models = models
            self.w_estimates = [model.WEstimates(last_t, q_acc, q_history) for period in range(n_periods)]
            for i, x in enumerate(self.w_estimates):
                # keep the point estimates of W, scrap the history
                self.w_estimates[i].w_estimates = self.models[i][0].w_estimates.w_estimates
                for k in range(self.n_classes):
                    self.models[i][k].w_estimates = x
            #self.w_estimates = [x[0].w_estimates for x in self.models]
            self.exploration = [x[0].exploration for x in self.models]

        self.drivers = [[[] for i in range(n_classes)] for j in range(n_clusters)] # contains the time entered for each driver of each class

        self.transiters = [[[0 for k in range(n_classes)] for j in range(n_clusters)] for l in range(n_clusters)]

        self.t = 0

        self.spawner = spawner.Spawner(epoch)
        self.controller = controller.Controller()
        self.observer = observer.Observer()

        self.next_events = [(0, "r", self.requests[0])]
        self.next_req = 1

        #heapq.heappush(self.next_events, self.spawner.get_spawn(0))
        for spawn in self.spawner.spawn_events:
            heapq.heappush(self.next_events, self.spawner.get_spawn_event(spawn))

        for req in self.requests:
            #heapq.heappush(self.next_events, (next_request.time, "r", next_request))
            heapq.heappush(self.next_events, (req.time, "r", req))

    def reset(self):
        self.observer.reset()
        self.spawner.reset()
        self.next_req = 1
        epoch = self.t

        # it should be noted that this preserves the heap
        self.next_events = [(a-epoch, b, c) for a,b,c in self.next_events]
        #heapq.heappush(self.next_events, self.spawner.get_spawn(0))

        self.t = 0
        self.next_events.append((0, "r", self.requests[0]))

        for j in range(self.n_clusters):
            for i in range(self.n_classes):
                self.drivers[j][i] = [x-epoch for x in self.drivers[j][i]]

    def is_stopped(self):
        return self.next_req == len(self.requests)
    
    def get_period(self):
        return get_period(self.t)

    def clean_queue(self, cluster, time):
        old_driver_ct = 0
        period = get_period(time)
        new_driver_ct = 0
        # remove any drivers that have been in the queue for more than 2 hours
        for _class in range(len(self.drivers[cluster])):
            old_driver_ct += len(self.drivers[cluster][_class])
            self.drivers[cluster][_class] = [x for x in self.drivers[cluster][_class] if (time-x) < 2]
            expelled_drivers = [x for x in self.drivers[cluster][_class] if (time-x) >= 2]
            new_driver_ct += len(self.drivers[cluster][_class])
        self.w_estimates[period].report_q_len(cluster, new_driver_ct, self.t)

    def process_request(self, request):
        if self.next_req < len(self.requests):
            #next_request = self.requests[self.next_req]
            #heapq.heappush(self.next_events, (next_request.time, "r", next_request))
            self.next_req += 1

        # check if a driver is available, and find the class if so
        driver_counts = [len(x) for x in self.drivers[request.start_cluster]]
        n_drivers = sum(driver_counts)

        if n_drivers == 0:
            self.observer.observe_request(request, None, False)
            return
        driver_class = random.choices(range(self.n_clusters), driver_counts, k=1)[0]
        self.controller.report_event(request.start_cluster, request.time, n_drivers)


        # expel a random driver from the queue
        driver_idx = random.randrange(len(self.drivers[request.start_cluster][driver_class]))
        waiting_time = self.drivers[request.start_cluster][driver_class][driver_idx]
        del self.drivers[request.start_cluster][driver_class][driver_idx]

        #self.w_estimates[request.period].report_q_len(request.start_cluster, n_drivers-1, self.t)

        self.clean_queue(request.start_cluster, request.time)

        #print("request q update")
        #waiting_time = self.w_estimates[request.period].last_w[request.start_cluster]
        remuneration = self.controller.get_price(request.period, driver_class, request.start_cluster, request.end_cluster, request.net_fare_cents, n_drivers, request.time, waiting_time)
        self.models[self.get_period()][driver_class].observe_r(request.start_cluster, remuneration)
        self.models[self.get_period()][driver_class].observe_p(request.start_cluster, request.end_cluster)


        fare = request.net_fare_cents / 100

        self.observer.observe_reward(fare, fare-remuneration)

        #end_time = request.time + self.grid.get_travel_time(request.start_cluster, request.end_cluster, self.get_period())
        end_time = request.time + self.empirical_tt.get_sample(self.get_period(), request.start_cluster, request.end_cluster)

        self.transiters[event.start_cluster][event.cluster][event._class] += 1
        arrival = Arrival(end_time, request.start_cluster, request.end_cluster, driver_class)
        heapq.heappush(self.next_events, (end_time, "a", arrival))

        self.observer.observe_request(request, remuneration, True)

    def decide(self, cluster, _class):
        # check the action of the driver and increment self.drivers appropriately
        #raise Exception("do")
        period = self.get_period()
        self.clean_queue(cluster, self.t)
        action = self.models[period][_class].decide(cluster, self.t)

        if action == -1:
            # vehicle leaves the system
            print(f"leaving the system.")
            return
        if action == cluster:
            #driver_counts = [len(x) for x in self.drivers[cluster]]
            #n_drivers = sum(driver_counts)
            #if n_drivers < 10:
            self.drivers[cluster][_class].append(self.t)
            driver_counts = [len(x) for x in self.drivers[cluster]]
            n_drivers = sum(driver_counts)
            self.controller.report_event(cluster, self.t, n_drivers)
            self.w_estimates[period].report_q_len(cluster, n_drivers, self.t)
            self.w_estimates[period].report_arrival(cluster, self.t)
            print(f"chose to enter queue: {cluster}")
        else:
            print(f"moving to {action}.")
            #end_time = self.t + self.grid.get_travel_time(cluster, action, self.get_period())
            end_time = self.t + self.empirical_tt.get_sample(self.get_period(), cluster, action)

            self.transiters[cluster][action][_class] += 1

            arrival = Arrival(end_time, cluster, action, _class)
            heapq.heappush(self.next_events, (end_time, "t", arrival))

    def process_arrival(self, event):
        # check if the vehicle auto-exits
        if self.models[self.get_period()][event._class].decide_exit():
            return
        
        driver_class = event._class
        period = get_period(event.time)
        start = event.start_cluster
        end = event.cluster

        self.transiters[event.start_cluster][event.cluster][event._class] -= 1

        cost = self.grid.distance_costs[period][event.start_cluster][event.cluster]

        subsidy = self.controller.get_subsidy(period, driver_class, start, end)
        self.models[self.get_period()][driver_class].observe_s(start, end, subsidy)

        self.observer.observe_reward(-cost, -subsidy)

        # let the driver decide where to spawn
        self.decide(event.cluster, driver_class)

    def process_transit(self, event):
        self.transiters[event.start_cluster][event.cluster][event._class] -= 1

        # accumulate mileage cost
        period = get_period(event.time)
        cost = self.grid.distance_costs[period][event.start_cluster][event.cluster]
        self.observer.observe_reward(-cost, 0)

        self.decide(event.cluster, event._class)

    def process_spawn(self, event):
        self.decide(event.cluster, event._class)

        # ask the spawner to spawn another event
        #heapq.heappush(self.next_events, self.spawner.get_spawn(self.t))

    def accumulate_rewards(self, event_t):
        # actually accumulating *costs* here, instantaneous rewards are handled elsewhere
        transit_cost = 0
        dt = event_t - self.t
        for start_cluster, x in enumerate(self.transiters):
            for end_cluster, y in enumerate(x):
                for _class, n in enumerate(y):
                    transit_cost += dt*n*RESERVATION

        waiting_cost = 0
        for cluster, x in enumerate(self.drivers):
            for _class, y in enumerate(x):
                waiting_cost += dt*len(y)*RESERVATION
        cost = transit_cost + waiting_cost
        self.observer.observe_reward(-cost, 0)

    def step(self):
        event_t, event_type, event = heapq.heappop(self.next_events)

        self.accumulate_rewards(event_t)

        print(f"({event_t}): {event}")

        self.t = event_t

        if event_type == "a":
            self.process_arrival(event)
        elif event_type == "s":
            self.process_spawn(event)
        elif event_type == "r":
            self.process_request(event)
        elif event_type == "t":
            self.process_transit(event)


if __name__ == "__main__":
    print("The big issue to fix now is that the V values seem identical across all clusters")
    print("I also think the cents vs dollars is a bit out of wack.")
    input("Trimmed the number of bellman iterations dramatically to speed things up")
    input("Need to finally fix waiting time inflation. Moving exploration to a constant")
    #input("Re-assigning bumped jobs")
    reqs, epoch = trip_reqs.get_trip_requests()
    simulator = Simulator(reqs, 16, 16, 8, epoch)
    while not simulator.is_stopped():
        simulator.step()

    simulator = Simulator(reqs, 16, 16, 8, epoch, models=simulator.models)
    while not simulator.is_stopped():
        simulator.step()
    sim_observer = simulator.observer
    print(f"Total trips: {sim_observer.total_trips}")
    print(f"Total requests: {sim_observer.total_requests}")
    print(f"Net profit: {sim_observer.profit}")
    sim_observer.save_trip_counts("trip_counts.csv")
