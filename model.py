from util import *

import random
import csv

class QHistory:
    def __init__(self, q_reports):
        self.q_reports = q_reports
        self.arrivals = [[] for i in range(N_CLUSTERS)]
        self.requests = [[] for i in range(N_CLUSTERS)]
        self.time_window = 1

    def get_q_len(self, cluster):
        if len(self.q_reports[cluster]) == 0:
            return 0
        return self.q_reports[cluster][-1][2]

    def get_expected_w_ll(self, cluster, t):
        # look backward to get the number of arrivals
        n_arrivals = 0
        to_cut = 0
        for r in range(0,len(self.arrivals[cluster])):
            i = len(self.arrivals[cluster])-1-r
            if self.arrivals[cluster][i] < t-self.time_window:
                to_cut = i
                break
            n_arrivals += 1

        #self.arrivals[cluster] = self.arrivals[cluster][:to_cut]

        qt = 0
        last_t = t
        qr = self.q_reports[cluster]

        to_cut = 0

        for r in range(0, len(qr)):
            i = len(qr)-1-r
            if qr[i][0] < t-self.time_window:
                qt += (last_t - (t-self.time_window))*qr[i][2]
                to_cut = i
                break
            qt += (last_t - qr[i][0])*qr[i][2]
            last_t = qr[i][0]

        #self.q_reports[cluster] = self.q_reports[cluster][:to_cut]
        
        #if qt < 0:
        #    print(self.q_reports[cluster])
        #    print(qt)
        #    raise Exception("stop")

        if n_arrivals == 0:
            # *shrugs*
            return 0
        return qt/n_arrivals

    def get_expected_w_harm(self, cluster, t):
        # look backward to get the number of arrivals
        n_arrivals = 0
        to_cut = 0
        for r in range(0,len(self.arrivals[cluster])):
            i = len(self.arrivals[cluster])-1-r
            if self.arrivals[cluster][i] < t-self.time_window:
                to_cut = i
                break
            n_arrivals += 1

        n_requests = 0
        to_cut = 0
        for r in range(0,len(self.requests[cluster])):
            i = len(self.requests[cluster])-1-r
            if self.requests[cluster][i] < t-self.time_window:
                to_cut = i
                break
            n_requests += 1

        Z = max(n_requests - n_arrivals, 0)
        Z /= self.time_window
        ll_exp = self.get_expected_w_ll(cluster, t)

        if ll_exp == 0:
            if Z <= 0:
                return 5
            return 2/Z

        """if Z <= 0:
            # *shrugs*
            return self.get_expected_w_ll(cluster, t)
        
        z_exp = 1/Z
        return 0.5*ll_exp + 0.5*z_exp"""
        
        # do the harmonic mean of the ll expected value and Z

        return 2/(Z + (1/ll_exp))

    def get_expected_w(self, cluster, t):
        qr = self.q_reports[cluster]
        q = 0

        if len(qr) > 0:
            q = qr[-1][2]

        n_requests = 0
        to_cut = 0
        for r in range(0,len(self.requests[cluster])):
            i = len(self.requests[cluster])-1-r
            if self.requests[cluster][i] < t-self.time_window:
                to_cut = i
                break
            n_requests += 1

        empirical_rate = n_requests/self.time_window

        if empirical_rate == 0:
            empirical_rate = 1

        return (1 + q)/empirical_rate
        

    def report_q_len(self, cluster, q_len, t):
        self.q_reports[cluster].append((t, 0, q_len))

    def report_arrival(self, cluster, t):
        self.arrivals[cluster].append(t)

    def report_request(self, cluster, t):
        self.requests[cluster].append(t)

    def last_arrival(self, cluster):
        return self.arrivals[cluster][-1]

