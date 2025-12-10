import pandas as pd

import random
import heapq
import math

import trip_reqs
import spawner
import controller
import observer
import grid
import model
from util import *

class Simulator:
    def __init__(self, requests, n_classes, n_clusters, n_periods):
        self.requests = requests
        self.n_classes = n_classes
        self.n_clusters = n_clusters
        self.n_periods = n_periods

        self.grid = grid.Grid()
        self.w_estimates = [model.WEstimates() for period in range(n_periods)]
        self.models = [[model.DriverModel(self.grid, period, _class, self.w_estimates[period]) for _class in range(n_classes)] for period in range(n_periods)]

        self.drivers = [[[] for i in range(n_classes)] for j in range(n_clusters)] # contains the time entered for each driver of each class

        self.t = 0

        self.spawner = spawner.Spawner()
        self.controller = controller.Controller()
        self.observer = observer.Observer()

        self.next_events = [(0, "r", self.requests[0])]
        self.next_req = 1

        heapq.heappush(self.next_events, self.spawner.get_spawn(0))

    def reset(self):
        self.observer.reset()
        self.next_req = 1
        self.t = 0
        self.next_events.append((0, "r", self.requests[0]))

        for j in range(self.n_clusters):
            for i in range(self.n_classes):
                self.drivers[j][i] = [0 for x in self.drivers[j][i]]

    def is_stopped(self):
        return self.next_req == len(self.requests)
    
    def get_period(self):
        return get_period(self.t)

    def clean_queue(self, cluster, time):
        # remove any drivers that have been in the queue for more than 2 hours
        for _class in range(len(self.drivers[cluster])):
            self.drivers[cluster][_class] = [x for x in self.drivers[cluster][_class] if (time-x) < 2]
            expelled_drivers = [x for x in self.drivers[cluster][_class] if (time-x) >= 2]
            for d in expelled_drivers:
                self.models[cluster][_class].observe_w(cluster, time-d)

    def process_request(self, request):
        if self.next_req < len(self.requests):
            next_request = self.requests[self.next_req]
            heapq.heappush(self.next_events, (next_request.time, "r", next_request))
            self.next_req += 1

        self.clean_queue(request.start_cluster, request.time)

        # check if a driver is available, and find the class if so
        driver_counts = [len(x) for x in self.drivers[request.start_cluster]]
        n_drivers = sum(driver_counts)

        if n_drivers == 0:
            self.observer.observe_request(request, None, False)
            return
        n_drivers_elsewhere = [sum([len(x) for x in y]) for y in self.drivers]
        driver_class = random.choices(range(self.n_clusters), driver_counts, k=1)[0]
        self.controller.report_event(request.start_cluster, request.time, n_drivers)


        # check the waiting time of a random driver and report it, as well as the controller's price
        n_drivers_in_class = len(self.drivers[request.start_cluster][driver_class])
        to_evict = random.randrange(n_drivers_in_class)
        arrival_t = self.drivers[request.start_cluster][driver_class].pop(to_evict)
        waiting_time = request.time - arrival_t
        self.models[self.get_period()][driver_class].observe_w(request.start_cluster, waiting_time)
        remuneration = self.controller.get_price(request.period, driver_class, request.start_cluster, request.end_cluster, request.net_fare_cents, n_drivers, request.time, waiting_time)
        self.models[self.get_period()][driver_class].observe_r(request.start_cluster, remuneration)
        self.models[self.get_period()][driver_class].observe_p(request.start_cluster, request.end_cluster)

        end_time = request.time + self.grid.get_travel_time(request.start_cluster, request.end_cluster, self.get_period())

        arrival = Arrival(end_time, request.start_cluster, request.end_cluster, driver_class)
        heapq.heappush(self.next_events, (end_time, "a", arrival))

        self.observer.observe_request(request, remuneration, True)

    def decide(self, cluster, _class):
        # check the action of the driver and increment self.drivers appropriately
        #raise Exception("do")
        period = self.get_period()

        action = self.models[period][_class].decide(cluster)

        if action == -1:
            # vehicle leaves the system
            print(f"leaving the system.")
            return
        if action == cluster:
            driver_counts = [len(x) for x in self.drivers[cluster]]
            n_drivers = sum(driver_counts)
            self.drivers[cluster][_class].append(self.t)
            self.controller.report_event(cluster, self.t, n_drivers)
            print(f"chose to enter queue: {cluster}")
        else:
            print(f"moving to {action}.")
            end_time = self.t + self.grid.get_travel_time(cluster, action, self.get_period())

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

        subsidy = self.controller.get_subsidy(period, driver_class, start, end)
        self.models[self.get_period()][driver_class].observe_s(start, end, subsidy)

        # let the driver decide where to spawn
        self.decide(event.cluster, driver_class)

    def process_transit(self, event):
        self.decide(event.cluster, event._class)

    def process_spawn(self, event):
        self.decide(event.cluster, event._class)

        # ask the spawner to spawn another event
        heapq.heappush(self.next_events, self.spawner.get_spawn(self.t))

    def step(self):
        event_t, event_type, event = heapq.heappop(self.next_events)

        self.t = event_t

        print(f"({event_t}): {event}")

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
    reqs = trip_reqs.get_trip_requests()
    simulator = Simulator(reqs, 16, 16, 8)
    while not simulator.is_stopped():
        simulator.step()
    simulator.reset()
    while not simulator.is_stopped():
        simulator.step()
    sim_observer = simulator.observer
    print(f"Total trips: {sim_observer.total_trips[-1]}")
    print(f"Total requests: {sim_observer.total_requests[-1]}")
    print(f"Net profit: {sim_observer.profit[-1]}")
