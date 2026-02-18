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

        # EWMA smoothing factors
        self.alpha_spawn = 0.95
        self.alpha_service = 0.95
        self.alpha_transition = 0.95
        self.alpha_reward = 0.95
        self.alpha_subsidy = 0.95
        self.alpha_w = 0.95

        # inter-spawn time estimates (per location)
        self.inter_spawn_estimates = [1.0 for _ in range(self.n_locations)]

        # inter-service time estimates (per location)
        self.inter_service_estimates = [1.0 for _ in range(self.n_locations)]

        # customer transition probability estimates (uniform prior)
        self.transition_estimates = [[(1 / self.n_locations) for _ in range(self.n_locations)] for _ in range(self.n_locations)]

        # reward estimates: [origin][location]
        self.reward_estimates = [[8.0 for _ in range(self.n_locations)] for _ in range(self.n_locations)]

        # fare estimates: [origin][location]
        self.fare_estimates = [[8.0 for _ in range(self.n_locations)] for _ in range(self.n_locations)]

        # subsidy estimates: [origin][start][end]
        self.subsidy_estimates = [[[0.0 for _ in range(self.n_locations)] for _ in range(self.n_locations)] for _ in range(self.n_locations)]

        self.waiting_time_estimates = [0.5 for _ in range(self.n_locations)]

        self.time_window = 2

        # Accumulator buffers for deferred EWMA updates
        self._spawn_buffer = [[] for _ in range(self.n_locations)]
        self._service_buffer = [[] for _ in range(self.n_locations)]
        self._transition_buffer = []
        self._reward_buffer = [[[] for _ in range(self.n_locations)] for _ in range(self.n_locations)]
        self._fare_buffer = [[[] for _ in range(self.n_locations)] for _ in range(self.n_locations)]
        self._subsidy_buffer = [[[[] for _ in range(self.n_locations)] for _ in range(self.n_locations)] for _ in range(self.n_locations)]
        self._w_buffer = [[] for _ in range(self.n_locations)]

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
        self.rate_tracker.queue_lengths = queue_lengths

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
        self._fare_buffer[origin][location].append(fare)

    def observe_subsidy(self, origin, start, end, subsidy):
        self._subsidy_buffer[origin][start][end].append(subsidy)

    def update_estimator(self):
        # Spawn buffer
        for loc in range(self.n_locations):
            if self._spawn_buffer[loc]:
                mean_val = sum(self._spawn_buffer[loc]) / len(self._spawn_buffer[loc])
                self.inter_spawn_estimates[loc] = self.alpha_spawn * self.inter_spawn_estimates[loc] + (1 - self.alpha_spawn) * mean_val
                self._spawn_buffer[loc].clear()

        # Service buffer
        for loc in range(self.n_locations):
            if self._service_buffer[loc]:
                mean_val = sum(self._service_buffer[loc]) / len(self._service_buffer[loc])
                self.inter_service_estimates[loc] = self.alpha_service * self.inter_service_estimates[loc] + (1 - self.alpha_service) * mean_val
                self._service_buffer[loc].clear()

        # Transition buffer
        if self._transition_buffer:
            # Count transitions per start location
            counts = [[0] * self.n_locations for _ in range(self.n_locations)]
            row_totals = [0] * self.n_locations
            for start, end in self._transition_buffer:
                counts[start][end] += 1
                row_totals[start] += 1
            # EWMA blend row-by-row for rows that have observations
            for i in range(self.n_locations):
                if row_totals[i] > 0:
                    for j in range(self.n_locations):
                        empirical = counts[i][j] / row_totals[i]
                        self.transition_estimates[i][j] = self.alpha_transition * self.transition_estimates[i][j] + (1 - self.alpha_transition) * empirical
            self._transition_buffer.clear()

        # Reward buffer
        for origin in range(self.n_locations):
            for loc in range(self.n_locations):
                if self._reward_buffer[origin][loc]:
                    mean_val = sum(self._reward_buffer[origin][loc]) / len(self._reward_buffer[origin][loc])
                    self.reward_estimates[origin][loc] = self.alpha_reward * self.reward_estimates[origin][loc] + (1 - self.alpha_reward) * mean_val
                    self._reward_buffer[origin][loc].clear()

        # Fare buffer
        for origin in range(self.n_locations):
            for loc in range(self.n_locations):
                if self._fare_buffer[origin][loc]:
                    mean_val = sum(self._fare_buffer[origin][loc]) / len(self._fare_buffer[origin][loc])
                    self.fare_estimates[origin][loc] = self.alpha_reward * self.fare_estimates[origin][loc] + (1 - self.alpha_reward) * mean_val
                    self._fare_buffer[origin][loc].clear()

        # Subsidy buffer
        for origin in range(self.n_locations):
            for start in range(self.n_locations):
                for end in range(self.n_locations):
                    if self._subsidy_buffer[origin][start][end]:
                        mean_val = sum(self._subsidy_buffer[origin][start][end]) / len(self._subsidy_buffer[origin][start][end])
                        self.subsidy_estimates[origin][start][end] = self.alpha_subsidy * self.subsidy_estimates[origin][start][end] + (1 - self.alpha_subsidy) * mean_val
                        self._subsidy_buffer[origin][start][end].clear()

        # Waiting time buffer
        for loc in range(self.n_locations):
            if self._w_buffer[loc]:
                mean_val = sum(self._w_buffer[loc]) / len(self._w_buffer[loc])
                self.waiting_time_estimates[loc] = self.alpha_w * self.waiting_time_estimates[loc] + (1 - self.alpha_w) * mean_val
                self._w_buffer[loc].clear()

    def get_arrival_rates(self):
        return [1.0 / self.inter_spawn_estimates[i] for i in range(self.n_locations)]

    def get_service_rates(self):
        return [1.0 / self.inter_service_estimates[i] for i in range(self.n_locations)]

    def get_config(self, exit_prob):
        return ModelConfig(
            grid=self.grid,
            period=self.period,
            arrival_rates=self.get_arrival_rates(),
            service_rates=self.get_service_rates(),
            vehicle_rewards=self.reward_estimates,
            producer_rewards=self.fare_estimates,
            exit_prob=exit_prob,
            customer_transitions=self.transition_estimates
        )