class WEstimates:
    def __init__(self, last_t, q_acc, q_history):
        self.w_estimates = [0 for i in range(N_CLUSTERS)]
        self.alpha_w = 0#.95
        self.max_alpha = 0.9
        self.alpha_inc = 0.0001
        self.q_acc = q_acc
        self.last_t = last_t
        self.last_w = [0 for i in range(N_CLUSTERS)]

        self.time_window = 2  # lookback time for w

        self.q_history = q_history

        self.arrival_alpha = 0.9
        self.arrival_estimates = [1 for i in range(N_CLUSTERS)]


    def observe_w(self, cluster, w):
        old_w = self.w_estimates[cluster]
        new_w = self.alpha_w*old_w + (1-self.alpha_w)*w

        self.alpha_w = self.alpha_inc*(self.max_alpha - self.alpha_w) + self.alpha_w

        self.w_estimates[cluster] = new_w
        self.last_w[cluster] = w

    def get_q_len(self, cluster):
        return self.q_history.get_q_len(cluster)

    def get_expected_w(self, cluster, t):
        #exp_w = self.q_history.get_expected_w(cluster, t)
        exp_q = self.get_q_len(cluster)
        exp_w = (1 + exp_q)*self.arrival_estimates[cluster]
        self.observe_w(cluster, exp_w)

        return self.w_estimates[cluster]

    def report_q_len(self, cluster, q_len, t):
        self.q_history.report_q_len(cluster, q_len, t)

    def report_arrival(self, cluster, t):
        last_arrival = self.q_history.last_arrival(cluster)
        self.q_history.report_arrival(cluster, t)

        arrival_time = last_arrival - t
        self.arrival_estimates[cluster] = (self.arrival_alpha*self.arrival_estimates[cluster]) + ((1-self.arrival_alpha)*arrival_time)

    def report_request(self, cluster, t):
        self.q_history.report_request(cluster, t)

class Exploration:
    def __init__(self):
        self.boltzmann_tau = 0.2#1.0#10.0
        self.min_boltzmann = 0.2
        self.boltzmann_decay = 0.99995

    def decay(self):
        self.boltzmann_tau = self.min_boltzmann + self.boltzmann_decay*(self.boltzmann_tau - self.min_boltzmann)

class DriverModel:
    def __init__(self, grid, period, destination, w_estimates, exploration):
        self.grid = grid
        self.r_estimates = [10 for i in range(N_CLUSTERS)]
        self.s_estimates = [[0 for j in range(N_CLUSTERS)] for i in range(N_CLUSTERS)]
        self.p_estimates = [[(1/N_CLUSTERS) for j in range(N_CLUSTERS)] for i in range(N_CLUSTERS)]
        self.w_estimates = w_estimates
        self.alpha_r = 0.8
        self.alpha_s = 0.8
        self.alpha_p = 0.9
        self.period = period
        self.destination = destination
        self.exit_prob = 1
        self.n_actions = N_CLUSTERS + 1
        self.exploration = exploration

        self.bellman_iterations = 15

        arrivals = [0 for i in range(N_CLUSTERS)]

        # get the exit prob for the current time period
        with open("data/arrival_rates.csv") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if int(row["period"]) == self.period:
                    cluster = int(row["start"])
                    arrivals[cluster] = float(row["arrivals"])

        with open("data/exit_rates.csv") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                if int(row["period"]) == self.period:
                    cluster = int(row["start"])
                    exit_rate = float(row["exits"])
                    self.exit_prob = min(self.exit_prob, exit_rate/arrivals[cluster])

    def observe_w(self, cluster, w):
        self.w_estimates.observe_w(cluster, w)

    def observe_r(self, cluster, r):
        r = min(r, 50) # reward clipping
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

    def incremental_rewards(self, t):
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
            expected_w = self.w_estimates.get_expected_w(cluster, t)
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
                    q_values[cluster][cluster] += (1-self.exit_prob)*self.p_estimates[cluster][end_cluster] * v_values[end_cluster]
                    q_values[cluster][cluster] -= (self.exit_prob)*self.p_estimates[cluster][end_cluster] * self.grid.get_travel_cost(end_cluster, self.destination, self.period)
                if abs(sum(self.p_estimates[cluster]) - 1) > 0.01:
                    raise Exception(f"bad probability: {sum(self.p_estimates[cluster])}")

            for cluster in range(N_CLUSTERS):
                v_values[cluster] = max(q_values[cluster])

        return q_values, v_values
    
    def decide(self, cluster, t):
        if False:
            x = random.random()
            if x < 0.1:
                return -1
            elif x < 0.3:
                return random.randrange(N_CLUSTERS)
            else:
                return cluster

        q_values, v_values = self.get_q_values(t)
        print(f"period: {self.period}")
        print(f"({cluster}) q_values: {q_values[cluster]}")
        print(f"({cluster}) v_values: {v_values}")
        print(f"({cluster}) incremental rewards: {self.incremental_rewards(t)[cluster]}")
        print(f"({cluster}) r_estimates: {self.r_estimates}")
        print(f"({cluster}) w_estimates: {[self.w_estimates.get_expected_w(x,t) for x in range(N_CLUSTERS)]}")
        print(f"({cluster}) Q values: {[self.w_estimates.get_q_len(x) for x in range(N_CLUSTERS)]}")

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
