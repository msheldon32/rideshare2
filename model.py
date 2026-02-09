from util import *

import random


class DriverModel:
    def __init__(self, policy, exit_prob):
        # policy[i] = list of n_loc+1 probabilities for location i
        self.policy = policy
        self.exit_prob = exit_prob
        self.n_locations = len(policy)

    def decide(self, cluster):
        print(f"({cluster}) deciding...")
        probs = self.policy[cluster]
        print(f"probs: {[float(x) for x in probs]}")
        action = random.choices(range(len(probs)), probs, k=1)[0]
        if action == self.n_locations:
            return -1
        return action

    def decide_exit(self):
        return random.random() < self.exit_prob
