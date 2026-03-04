import cvxpy as cp
import numpy as np


def estimate_total_reward(model_config, policies):
    """Compute estimated steady-state total reward rate given a model config and policies.

    Solves the per-class flow balance equations to get steady-state vehicle
    flows, then computes: vehicle rewards - relocation costs - waiting costs.
    """
    n_loc = len(model_config.locations)

    # Steady-state flow v[k][i]: rate of class-k vehicles arriving at location i
    flows = []
    for k in range(n_loc):
        A = np.zeros((n_loc, n_loc))
        b = np.zeros(n_loc)
        b[k] = model_config.arrival_rates[k]

        for j in range(n_loc):
            p_queue_j = policies[k][j][j]
            for i in range(n_loc):
                if i != j:
                    A[i, j] += policies[k][j][i]  # relocation j -> i
                A[i, j] += (1 - model_config.exit_prob) * p_queue_j * model_config.customer_transitions[j][i]  # post-service return

        try:
            v = np.linalg.solve(np.eye(n_loc) - A, b)
            v = np.maximum(v, 0)
        except np.linalg.LinAlgError:
            v = np.zeros(n_loc)
        flows.append(v)

    # Total arrival rate at each queue
    lambda_i = np.zeros(n_loc)
    for k in range(n_loc):
        for i in range(n_loc):
            lambda_i[i] += flows[k][i] * policies[k][i][i]

    total_reward = 0.0

    # Vehicle rewards minus relocation costs
    for k in range(n_loc):
        for i in range(n_loc):
            v_ki = flows[k][i]
            arrivals = v_ki * policies[k][i][i]
            total_reward += arrivals * model_config.producer_rewards[k][i]
            for j in range(n_loc):
                if j != i and j < n_loc and policies[k][i][j] > 0:
                    total_reward -= v_ki * policies[k][i][j] * model_config.get_prepaid_cost(k, i, j)

    # Waiting costs: reservation * E[L_i] = reservation * lambda / (mu - lambda)
    for i in range(n_loc):
        mu_i = model_config.service_rates[i]
        lam_i = lambda_i[i]
        if 0 < lam_i < mu_i:
            total_reward -= model_config.reservation * lam_i / (mu_i - lam_i)

    return total_reward



def get_cvxpy_prob(model_config, input_vehicle_rewards=None):
    if input_vehicle_rewards is None:
        input_vehicle_rewards = model_config.vehicle_rewards
    n_loc = len(model_config.locations)

    # arrivals into queue: arrivals into the queue at location i, from vehicles with origin k
    arrivals_into_queue = cp.Variable((n_loc, n_loc), nonneg=True)
    balk_rate = cp.Variable((n_loc, n_loc), nonneg=True)

    # flows between locations: flows from location i to location j, from vehicles with origin k
    flows_between_locations = [cp.Variable((n_loc, n_loc), nonneg=True) for k in range(n_loc)]

    total_arrival_rates = cp.Variable(n_loc, nonneg=True)

    vehicle_rewards = [[cp.Parameter() for i in range(n_loc)] for k in range(n_loc)]

    for k in range(n_loc):
        for i in range(n_loc):
            vehicle_rewards[k][i].value = input_vehicle_rewards[k][i]

    vehicle_utilities = [[None for i in range(n_loc)] for k in range(n_loc)]

    for k in range(n_loc):
        for i in range(n_loc):
            expected_tt_difference = -sum([model_config.customer_transitions[i][j] * model_config.get_prepaid_cost(k, i, j) for j in range(n_loc)])
            vehicle_utilities[k][i] = (expected_tt_difference + vehicle_rewards[k][i])

    # objective function: minimize the travel time multiplied by the flow minus the log of (service rate - total arrival rate across all origins)
    obj = 0
    for k in range(n_loc):
        for i in range(n_loc):
            for j in range(n_loc):
                travel_cost = model_config.get_prepaid_cost(k, i, j)
                obj += travel_cost * flows_between_locations[k][i,j]

    for i in range(n_loc):
        obj -= cp.log(model_config.service_rates[i] - total_arrival_rates[i]) * model_config.reservation

    for i in range(n_loc):
        for k in range(n_loc):
            obj -= vehicle_utilities[k][i] * arrivals_into_queue[k,i]

    objective = cp.Minimize(obj)

    # constraints
    constraints = []

    # 1. total arrival rate
    for i in range(n_loc):
        constraints.append(total_arrival_rates[i] == cp.sum(arrivals_into_queue[:, i]))

    # 2. flow conservation
    for k in range(n_loc):
        for i in range(n_loc):
            outside_arrival_rate = model_config.arrival_rates[i] if i == k else 0

            vehicle_returns = (1 - model_config.exit_prob) * cp.sum([arrivals_into_queue[k, j] * model_config.customer_transitions[j][i] for j in range(n_loc)])

            constraints.append(cp.sum(flows_between_locations[k][:, i]) - cp.sum(flows_between_locations[k][i, :]) + outside_arrival_rate + vehicle_returns == arrivals_into_queue[k,i] + balk_rate[k,i])

    prob = cp.Problem(objective, constraints)

    return [prob, total_arrival_rates, vehicle_rewards, arrivals_into_queue, flows_between_locations, balk_rate]

