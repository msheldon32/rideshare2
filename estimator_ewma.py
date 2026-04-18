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
        self.last_arrival_time_in_period = [[float("inf") for _ in range(n_locations)] for _ in range(N_PERIODS)]

    def reset(self, t):
        self.last_spawn_time = [t for _ in range(self.n_locations)]
        self.last_service_time = [t for _ in range(self.n_locations)]
        self.last_arrival_time = [t for _ in range(self.n_locations)]
        self.queue_lengths = [0 for _ in range(self.n_locations)]
        for loc in range(self.n_locations):
            self.services[loc].clear()
        self.last_arrival_time_in_period = [[float("inf") for _ in range(self.n_locations)] for _ in range(N_PERIODS)]

    def flush(self, t):
        self.last_spawn_time = [t for _ in range(self.n_locations)]
        self.last_service_time = [t for _ in range(self.n_locations)]
        self.last_arrival_time = [t for _ in range(self.n_locations)]
        for loc in range(self.n_locations):
            self.services[loc].clear()
        self.last_arrival_time_in_period = [[float("inf") for _ in range(self.n_locations)] for _ in range(N_PERIODS)]


class Estimator:
    def __init__(self, rate_tracker, grid, period, controller, use_fare_tax=False, alpha=0, ewma_alpha=0.5):
        self.rate_tracker = rate_tracker
        self.grid = grid
        self.period = period
        self.n_locations = N_CLUSTERS
        self.controller = controller

        self.use_fare_tax = use_fare_tax
        self.tax_scale = 0.0
        self.time_window = 2
        self.ewma_alpha = ewma_alpha
        self.alpha = alpha

        n = self.n_locations

        # ------------------------------------------------------------------
        # Raw observation buffers — cleared on each update_estimator() call
        # ------------------------------------------------------------------
        self._spawn_buf      = [[] for _ in range(n)]
        self._service_buf    = [[] for _ in range(n)]
        self._arrival_buf    = [[] for _ in range(n)]
        self._w_buf          = [[] for _ in range(n)]
        self._queue_buf      = [[] for _ in range(n)]
        self._fare_buf       = [[] for _ in range(n)]
        self._tax_buf        = [[] for _ in range(n)]
        self._reward_buf     = [[[] for _ in range(n)] for _ in range(n)]
        self._transition_buf = []
        self._subsidy_buf    = [[[[] for _ in range(n)] for _ in range(n)] for _ in range(n)]

        # ------------------------------------------------------------------
        # Means lists — one entry per update_estimator() call, cleared on flush()
        # ------------------------------------------------------------------
        self._spawn_means      = [[] for _ in range(n)]
        self._service_means    = [[] for _ in range(n)]
        self._arrival_means    = [[] for _ in range(n)]
        self._w_means          = [[] for _ in range(n)]
        self._queue_means      = [[] for _ in range(n)]
        self._fare_means       = [[] for _ in range(n)]
        self._tax_means        = [[] for _ in range(n)]
        self._reward_means     = [[[] for _ in range(n)] for _ in range(n)]
        self._transition_means = [[[] for _ in range(n)] for _ in range(n)]
        self._subsidy_means    = [[[[] for _ in range(n)] for _ in range(n)] for _ in range(n)]

        # ------------------------------------------------------------------
        # EWMA point estimates — updated on flush(), initialised to priors
        # ------------------------------------------------------------------
        self.spawn_est      = [1.0         for _ in range(n)]
        self.service_est    = [0.5         for _ in range(n)]
        self.arrival_est    = [1.0         for _ in range(n)]
        self.w_est          = [0.5         for _ in range(n)]
        self.queue_est      = [0.0         for _ in range(n)]
        self.fare_est       = [10.0        for _ in range(n)]
        self.tax_est        = [0.0         for _ in range(n)]
        self.reward_est     = [[10.0] * n  for _ in range(n)]
        self.transition_est = [[1.0 / n] * n for _ in range(n)]
        self.subsidy_est    = [[[0.0] * n  for _ in range(n)] for _ in range(n)]

        # aliases expected by get_config() and simulator
        self.reward_estimates = self.reward_est
        self.fare_estimates   = self.fare_est
        self.tax_estimates    = self.tax_est

    def clean_rewards(self, t):
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ewma(self, old, new):
        return self.ewma_alpha * old + (1.0 - self.ewma_alpha) * new

    def _flush_1d(self, means, est, default=None):
        """EWMA-update a 1-D list of point estimates from their means lists."""
        for i in range(self.n_locations):
            if means[i]:
                m = sum(means[i]) / len(means[i])
                est[i] = self._ewma(est[i], m)
                means[i].clear()
            elif default is not None:
                est[i] = self._ewma(est[i], default)

    def _flush_2d(self, means, est, default=None):
        for i in range(self.n_locations):
            for j in range(self.n_locations):
                if means[i][j]:
                    m = sum(means[i][j]) / len(means[i][j])
                    est[i][j] = self._ewma(est[i][j], m)
                    means[i][j].clear()
                elif default is not None:
                    est[i][j] = self._ewma(est[i][j], default)

    def _flush_3d(self, means, est, default=None):
        for i in range(self.n_locations):
            for j in range(self.n_locations):
                for k in range(self.n_locations):
                    if means[i][j][k]:
                        m = sum(means[i][j][k]) / len(means[i][j][k])
                        est[i][j][k] = self._ewma(est[i][j][k], m)
                        means[i][j][k].clear()
                    elif default is not None:
                        est[i][j][k] = self._ewma(est[i][j][k], default)

    def update_w_estimates(self, t):
        for loc in range(self.n_locations):
            while self.rate_tracker.services[loc] and self.rate_tracker.services[loc][0] < t - self.time_window:
                self.rate_tracker.services[loc].popleft()
            self._w_buf[loc].append((1 + self.rate_tracker.queue_lengths[loc]) * self.service_est[loc])

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------

    def observe_queue_lengths(self, t, queue_lengths):
        self.update_w_estimates(t)
        self.rate_tracker.queue_lengths = queue_lengths
        for loc in range(self.n_locations):
            self._queue_buf[loc].append(queue_lengths[loc])

    def observe_spawn(self, location, t):
        self._spawn_buf[location].append(t - self.rate_tracker.last_spawn_time[location])
        self.rate_tracker.last_spawn_time[location] = t

    def observe_arrival(self, location, _class, t):
        self._arrival_buf[location].append(t - self.rate_tracker.last_arrival_time[location])
        self.rate_tracker.last_arrival_time[location] = t
        self.rate_tracker.last_arrival_time_in_period[self.period][location] = t

    def observe_service(self, location, t):
        self._service_buf[location].append(t - self.rate_tracker.last_service_time[location])
        self.rate_tracker.last_service_time[location] = t
        self.rate_tracker.services[location].append(t)

    def observe_transition(self, start, end):
        self._transition_buf.append((start, end))

    def observe_reward(self, origin, location, reward):
        self._reward_buf[origin][location].append(reward)

    def observe_fare(self, origin, location, fare):
        self._fare_buf[location].append(fare)

    def observe_tax(self, origin, location, tax):
        self._tax_buf[location].append(tax * self.tax_scale)

    def observe_subsidy(self, origin, start, end, subsidy):
        self._subsidy_buf[origin][start][end].append(subsidy)

    # ------------------------------------------------------------------
    # update_estimator: raw buffer -> mean -> means list, clear raw buffer
    # ------------------------------------------------------------------

    def update_estimator(self):
        for loc in range(self.n_locations):
            for buf, means in [
                (self._spawn_buf[loc],   self._spawn_means[loc]),
                (self._service_buf[loc], self._service_means[loc]),
                (self._arrival_buf[loc], self._arrival_means[loc]),
                (self._w_buf[loc],       self._w_means[loc]),
                (self._queue_buf[loc],   self._queue_means[loc]),
                (self._fare_buf[loc],    self._fare_means[loc]),
                (self._tax_buf[loc],     self._tax_means[loc]),
            ]:
                if buf:
                    means.append(sum(buf) / len(buf))
                    buf.clear()

        for origin in range(self.n_locations):
            for loc in range(self.n_locations):
                buf = self._reward_buf[origin][loc]
                if buf:
                    self._reward_means[origin][loc].append(sum(buf) / len(buf))
                    buf.clear()

        if self._transition_buf:
            counts = [[0] * self.n_locations for _ in range(self.n_locations)]
            row_totals = [0] * self.n_locations
            for start, end in self._transition_buf:
                counts[start][end] += 1
                row_totals[start] += 1
            for i in range(self.n_locations):
                if row_totals[i] > 0:
                    for j in range(self.n_locations):
                        self._transition_means[i][j].append(counts[i][j] / row_totals[i])
            self._transition_buf.clear()

        for origin in range(self.n_locations):
            for start in range(self.n_locations):
                for end in range(self.n_locations):
                    buf = self._subsidy_buf[origin][start][end]
                    if buf:
                        self._subsidy_means[origin][start][end].append(sum(buf) / len(buf))
                        buf.clear()

    # ------------------------------------------------------------------
    # flush: means list -> one EWMA step -> clear means list
    # ------------------------------------------------------------------

    def flush(self, t=None):
        self._flush_1d(self._spawn_means,   self.spawn_est)
        self._flush_1d(self._service_means, self.service_est)
        self._flush_1d(self._arrival_means, self.arrival_est)
        self._flush_1d(self._w_means,       self.w_est)
        self._flush_1d(self._queue_means,   self.queue_est)
        self._flush_1d(self._fare_means,    self.fare_est)
        self._flush_1d(self._tax_means,     self.tax_est, default=0.0)  # default to 0 if no tax observed
        self._flush_2d(self._reward_means,     self.reward_est)
        self._flush_2d(self._transition_means, self.transition_est)
        self._flush_3d(self._subsidy_means,    self.subsidy_est)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_arrival_rates(self):
        return [1.0 / s if s > 0 else 0.0 for s in self.spawn_est]

    def get_service_rates(self):
        return [1.0 / s if s > 0 else 0.0 for s in self.service_est]

    def get_queue_arrival_rates(self):
        return [1.0 / s if s > 0 else 0.0 for s in self.arrival_est]

    def get_config(self, exit_prob):
        adjusted_rewards = [[0.0] * self.n_locations for _ in range(self.n_locations)]
        adjusted_producer_rewards = [[0.0] * self.n_locations for _ in range(self.n_locations)]
        for _class in range(self.n_locations):
            for origin in range(self.n_locations):
                if self.use_fare_tax:
                    reward_est = self.fare_est[origin] - self.tax_est[origin]
                    other_est  = self.reward_est[_class][origin]
                    adjusted_rewards[_class][origin] = (1 - self.alpha) * reward_est + self.alpha * other_est
                else:
                    adjusted_rewards[_class][origin] = self.reward_est[_class][origin]
                adjusted_producer_rewards[_class][origin] = self.fare_est[origin]

        return ModelConfig(
            grid=self.grid,
            period=self.period,
            arrival_rates=self.get_arrival_rates(),
            service_rates=self.get_service_rates(),
            vehicle_rewards=adjusted_rewards,
            producer_rewards=adjusted_producer_rewards,
            exit_prob=exit_prob,
            customer_transitions=self.transition_est,
        )
