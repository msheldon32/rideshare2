from util import *

import random


class Exploration:
    def __init__(self):
        self.boltzmann_tau = 0.2
        self.min_boltzmann = 0.2
        self.boltzmann_decay = 0.99995

    def decay(self):
        self.boltzmann_tau = self.min_boltzmann + self.boltzmann_decay*(self.boltzmann_tau - self.min_boltzmann)

class DriverModel:
    def __init__(self, grid, period, destination, estimator, exit_prob, exploration):
        self.grid = grid
        self.estimator = estimator
        self.period = period
        self.destination = destination
        self.exit_prob = exit_prob
        self.n_actions = N_CLUSTERS + 1
        self.exploration = exploration

        self.bellman_iterations = 15

    def get_w_estimate(self, cluster):
        #q = getattr(self.estimator, 'queue_lengths', [0]*N_CLUSTERS)[cluster]
        #return (1 + q) * self.estimator.inter_service_estimates[cluster]
        return self.estimator.waiting_time_estimates[cluster]

    def incremental_rewards(self, t):
        r = [[0 for i in range(self.n_actions)] for j in range(N_CLUSTERS)]

        self.estimator.update_w_estimates(t)

        for cluster in range(N_CLUSTERS):
            # cost of leaving
            if cluster == self.destination:
                r[cluster][-1] = 0
            else:
                r[cluster][-1] = -self.grid.get_rebalance_cost(cluster, self.destination, self.period)

            # cost of transiting
            for other_cluster in range(N_CLUSTERS):
                expected_s = self.estimator.subsidy_estimates[self.destination][cluster][other_cluster]
                r[cluster][other_cluster] = expected_s - self.grid.get_rebalance_cost(cluster, other_cluster, self.period)

            # cost of entering the queue
            #expected_r = self.estimator.reward_estimates[self.destination][cluster]
            expected_r = self.estimator.fare_estimates[self.destination][cluster] - self.estimator.controller.get_tax(cluster)
            expected_w = self.get_w_estimate(cluster)
            r[cluster][cluster] = expected_r - expected_w*RESERVATION  # this uses the fiction that travel costs are already handled.
        return r

    def get_q_values(self, t):
        # return a list [a_i | i in clusters]

        # use value iteration over each policy

        # codes: -1 to exit the system, the current cluster to enter the queue, and any other cluster to transit
        # this can be handled a bit creatively with negative indexing
        q_values = [[0 for i in range(self.n_actions)] for j in range(N_CLUSTERS)]
        v_values = [0 for j in range(N_CLUSTERS)]

        incremental_rewards = self.incremental_rewards(t)
        p_estimates = self.estimator.transition_estimates

        # I need to estimate or plug in the probability of transit...
        for i in range(self.bellman_iterations):
            for cluster in range(N_CLUSTERS):
                for end_cluster in range(N_CLUSTERS):
                    if cluster == end_cluster:
                        continue
                    q_values[cluster][end_cluster] = v_values[end_cluster] + incremental_rewards[cluster][end_cluster]
                q_values[cluster][cluster] = incremental_rewards[cluster][cluster]
                q_values[cluster][-1] = incremental_rewards[cluster][-1]

                for end_cluster in range(N_CLUSTERS):
                    q_values[cluster][cluster] += (1-self.exit_prob)*p_estimates[cluster][end_cluster] * v_values[end_cluster]
                    q_values[cluster][cluster] -= (self.exit_prob)*p_estimates[cluster][end_cluster] * self.grid.get_travel_cost(end_cluster, self.destination, self.period)
                if abs(sum(p_estimates[cluster]) - 1) > 0.01:
                    raise Exception(f"bad probability: {sum(p_estimates[cluster])}")

            for cluster in range(N_CLUSTERS):
                v_values[cluster] = max(q_values[cluster])

        return q_values, v_values

    def decide(self, cluster, t):
        q_values, v_values = self.get_q_values(t)
        r_estimates = [self.estimator.fare_estimates[self.destination][cluster] - self.estimator.controller.get_tax(cluster) for cluster in range(N_CLUSTERS)]
        print(f"period: {self.period}")
        print(f"({cluster}) q_values: {q_values[cluster]}")
        print(f"({cluster}) v_values: {v_values}")
        print(f"({cluster}) incremental rewards: {self.incremental_rewards(t)[cluster]}")
        print(f"({cluster}) r_estimates: {[r_estimates[c] for c in range(N_CLUSTERS)]}")
        print(f"({cluster}) w_estimates: {[self.get_w_estimate(x) for x in range(N_CLUSTERS)]}")
        print(f"({cluster}) Q lengths: {self.estimator.rate_tracker.queue_lengths}")
        print(f"({self.period}, {cluster}) service rate estimates: {[1/x for x in self.estimator.inter_service_estimates]}")

        tau = self.exploration.boltzmann_tau
        unnorm_probs = [q/tau for q in q_values[cluster]]
        self.exploration.decay()

        if any([x > 100 for x in unnorm_probs]):
            # just default to the maximum
            action = -1
            max_val = float("-inf")
            for i, x in enumerate(unnorm_probs):
                if x > max_val:
                    max_val = x
                    action = i
        else:
            unnorm_probs = [math.exp(min(x,100)) for x in unnorm_probs]

            print(f"({cluster}) unnorm_probs: {unnorm_probs}")
            norm = sum(unnorm_probs)
            probs = [x/norm for x in unnorm_probs]
            action = 0
            rval = random.random()
            cprob = 0
            for i in range(self.n_actions):
                cprob += probs[i]
                if cprob >= rval:
                    action = i
                    break
            print(f"({cluster}) chose action {action}")
            print(f"({cluster}) probs: {probs}")
            print(f"({cluster}) tau: {tau}")
        if action == len(unnorm_probs)-1:
            return -1
        return action

    def decide_exit(self):
        x = random.random()
        return x < self.exit_prob
