from util import N_CLUSTERS, N_PERIODS
from model_config import ModelConfig

import collections
import random

class RateTracker:
    def __init__(self, n_locations):
        self.n_locations = n_locations
        self.last_spawn_time = [0.0 for _ in range(n_locations)]
        self.last_arrival_time = [0.0 for _ in range(n_locations)]
        self.last_service_time = [0.0 for _ in range(n_locations)]
        self.services = [collections.deque() for _ in range(self.n_locations)]
        self.queue_lengths = [0 for _ in range(n_locations)]
        self.last_arrival_time_in_period = [[float("inf") for _ in range(n_locations)] for period in range(N_PERIODS)]

    def reset(self, t):
        self.last_spawn_time = [t for _ in range(self.n_locations)]
        self.last_service_time = [t for _ in range(self.n_locations)]


class Estimator:
    def __init__(self, rate_tracker, grid, period, controller):
        self.rate_tracker = rate_tracker
        self.grid = grid
        self.period = period
        self.n_locations = N_CLUSTERS
        self.controller = controller



        # inter-spawn time estimates (per location)
        self.inter_spawn_estimates = [1.0 for _ in range(self.n_locations)]

        # inter-service time estimates (per location)
        self.inter_service_estimates = [1.0 for _ in range(self.n_locations)]

        # customer transition probability estimates (uniform prior)
        self.transition_estimates = [[(1 / self.n_locations) for _ in range(self.n_locations)] for _ in range(self.n_locations)]

        # reward estimates: [origin][location]
        self.reward_estimates = [[10.0 for _ in range(self.n_locations)] for _ in range(self.n_locations)]

        # fare estimates: [origin][location]
        self.fare_estimates = [10.0 for _ in range(self.n_locations)]

        # tax estimates: [origin][location]
        self.tax_estimates = [0.0 for _ in range(self.n_locations)]

        # subsidy estimates: [origin][start][end]
        self.subsidy_estimates = [[[0.0 for _ in range(self.n_locations)] for _ in range(self.n_locations)] for _ in range(self.n_locations)]

        self.waiting_time_estimates = [0.5 for _ in range(self.n_locations)]

        # queue length estimates (per location)
        self.queue_length_estimates = [0.0 for _ in range(self.n_locations)]

        self.time_window = 2

        # Accumulator buffers for deferred EWMA updates
        self._spawn_buffer = [[] for _ in range(self.n_locations)]
        self._service_buffer = [[] for _ in range(self.n_locations)]
        self._transition_buffer = []
        self._reward_buffer = [[[] for _ in range(self.n_locations)] for _ in range(self.n_locations)]
        self._fare_buffer = [[] for _ in range(self.n_locations)]
        self._tax_buffer = [[] for _ in range(self.n_locations)]
        self._subsidy_buffer = [[[[] for _ in range(self.n_locations)] for _ in range(self.n_locations)] for _ in range(self.n_locations)]
        self._w_buffer = [[] for _ in range(self.n_locations)]
        self._queue_buffer = [[] for _ in range(self.n_locations)]

    def clean_rewards(self, t):
        for cluster in range(N_CLUSTERS):
            if (t - self.rate_tracker.last_arrival_time_in_period[self.period][cluster]) > 7*24:
                for _class in range(N_CLUSTERS):
                    # to prevent freezeout, simply increment the reward for a bit.
                    self.reward_estimates[_class][cluster] = min(10, self.reward_estimates[_class][cluster]+1)
                # note that this is only used here, it's simply to prevent consecutive updates
                self.rate_tracker.last_arrival_time_in_period[self.period][cluster] = t

    def update_w_estimates(self, t):
        for loc in range(self.n_locations):
            while len(self.rate_tracker.services[loc]) > 0 and self.rate_tracker.services[loc][0] < t-self.time_window:
                self.rate_tracker.services[loc].popleft()
            
            if len(self.rate_tracker.services[loc]) == 0:
                mu = 1/self.inter_service_estimates[loc]
            else:
                mu = len(self.rate_tracker.services[loc])/self.time_window

            #old_w = self.waiting_time_estimates[loc]
            #new_w = (1 + self.rate_tracker.queue_lengths[loc])/mu
            new_w = (1+ self.rate_tracker.queue_lengths[loc])*self.inter_service_estimates[loc]

            self._w_buffer[loc].append(new_w)

    def observe_queue_lengths(self, t, queue_lengths):
        self.update_w_estimates(t)
        self.rate_tracker.queue_lengths = queue_lengths
        for loc in range(self.n_locations):
            self._queue_buffer[loc].append(queue_lengths[loc])

    def observe_spawn(self, location, t):
        inter_spawn = t - self.rate_tracker.last_spawn_time[location]
        self._spawn_buffer[location].append(inter_spawn)
        self.rate_tracker.last_spawn_time[location] = t

    def observe_arrival(self, location, _class, t):
        self.rate_tracker.last_arrival_time[location] = t
        self.rate_tracker.last_arrival_time_in_period[self.period][location] = t

    def observe_service(self, location, t):
        inter_service = t - self.rate_tracker.last_service_time[location]
        self._service_buffer[location].append(inter_service)
        self.rate_tracker.last_service_time[location] = t

        self.rate_tracker.services[location].append(t)


    def observe_transition(self, start, end):
        self._transition_buffer.append((start, end))

    def observe_reward(self, origin, location, reward):
        #reward = min(reward, 50)
        self._reward_buffer[origin][location].append(reward)

    def observe_fare(self, origin, location, fare):
        self._fare_buffer[location].append(fare)

    def observe_tax(self, origin, location, tax):
        self._tax_buffer[location].append(tax)

    def observe_subsidy(self, origin, start, end, subsidy):
        self._subsidy_buffer[origin][start][end].append(subsidy)

    def update_estimator(self):
        # Spawn buffer
        for loc in range(self.n_locations):
            if self._spawn_buffer[loc]:
                self.inter_spawn_estimates[loc] = sum(self._spawn_buffer[loc]) / len(self._spawn_buffer[loc])

        # Service buffer
        for loc in range(self.n_locations):
            if self._service_buffer[loc]:
                self.inter_service_estimates[loc] = sum(self._service_buffer[loc]) / len(self._service_buffer[loc])

        # Transition buffer
        if self._transition_buffer:
            counts = [[0] * self.n_locations for _ in range(self.n_locations)]
            row_totals = [0] * self.n_locations
            for start, end in self._transition_buffer:
                counts[start][end] += 1
                row_totals[start] += 1
            for i in range(self.n_locations):
                if row_totals[i] > 0:
                    for j in range(self.n_locations):
                        self.transition_estimates[i][j] = counts[i][j] / row_totals[i]

        # Reward buffer
        for origin in range(self.n_locations):
            for loc in range(self.n_locations):
                if self._reward_buffer[origin][loc]:
                    self.reward_estimates[origin][loc] = sum(self._reward_buffer[origin][loc]) / len(self._reward_buffer[origin][loc])

        # Fare buffer
        for loc in range(self.n_locations):
            if self._fare_buffer[loc]:
                self.fare_estimates[loc] = sum(self._fare_buffer[loc]) / len(self._fare_buffer[loc])

        # Tax buffer
        for loc in range(self.n_locations):
            if self._tax_buffer[loc]:
                self.tax_estimates[loc] = sum(self._tax_buffer[loc]) / len(self._tax_buffer[loc])

        # Subsidy buffer
        for origin in range(self.n_locations):
            for start in range(self.n_locations):
                for end in range(self.n_locations):
                    if self._subsidy_buffer[origin][start][end]:
                        self.subsidy_estimates[origin][start][end] = sum(self._subsidy_buffer[origin][start][end]) / len(self._subsidy_buffer[origin][start][end])

        # Waiting time buffer
        for loc in range(self.n_locations):
            if self._w_buffer[loc]:
                self.waiting_time_estimates[loc] = sum(self._w_buffer[loc]) / len(self._w_buffer[loc])

        # Queue length buffer
        for loc in range(self.n_locations):
            if self._queue_buffer[loc]:
                self.queue_length_estimates[loc] = sum(self._queue_buffer[loc]) / len(self._queue_buffer[loc])

    def get_arrival_rates(self):
        return [1.0 / self.inter_spawn_estimates[i] for i in range(self.n_locations)]

    def get_service_rates(self):
        return [1.0 / self.inter_service_estimates[i] for i in range(self.n_locations)]

    def get_config(self, exit_prob):
        adjusted_rewards = [[0.0] * self.n_locations for _ in range(self.n_locations)]
        for _class in range(self.n_locations):
            for origin in range(self.n_locations):
                origin_return_cost = self.grid.get_travel_cost(origin, _class, self.period)
                expected_dest_return_cost = sum(
                    self.transition_estimates[origin][dest] * self.grid.get_travel_cost(dest, _class, self.period)
                    for dest in range(self.n_locations)
                )
                adjusted_rewards[_class][origin] = (
                    self.reward_estimates[_class][origin]
                    + origin_return_cost
                    - expected_dest_return_cost
                )

        return ModelConfig(
            grid=self.grid,
            period=self.period,
            arrival_rates=self.get_arrival_rates(),
            service_rates=self.get_service_rates(),
            vehicle_rewards=adjusted_rewards,
            producer_rewards=self.fare_estimates,
            exit_prob=exit_prob,
            customer_transitions=self.transition_estimates
        )
