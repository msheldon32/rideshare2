from util import N_CLUSTERS
from model_config import ModelConfig


class Estimator:
    def __init__(self, grid, period):
        self.grid = grid
        self.period = period
        self.n_locations = N_CLUSTERS

        # EWMA smoothing factors
        self.alpha_spawn = 0.9
        self.alpha_service = 0.9
        self.alpha_transition = 0.9

        # inter-spawn time estimates (per location)
        self.inter_spawn_estimates = [1.0 for _ in range(self.n_locations)]
        self.last_spawn_time = [0.0 for _ in range(self.n_locations)]

        # inter-service time estimates (per location)
        self.inter_service_estimates = [1.0 for _ in range(self.n_locations)]
        self.last_service_time = [0.0 for _ in range(self.n_locations)]

        # customer transition probability estimates (uniform prior)
        self.transition_estimates = [[(1 / self.n_locations) for _ in range(self.n_locations)] for _ in range(self.n_locations)]

    def observe_spawn(self, location, t):
        inter_spawn = t - self.last_spawn_time[location]
        self.inter_spawn_estimates[location] = (self.alpha_spawn * self.inter_spawn_estimates[location]) + ((1 - self.alpha_spawn) * inter_spawn)
        self.last_spawn_time[location] = t

    def observe_service(self, location, t):
        inter_service = t - self.last_service_time[location]
        self.inter_service_estimates[location] = (self.alpha_service * self.inter_service_estimates[location]) + ((1 - self.alpha_service) * inter_service)
        self.last_service_time[location] = t

    def observe_transition(self, start, end):
        for j in range(self.n_locations):
            self.transition_estimates[start][j] = self.alpha_transition * self.transition_estimates[start][j]
        self.transition_estimates[start][end] += (1 - self.alpha_transition)

    def get_arrival_rates(self):
        return [1.0 / self.inter_spawn_estimates[i] for i in range(self.n_locations)]

    def get_service_rates(self):
        return [1.0 / self.inter_service_estimates[i] for i in range(self.n_locations)]

    def get_config(self, vehicle_rewards, producer_rewards, exit_prob):
        return ModelConfig(
            grid=self.grid,
            period=self.period,
            arrival_rates=self.get_arrival_rates(),
            service_rates=self.get_service_rates(),
            vehicle_rewards=vehicle_rewards,
            producer_rewards=producer_rewards,
            exit_prob=exit_prob,
            customer_transitions=self.transition_estimates
        )
