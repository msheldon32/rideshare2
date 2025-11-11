from util import *

import random

class DriverModel:
    def __init__(self, grid):
        self.grid = grid
        self.w_estimates = [0 for i in range(N_CLUSTERS)]
        self.r_estimates = [10 for i in range(N_CLUSTERS)]
        self.s_estimates = [[0 for j in range(N_CLUSTERS)] for i in range(N_CLUSTERS)]
        self.alpha_w = 0.95
        self.alpha_r = 0.95
        self.alpha_s = 0.95

    def observe_w(self, cluster, w):
        old_w = self.w_estimates[cluster]
        new_w = self.alpha_w*old_w + (1-self.alpha_w)*w

        self.w_estimates[cluster] = new_w

    def observe_r(self, cluster, r):
        old_r = self.r_estimates[cluster]
        new_r = self.alpha_r*old_r + (1-self.alpha_r)*r

        self.r_estimates[cluster] = new_r

    def observe_s(self, start, end, s):
        old_s = self.s_estimates[start][end]
        new_s = self.alpha_s*old_s + (1-self.alpha_s)*s

        self.s_estimates[start][end] = new_s

    def get_q_values(self):
        # return a list [a_i | i in clusters]
        pass
    
    def decide(self, cluster):
        x = random.random()
        if x < 0.1:
            return -1
        elif x < 0.3:
            return random.randrange(N_CLUSTERS)
        else:
            return cluster

    def decide_exit(self):
        x = random.random()
        return x < 0.2