def get_cvxpy_prob_agg_queue(model_config):
    n_loc = len(model_config.locations)

    arrivals_into_queue = cp.Variable((n_loc, n_loc), nonneg=True)
    balk_rate = cp.Variable((n_loc, n_loc), nonneg=True)
    flows_between_locations = [cp.Variable((n_loc, n_loc), nonneg=True) for k in range(n_loc)]
    total_arrival_rates = cp.Variable(n_loc, nonneg=True)

    vehicle_utilities = [[None for i in range(n_loc)] for k in range(n_loc)]
    for k in range(n_loc):
        for i in range(n_loc):
            expected_tt_difference = -sum([model_config.customer_transitions[i][j] * model_config.get_prepaid_cost(k, i, j) for j in range(n_loc)])
            vehicle_utilities[k][i] = expected_tt_difference + model_config.producer_rewards[k][i]

    obj = 0
    for k in range(n_loc):
        for i in range(n_loc):
            for j in range(n_loc):
                travel_cost = model_config.get_prepaid_cost(k, i, j)
                obj += travel_cost * flows_between_locations[k][i, j]

    # aggregate queue length: E[L] = lambda / (mu - lambda) = mu * inv_pos(mu - lambda) - 1
    for i in range(n_loc):
        mu_i = model_config.service_rates[i]
        obj += (mu_i * cp.inv_pos(mu_i - total_arrival_rates[i]) - 1) * model_config.reservation

    for i in range(n_loc):
        for k in range(n_loc):
            obj -= vehicle_utilities[k][i] * arrivals_into_queue[k, i]

    objective = cp.Minimize(obj)

    constraints = []
    for i in range(n_loc):
        constraints.append(total_arrival_rates[i] == cp.sum(arrivals_into_queue[:, i]))
    for k in range(n_loc):
        for i in range(n_loc):
            outside_arrival_rate = model_config.arrival_rates[i] if i == k else 0
            vehicle_returns = (1 - model_config.exit_prob) * cp.sum([arrivals_into_queue[k, j] * model_config.customer_transitions[j][i] for j in range(n_loc)])
            constraints.append(cp.sum(flows_between_locations[k][:, i]) - cp.sum(flows_between_locations[k][i, :]) + outside_arrival_rate + vehicle_returns == arrivals_into_queue[k, i] + balk_rate[k, i])

    prob = cp.Problem(objective, constraints)
    return [prob, total_arrival_rates, arrivals_into_queue, flows_between_locations, balk_rate]


def get_policies_agg_queue(model_config):
    prob, total_arrival_rates, arrivals_into_queue, flows_between_locations, balk_rate = get_cvxpy_prob_agg_queue(model_config)
    try:
        prob.solve(solver=cp.CLARABEL)
        if prob.status not in ("optimal", "optimal_inaccurate"):
            raise ValueError(f"CLARABEL status: {prob.status}")
    except Exception as e:
        print(f"CLARABEL failed ({e}), falling back to SCS")
        prob.solve(solver=cp.SCS)

    n_loc = len(model_config.locations)
    policies = [[None for i in range(n_loc)] for k in range(n_loc)]
    for k in range(n_loc):
        for i in range(n_loc):
            action_rates = [0.0] * (n_loc + 1)
            action_rates[i] = arrivals_into_queue.value[k, i]
            for j in range(n_loc):
                if j != i:
                    action_rates[j] = flows_between_locations[k].value[i, j]
            action_rates[n_loc] = balk_rate.value[k, i]
            total = sum(action_rates)
            if total > 0:
                policies[k][i] = [r / total for r in action_rates]
            else:
                policies[k][i] = [0.0] * (n_loc + 1)
                policies[k][i][n_loc] = 1.0

    return policies


def get_policies(model_config, input_vehicle_rewards=None):
    prob, total_arrival_rates, vehicle_rewards, arrivals_into_queue, flows_between_locations, balk_rate = get_cvxpy_prob(model_config, input_vehicle_rewards)
    try:
        prob.solve(solver=cp.CLARABEL)
        if prob.status not in ("optimal", "optimal_inaccurate"):
            raise ValueError(f"CLARABEL status: {prob.status}")
    except Exception as e:
        print(f"CLARABEL failed ({e}), falling back to SCS")
        prob.solve(solver=cp.SCS)

    n_loc = len(model_config.locations)

    # policies[k][i] is a list of n_loc + 1 probabilities:
    #   policies[k][i][j] for j != i: probability of relocating to location j
    #   policies[k][i][i]: probability of entering the queue
    #   policies[k][i][n_loc]: probability of exiting
    policies = [[None for i in range(n_loc)] for k in range(n_loc)]

    for k in range(n_loc):
        for i in range(n_loc):
            action_rates = [0.0] * (n_loc + 1)

            # enter queue at i
            action_rates[i] = arrivals_into_queue.value[k, i]

            # relocate to j
            for j in range(n_loc):
                if j != i:
                    action_rates[j] = flows_between_locations[k].value[i, j]

            # exit
            action_rates[n_loc] = balk_rate.value[k, i]

            # normalize to probabilities
            total = sum(action_rates)
            if total > 0:
                policies[k][i] = [r / total for r in action_rates]
            else:
                # no flow at this (k, i) - default to exit
                policies[k][i] = [0.0] * (n_loc + 1)
                policies[k][i][n_loc] = 1.0

    return policies
