from util import *

class ModelConfig:
    def __init__(self, grid, period, arrival_rates, service_rates,
                 vehicle_rewards, producer_rewards, exit_prob, customer_transitions):
        self.grid = grid
        self.period = period
        self.n_locations = N_CLUSTERS
        self.locations = [i for i in range(self.n_locations)]

        self.arrival_rates = arrival_rates
        self.service_rates = service_rates
        self.vehicle_rewards = vehicle_rewards      # n_locations x n_locations: [k][i] where k=origin, i=queue location
        self.producer_rewards = producer_rewards    # n_locations x n_locations: [k][i] where k=origin, i=queue location
        self.exit_prob = exit_prob
        self.customer_transitions = customer_transitions
        self.reservation = RESERVATION
        self.cost_per_distance = COST_PER_MILE

    def get_prepaid_cost(self, k, i, j):
        if i == j:
            return 0
        return self.grid.get_prepaid_cost(k, i, j, self.period)
    
    def get_potential_change(self, k, i, j):
        if i == j:
            return 0
        return self.grid.get_potential_change(k, i, j, self.period)

    def cost_to(self, i, j):
        if i == j:
            return 0
        return self.grid.get_travel_cost(i, j, self.period)

    def get_rebalance_cost(self, k, i, j):
        return self.cost_to(i,j) + self.get_potential_change(k,i,j)
