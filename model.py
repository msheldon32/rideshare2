from util import *

import random
import csv

class WEstimates:
    def __init__(self):
        self.w_estimates = [0 for i in range(N_CLUSTERS)]
        self.alpha_w = 0.95

    def observe_w(self, cluster, w):
        old_w = self.w_estimates[cluster]
        new_w = self.alpha_w*old_w + (1-self.alpha_w)*w

        self.w_estimates[cluster] = new_w


class DriverModel:
    def __init__(self, grid, period, destination, w_estimates):
        self.grid = grid
        self.r_estimates = [10 for i in range(N_CLUSTERS)]
        self.s_estimates = [[0 for j in range(N_CLUSTERS)] for i in range(N_CLUSTERS)]
        self.p_estimates = [[(1/N_CLUSTERS) for j in range(N_CLUSTERS)] for i in range(N_CLUSTERS)]
        self.w_estimates = w_estimates
        self.alpha_r = 0.8
        self.alpha_s = 0.9
        self.alpha_p = 0.95
        self.period = period
        self.destination = destination
        self.exit_prob = 1
        self.n_actions = N_CLUSTERS + 1

        self.bellman_iterations = 100

        self.boltzmann_tau = 10.0
        self.min_boltzmann = 1.0
        self.boltzmann_decay = 0.999

        # get the exit rates for the current time period

        with open("data/exit_probs.csv") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                if int(row["period"]) == self.period:
                    self.exit_prob = float(row["exit_prob"])
                    break

    def observe_w(self, cluster, w):
        self.w_estimates.observe_w(cluster, w)

    def observe_r(self, cluster, r):
        old_r = self.r_estimates[cluster]
        new_r = self.alpha_r*old_r + (1-self.alpha_r)*r

        self.r_estimates[cluster] = new_r

    def observe_s(self, start, end, s):
        old_s = self.s_estimates[start][end]
        new_s = self.alpha_s*old_s + (1-self.alpha_s)*s

        self.s_estimates[start][end] = new_s

    def observe_p(self, start, end):
        for cluster in range(N_CLUSTERS):
            self.p_estimates[start][cluster] = self.alpha_p * self.p_estimates[start][cluster]

        self.p_estimates[start][end] += (1-self.alpha_p)

    def incremental_rewards(self):
        r = [[0 for i in range(self.n_actions)] for j in range(N_CLUSTERS)]

        for cluster in range(N_CLUSTERS):
            # cost of leaving
            r[cluster][-1] = -self.grid.get_travel_cost(cluster, self.destination, self.period)

            # cost of transiting
            for other_cluster in range(N_CLUSTERS):
                expected_s = self.s_estimates[cluster][other_cluster]
                r[cluster][other_cluster] = expected_s-self.grid.get_travel_cost(cluster, other_cluster, self.period)

            # cost of entering the queue
            expected_r = self.r_estimates[cluster]
            expected_w = self.w_estimates.w_estimates[cluster]
            r[cluster][cluster] = expected_r - expected_w*RESERVATION  # this uses the fiction that travel costs are already handled.
        return r

    def get_q_values(self):
        # return a list [a_i | i in clusters]

        # use value iteration over each policy

        # codes: -1 to exit the system, the current cluster to enter the queue, and any other cluster to transit
        # this can be handled a bit creatively with negative indexing
        q_values = [[0 for i in range(self.n_actions)] for j in range(N_CLUSTERS)]
        v_values = [0 for j in range(N_CLUSTERS)]

        incremental_rewards = self.incremental_rewards()

        # I need to estimate or plug in the probability of transit...
        for i in range(self.bellman_iterations):
            for cluster in range(N_CLUSTERS):
                for end_cluster in range(N_CLUSTERS):
                    if cluster == end_cluster:
                        continue
                    q_values[cluster][end_cluster] = v_values[end_cluster] + incremental_rewards[cluster][end_cluster]
                q_values[cluster][cluster] = incremental_rewards[cluster][end_cluster]
                q_values[cluster][-1] = incremental_rewards[cluster][-1]

                for end_cluster in range(N_CLUSTERS):
                    q_values[cluster][cluster] += self.p_estimates[cluster][end_cluster] * v_values[end_cluster]

            for cluster in range(N_CLUSTERS):
                v_values[cluster] = max(q_values[cluster])

        return q_values
    
    def decide(self, cluster):
        if False:
            x = random.random()
            if x < 0.1:
                return -1
            elif x < 0.3:
                return random.randrange(N_CLUSTERS)
            else:
                return cluster

        q_values = self.get_q_values()
        print(f"period: {self.period}")
        print(f"({cluster}) q_values: {q_values[cluster]}")
        print(f"({cluster}) incremental rewards: {self.incremental_rewards()[cluster]}")
        print(f"({cluster}) r_estimates: {self.r_estimates}")
        print(f"({cluster}) w_estimates: {self.w_estimates.w_estimates}")

        print(f"({cluster}) unnorm_probs(pre): {[q/self.boltzmann_tau for q in q_values[cluster]]}")
        unnorm_probs = [math.exp(q/self.boltzmann_tau) for q in q_values[cluster]]
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
        print(f"({cluster}) tau: {self.boltzmann_tau}")
        self.boltzmann_tau = self.min_boltzmann + self.boltzmann_decay*(self.boltzmann_tau - self.min_boltzmann)
        if action == len(probs)-1:
            return -1
        return action

    def decide_exit(self):
        x = random.random()
        return x < 0.2
