from util import N_CLUSTERS, N_PERIODS
from model_config import ModelConfig


class ConstantStatistics:
    """Synthetic-rate stats pulled directly from the requester/spawner Poisson
    generators. Mirrors the dict shape produced by
    estimator_empirical.TraceStatistics so the Estimator below can be a drop-in
    replacement.
    """

    def __init__(self, requester, spawner):
        n = N_CLUSTERS

        spawn_rate = [[spawner.rates[p][i][i] for i in range(n)] for p in range(N_PERIODS)]

        service_rate = [[requester.rates[p][i] for i in range(n)] for p in range(N_PERIODS)]

        fare_mean = [[requester._net_rewards.get((p, i), 0) / 100 for i in range(n)] for p in range(N_PERIODS)]
        gross_fare_mean = [[requester._gross_rewards.get((p, i), 0) / 100 for i in range(n)] for p in range(N_PERIODS)]

        transition = []
        for p in range(N_PERIODS):
            mat = []
            for i in range(n):
                key = (p, i)
                row = [0.0] * n
                if key in requester._dest_ends:
                    ends = requester._dest_ends[key]
                    probs = requester._dest_probs[key]
                    total = sum(probs)
                    if total > 0:
                        for end, prob in zip(ends, probs):
                            row[end] = prob / total
                    else:
                        row = [1.0 / n for _ in range(n)]
                else:
                    row = [1.0 / n for _ in range(n)]
                mat.append(row)
            transition.append(mat)

        self._stats = {
            "spawn_rate":      spawn_rate,
            "service_rate":    service_rate,
            "fare_mean":       fare_mean,
            "gross_fare_mean": gross_fare_mean,
            "transition":      transition,
        }

        self.fare_mean = fare_mean
        self.gross_fare_mean = gross_fare_mean

    def get_window_stats(self, t):
        return self._stats


class Estimator:
    def __init__(self, rate_tracker, grid, period, controller, trace_stats,
                 use_fare_tax=False, alpha=0, ewma_alpha=0.5, decay_tax=True,
                 swap_reward_fare=False, ptg=0.0):
        self.rate_tracker = rate_tracker
        self.grid = grid
        self.period = period
        self.controller = controller
        self.n_locations = N_CLUSTERS
        self.use_fare_tax = use_fare_tax
        self.alpha = alpha
        self.ewma_alpha = ewma_alpha
        self.decay_tax = decay_tax
        self.swap_reward_fare = swap_reward_fare
        self.ptg = ptg
        self.tax_scale = 1.0
        self.trace_stats = trace_stats

        n = self.n_locations

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
        return [r + 0.01 for r in self.spawn_rate]

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
                if self.swap_reward_fare:
                    adjusted_rewards[k][i] = self.fare_est[i] - self.ptg * self.producer_reward_est[i]
                elif self.use_fare_tax:
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
