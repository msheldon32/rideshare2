from util import N_CLUSTERS, N_PERIODS
from model_config import ModelConfig

import collections


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

    def flush(self, t):
        self.last_spawn_time = [t for _ in range(self.n_locations)]
        self.last_service_time = [t for _ in range(self.n_locations)]
        for loc in range(self.n_locations):
            self.services[loc].clear()
        self.last_arrival_time_in_period = [[float("inf") for _ in range(self.n_locations)] for _ in range(N_PERIODS)]


class Estimator:
    def __init__(self, rate_tracker, grid, period, controller):
        self.rate_tracker = rate_tracker
        self.grid = grid
        self.period = period
        self.n_locations = N_CLUSTERS
        self.controller = controller

        self.time_window = 2

        # --- Observation buffers (raw events since last update_estimator call) ---
        self._spawn_buffer = [[] for _ in range(self.n_locations)]
        self._service_buffer = [[] for _ in range(self.n_locations)]
        self._transition_buffer = []
        self._reward_buffer = [[[] for _ in range(self.n_locations)] for _ in range(self.n_locations)]
        self._fare_buffer = [[] for _ in range(self.n_locations)]
        self._tax_buffer = [[] for _ in range(self.n_locations)]
        self._subsidy_buffer = [[[[] for _ in range(self.n_locations)] for _ in range(self.n_locations)] for _ in range(self.n_locations)]
        self._w_buffer = [[] for _ in range(self.n_locations)]
        self._queue_buffer = [[] for _ in range(self.n_locations)]

        # --- Means buffers (one entry per update_estimator call) ---
        self._spawn_means = [[] for _ in range(self.n_locations)]
        self._service_means = [[] for _ in range(self.n_locations)]
        self._transition_means = [[[] for _ in range(self.n_locations)] for _ in range(self.n_locations)]
        self._subsidy_means = [[[[] for _ in range(self.n_locations)] for _ in range(self.n_locations)] for _ in range(self.n_locations)]
        self._w_means = [[] for _ in range(self.n_locations)]
        self._queue_means = [[] for _ in range(self.n_locations)]

        # --- Priors (used when means buffers are empty) ---
        self._prior_spawn = 1.0
        self._prior_service = 1.0
        self._prior_transition = 1.0 / self.n_locations
        self._prior_subsidy = 0.0
        self._prior_w = 0.5
        self._prior_queue = 0.0

        # --- Estimates updated on flush() ---
        self.reward_estimates = [[10.0] * self.n_locations for _ in range(self.n_locations)]
        self.fare_estimates = [10.0 for _ in range(self.n_locations)]
        self.tax_estimates = [0.0 for _ in range(self.n_locations)]

    def clean_rewards(self, t):
        # no-op in mean estimator (no EWMA state to nudge)
        pass

    def update_w_estimates(self, t):
        for loc in range(self.n_locations):
            while len(self.rate_tracker.services[loc]) > 0 and self.rate_tracker.services[loc][0] < t - self.time_window:
                self.rate_tracker.services[loc].popleft()

            new_w = (1 + self.rate_tracker.queue_lengths[loc]) * self._mean_or_prior(self._service_means[loc], self._prior_service)
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
        self._reward_buffer[origin][location].append(reward)

    def observe_fare(self, origin, location, fare):
        self._fare_buffer[location].append(fare)

    def observe_tax(self, origin, location, tax):
        self._tax_buffer[location].append(tax)

    def observe_subsidy(self, origin, start, end, subsidy):
        self._subsidy_buffer[origin][start][end].append(subsidy)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mean_or_prior(buf, prior):
        return sum(buf) / len(buf) if buf else prior

    # ------------------------------------------------------------------
    # update_estimator: flush observation buffers -> means buffers
    # ------------------------------------------------------------------

    def update_estimator(self):
        # Spawn
        for loc in range(self.n_locations):
            if self._spawn_buffer[loc]:
                self._spawn_means[loc].append(sum(self._spawn_buffer[loc]) / len(self._spawn_buffer[loc]))
                self._spawn_buffer[loc].clear()

        # Service
        for loc in range(self.n_locations):
            if self._service_buffer[loc]:
                self._service_means[loc].append(sum(self._service_buffer[loc]) / len(self._service_buffer[loc]))
                self._service_buffer[loc].clear()

        # Transition
        if self._transition_buffer:
            counts = [[0] * self.n_locations for _ in range(self.n_locations)]
            row_totals = [0] * self.n_locations
            for start, end in self._transition_buffer:
                counts[start][end] += 1
                row_totals[start] += 1
            for i in range(self.n_locations):
                if row_totals[i] > 0:
                    for j in range(self.n_locations):
                        self._transition_means[i][j].append(counts[i][j] / row_totals[i])
            self._transition_buffer.clear()

        # Reward, fare, and tax buffers are flushed in flush(), not here

        # Subsidy
        for origin in range(self.n_locations):
            for start in range(self.n_locations):
                for end in range(self.n_locations):
                    if self._subsidy_buffer[origin][start][end]:
                        self._subsidy_means[origin][start][end].append(
                            sum(self._subsidy_buffer[origin][start][end]) / len(self._subsidy_buffer[origin][start][end])
                        )
                        self._subsidy_buffer[origin][start][end].clear()

        # Waiting time
        for loc in range(self.n_locations):
            if self._w_buffer[loc]:
                self._w_means[loc].append(sum(self._w_buffer[loc]) / len(self._w_buffer[loc]))
                self._w_buffer[loc].clear()

        # Queue length
        for loc in range(self.n_locations):
            if self._queue_buffer[loc]:
                self._queue_means[loc].append(sum(self._queue_buffer[loc]) / len(self._queue_buffer[loc]))
                self._queue_buffer[loc].clear()

    # ------------------------------------------------------------------
    # flush: clear all means buffers (resets accumulated history)
    # ------------------------------------------------------------------

    def flush(self):
        # Clear means buffers
        for loc in range(self.n_locations):
            self._spawn_means[loc].clear()
            self._service_means[loc].clear()
            self._w_means[loc].clear()
            self._queue_means[loc].clear()
        for i in range(self.n_locations):
            for j in range(self.n_locations):
                self._transition_means[i][j].clear()
        for origin in range(self.n_locations):
            for start in range(self.n_locations):
                for end in range(self.n_locations):
                    self._subsidy_means[origin][start][end].clear()

        # Rewards: use mean of observations since last flush, else keep last value
        for origin in range(self.n_locations):
            for loc in range(self.n_locations):
                buf = self._reward_buffer[origin][loc]
                if buf:
                    self.reward_estimates[origin][loc] = sum(buf) / len(buf)
                buf.clear()

        # Fares: use mean of observations since last flush, else keep last value
        for loc in range(self.n_locations):
            buf = self._fare_buffer[loc]
            if buf:
                self.fare_estimates[loc] = sum(buf) / len(buf)
            buf.clear()

        # Taxes: use mean of observations since last flush, else default to 0
        for loc in range(self.n_locations):
            buf = self._tax_buffer[loc]
            self.tax_estimates[loc] = sum(buf) / len(buf) if buf else 0.0
            buf.clear()

    # ------------------------------------------------------------------
    # Accessors — compute mean of means buffers, fall back to prior
    # ------------------------------------------------------------------

    def get_inter_spawn_estimates(self):
        return [self._mean_or_prior(self._spawn_means[i], self._prior_spawn) for i in range(self.n_locations)]

    def get_inter_service_estimates(self):
        return [self._mean_or_prior(self._service_means[i], self._prior_service) for i in range(self.n_locations)]

    def get_transition_estimates(self):
        return [
            [self._mean_or_prior(self._transition_means[i][j], self._prior_transition) for j in range(self.n_locations)]
            for i in range(self.n_locations)
        ]

    def get_arrival_rates(self):
        return [1.0 / s if s > 0 else 0.0 for s in self.get_inter_spawn_estimates()]

    def get_service_rates(self):
        return [1.0 / s if s > 0 else 0.0 for s in self.get_inter_service_estimates()]

    def get_config(self, exit_prob):
        transitions = self.get_transition_estimates()

        adjusted_rewards = [[0.0] * self.n_locations for _ in range(self.n_locations)]
        for _class in range(self.n_locations):
            for origin in range(self.n_locations):
                origin_return_cost = self.grid.get_travel_cost(origin, _class, self.period)
                expected_dest_return_cost = sum(
                    transitions[origin][dest] * self.grid.get_travel_cost(dest, _class, self.period)
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
            customer_transitions=transitions
        )
