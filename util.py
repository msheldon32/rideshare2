import math
from dataclasses import dataclass

N_PERIODS = 8
PERIOD_LENGTH = (24//N_PERIODS)
BOOKING_FEE = 1.5

N_CLUSTERS = 16
N_CLASSES = 16

RESERVATION = 7.25
COST_PER_MILE = 0.535
METERS_PER_MILE = 1609.34

def get_period(t):
    hod = math.floor(t) % 24
    return hod // PERIOD_LENGTH

@dataclass(order=True)
class Request:
    time: float
    start_cluster: int
    end_cluster: int
    period: int
    net_fare_cents: int
    travel_time: float

@dataclass(order=True)
class Arrival:
    time: float
    start_cluster: int
    cluster: int
    _class: int

@dataclass(order=True)
class Spawn:
    time: float
    cluster: int
    _class: int
