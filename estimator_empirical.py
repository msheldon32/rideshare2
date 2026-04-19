import bisect
from datetime import timedelta

from util import N_CLUSTERS, N_PERIODS, PERIOD_LENGTH, get_period
from model_config import ModelConfig


WINDOW_HOURS = 48


def active_window_end(t_start, target_active_hours, epoch):
    cur = t_start
    remaining = target_active_hours
    while remaining > 0:
        dt = epoch + timedelta(hours=cur)
        if dt.weekday() > 2:
            days_to_mon = (7 - dt.weekday()) % 7 or 7
            offset = days_to_mon * 24 - dt.hour - dt.minute/60 - dt.second/3600
            cur += offset
        else:
            hours_to_wed_end = (2 - dt.weekday()) * 24 + (24 - dt.hour - dt.minute/60 - dt.second/3600)
            take = min(hours_to_wed_end, remaining)
            cur += take
            remaining -= take
    return cur


def period_hours_in_window(t_start, t_end, period_idx, epoch):
    total = 0.0
    cur = t_start
    while cur < t_end:
        dt = epoch + timedelta(hours=cur)
        if dt.weekday() > 2:
            days_to_mon = (7 - dt.weekday()) % 7 or 7
            offset = days_to_mon * 24 - dt.hour - dt.minute/60 - dt.second/3600
            cur = min(cur + offset, t_end)
            continue
        hour_in_day = dt.hour + dt.minute/60 + dt.second/3600
        cur_period = int(hour_in_day // PERIOD_LENGTH)
        next_boundary_hod = (cur_period + 1) * PERIOD_LENGTH
        hours_to_boundary = next_boundary_hod - hour_in_day
        hours_to_active_end = (2 - dt.weekday()) * 24 + (24 - hour_in_day)
        nxt = min(cur + hours_to_boundary, cur + hours_to_active_end, t_end)
        if cur_period == period_idx:
            total += nxt - cur
        cur = nxt
    return total


class TraceStatistics:
    def __init__(self, requests, spawn_events, epoch):
        self.epoch = epoch
        self.requests = sorted(requests, key=lambda r: r.time)
        self.spawn_events = sorted(spawn_events, key=lambda e: e[0])
        self.req_times = [r.time for r in self.requests]
        self.spawn_times = [e[0] for e in self.spawn_events]
        self._cached_t = None
        self._cached_stats = None

        # Overall fare means across the whole dataset (active days only),
        # per (period, cluster). Used as a stable reference instead of the
        # lookahead window so policy reward signals don't shift run to run.
        n = N_CLUSTERS
        all_request_counts = [[0]   * n for _ in range(N_PERIODS)]
        all_fare_sum       = [[0.0] * n for _ in range(N_PERIODS)]
        all_gross_fare_sum = [[0.0] * n for _ in range(N_PERIODS)]
        for req in self.requests:
            if (epoch + timedelta(hours=req.time)).weekday() > 2:
                continue
            p, i = req.period, req.start_cluster
            all_request_counts[p][i] += 1
            all_fare_sum[p][i]       += req.net_fare_cents  / 100
            all_gross_fare_sum[p][i] += req.gross_fare_cents / 100
        self.fare_mean = [
            [(all_fare_sum[p][i]       / all_request_counts[p][i]) if all_request_counts[p][i] > 0 else 0.0
             for i in range(n)] for p in range(N_PERIODS)
        ]
        self.gross_fare_mean = [
            [(all_gross_fare_sum[p][i] / all_request_counts[p][i]) if all_request_counts[p][i] > 0 else 0.0
             for i in range(n)] for p in range(N_PERIODS)
        ]

    def get_window_stats(self, t):
        if self._cached_t == t and self._cached_stats is not None:
            return self._cached_stats

        n = N_CLUSTERS
        t_end = active_window_end(t, WINDOW_HOURS, self.epoch)

        request_counts    = [[0]   * n for _ in range(N_PERIODS)]
        transition_counts = [[[0]  * n for _ in range(n)] for _ in range(N_PERIODS)]
        spawn_counts      = [[0]   * n for _ in range(N_PERIODS)]

        lo_r = bisect.bisect_left(self.req_times, t)
        hi_r = bisect.bisect_right(self.req_times, t_end)
        for k in range(lo_r, hi_r):
            req = self.requests[k]
            if (self.epoch + timedelta(hours=req.time)).weekday() > 2:
                continue
            p, i, j = req.period, req.start_cluster, req.end_cluster
            request_counts[p][i] += 1
            transition_counts[p][i][j] += 1

        lo_s = bisect.bisect_left(self.spawn_times, t)
        hi_s = bisect.bisect_right(self.spawn_times, t_end)
        for k in range(lo_s, hi_s):
            ev = self.spawn_events[k]
            ts, p, cluster = ev[0], ev[1], ev[2]
            if (self.epoch + timedelta(hours=ts)).weekday() > 2:
                continue
            spawn_counts[p][cluster] += 1

        period_h = [period_hours_in_window(t, t_end, p, self.epoch) for p in range(N_PERIODS)]

        spawn_rate = [[(spawn_counts[p][i]   / period_h[p]) if period_h[p] > 0 else 0.0
                       for i in range(n)] for p in range(N_PERIODS)]
        service_rate = [[(request_counts[p][i] / period_h[p]) if period_h[p] > 0 else 0.0
                         for i in range(n)] for p in range(N_PERIODS)]

        transition = []
        for p in range(N_PERIODS):
            mat = []
            for i in range(n):
                row_total = sum(transition_counts[p][i])
                if row_total > 0:
                    mat.append([transition_counts[p][i][j] / row_total for j in range(n)])
                else:
                    mat.append([1.0 / n for _ in range(n)])
            transition.append(mat)

        stats = {
            "spawn_rate":      spawn_rate,
            "service_rate":    service_rate,
            "fare_mean":       self.fare_mean,
            "gross_fare_mean": self.gross_fare_mean,
            "transition":      transition,
        }
        self._cached_t = t
        self._cached_stats = stats
        return stats


class Estimator:
    def __init__(self, rate_tracker, grid, period, controller, trace_stats,
                 use_fare_tax=False, alpha=0, ewma_alpha=0.5, decay_tax=False):
        self.rate_tracker = rate_tracker
        self.grid = grid
        self.period = period
        self.controller = controller
        self.n_locations = N_CLUSTERS
        self.use_fare_tax = use_fare_tax
        self.alpha = alpha
        self.ewma_alpha = ewma_alpha
        self.decay_tax = decay_tax
        self.tax_scale = 0.0
        self.trace_stats = trace_stats

        n = self.n_locations

        # initial window seeded at t=0; will be refreshed on every flush(t)
        stats = trace_stats.get_window_stats(0.0)
        self.spawn_rate          = list(stats["spawn_rate"][period])
        self.service_rate        = list(stats["service_rate"][period])
        self.fare_est            = list(stats["fare_mean"][period])
        self.producer_reward_est = list(stats["gross_fare_mean"][period])
        self.transition_est      = [list(stats["transition"][period][i]) for i in range(n)]
        self.reward_est          = [[stats["fare_mean"][period][i] for i in range(n)] for _ in range(n)]

        self.tax_est    = [0.0 for _ in range(n)]
        self._tax_buf   = [[] for _ in range(n)]
        self._tax_means = [[] for _ in range(n)]

        self.tax_estimates    = self.tax_est
        self.fare_estimates   = self.fare_est
        self.reward_estimates = self.reward_est

        self.queue_est = [0.0 for _ in range(n)]
        self.w_est     = [0.0 for _ in range(n)]

    def clean_rewards(self, t):
        pass

    def observe_queue_lengths(self, t, queue_lengths):
        pass

    def observe_spawn(self, location, t):
        pass

    def observe_arrival(self, location, _class, t):
        pass

    def observe_service(self, location, t):
        pass

    def observe_transition(self, start, end):
        pass

    def observe_reward(self, origin, location, reward):
        pass

    def observe_fare(self, origin, location, fare):
        pass

    def observe_tax(self, origin, location, tax):
        self._tax_buf[location].append(tax * self.tax_scale)

    def observe_subsidy(self, origin, start, end, subsidy):
        pass

    def update_estimator(self):
        for loc in range(self.n_locations):
            buf = self._tax_buf[loc]
            if buf:
                self._tax_means[loc].append(sum(buf) / len(buf))
                buf.clear()

    def flush(self, t):
        n = self.n_locations
        stats = self.trace_stats.get_window_stats(t)
        p = self.period
        self.spawn_rate          = list(stats["spawn_rate"][p])
        self.service_rate        = list(stats["service_rate"][p])
        self.fare_est            = list(stats["fare_mean"][p])
        self.producer_reward_est = list(stats["gross_fare_mean"][p])
        self.transition_est      = [list(stats["transition"][p][i]) for i in range(n)]
        self.reward_est          = [[stats["fare_mean"][p][i] for i in range(n)] for _ in range(n)]
        self.fare_estimates   = self.fare_est
        self.reward_estimates = self.reward_est

        for loc in range(self.n_locations):
            if self._tax_means[loc]:
                m = sum(self._tax_means[loc]) / len(self._tax_means[loc])
                self.tax_est[loc] = self.ewma_alpha * self.tax_est[loc] + (1 - self.ewma_alpha) * m
                self._tax_means[loc].clear()
            elif self.decay_tax:
                self.tax_est[loc] = self.ewma_alpha * self.tax_est[loc]

    def get_arrival_rates(self):
        return list(self.spawn_rate)

    def get_service_rates(self):
        return list(self.service_rate)

    def get_queue_arrival_rates(self):
        return list(self.spawn_rate)

    def get_config(self, exit_prob):
        n = self.n_locations
        adjusted_rewards          = [[0.0] * n for _ in range(n)]
        adjusted_producer_rewards = [[0.0] * n for _ in range(n)]
        for k in range(n):
            for i in range(n):
                if self.use_fare_tax:
                    reward_est = self.fare_est[i] - self.tax_est[i]
                    other_est  = self.reward_est[k][i]
                    adjusted_rewards[k][i] = (1 - self.alpha) * reward_est + self.alpha * other_est
                else:
                    adjusted_rewards[k][i] = self.reward_est[k][i]
                adjusted_producer_rewards[k][i] = self.fare_est[i]

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
