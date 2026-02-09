from util import N_CLUSTERS
from model_config import ModelConfig

class RateTracker:
    def __init__(self, n_locations):
        self.n_locations = n_locations
        self.last_spawn_time = [0.0 for _ in range(n_locations)]
        self.last_service_time = [0.0 for _ in range(n_locations)]

    def reset(self, t):
        self.last_spawn_time = [t for _ in range(self.n_locations)]
        self.last_service_time = [t for _ in range(self.n_locations)]


class Estimator:
    def __init__(self, rate_tracker, grid, period):
        self.rate_tracker = rate_tracker
        self.grid = grid
        self.period = period
        self.n_locations = N_CLUSTERS

        # EWMA smoothing factors
        self.alpha_spawn = 0.9
        self.alpha_service = 0.9
        self.alpha_transition = 0.9
        self.alpha_reward = 0.8
        self.alpha_subsidy = 0.8

        # inter-spawn time estimates (per location)
        self.inter_spawn_estimates = [1.0 for _ in range(self.n_locations)]

        # inter-service time estimates (per location)
        self.inter_service_estimates = [1.0 for _ in range(self.n_locations)]

        # customer transition probability estimates (uniform prior)
        self.transition_estimates = [[(1 / self.n_locations) for _ in range(self.n_locations)] for _ in range(self.n_locations)]

        # reward estimates: [origin][location]
        self.reward_estimates = [[10.0 for _ in range(self.n_locations)] for _ in range(self.n_locations)]

        # fare estimates: [origin][location]
        self.fare_estimates = [[10.0 for _ in range(self.n_locations)] for _ in range(self.n_locations)]

        # subsidy estimates: [origin][start][end]
        self.subsidy_estimates = [[[0.0 for _ in range(self.n_locations)] for _ in range(self.n_locations)] for _ in range(self.n_locations)]

    def observe_spawn(self, location, t):
        inter_spawn = t - self.rate_tracker.last_spawn_time[location]
        self.inter_spawn_estimates[location] = (self.alpha_spawn * self.inter_spawn_estimates[location]) + ((1 - self.alpha_spawn) * inter_spawn)
        self.rate_tracker.last_spawn_time[location] = t

    def observe_service(self, location, t):
        inter_service = t - self.rate_tracker.last_service_time[location]
        self.inter_service_estimates[location] = (self.alpha_service * self.inter_service_estimates[location]) + ((1 - self.alpha_service) * inter_service)
        self.rate_tracker.last_service_time[location] = t

    def observe_transition(self, start, end):
        for j in range(self.n_locations):
            self.transition_estimates[start][j] = self.alpha_transition * self.transition_estimates[start][j]
        self.transition_estimates[start][end] += (1 - self.alpha_transition)

    def observe_reward(self, origin, location, reward):
        reward = min(reward, 50)
        self.reward_estimates[origin][location] = (self.alpha_reward * self.reward_estimates[origin][location]) + ((1 - self.alpha_reward) * reward)

    def observe_fare(self, origin, location, fare):
        self.fare_estimates[origin][location] = (self.alpha_reward * self.fare_estimates[origin][location]) + ((1 - self.alpha_reward) * fare)

    def observe_subsidy(self, origin, start, end, subsidy):
        self.subsidy_estimates[origin][start][end] = (self.alpha_subsidy * self.subsidy_estimates[origin][start][end]) + ((1 - self.alpha_subsidy) * subsidy)

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
