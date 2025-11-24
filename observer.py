from util import *

class Observer:
    def __init__(self):
        self.total_requests = [0]
        self.profit = [0]
        self.total_trips = [0]
    
    def observe_request(self, request, remuneration, admitted):
        self.total_requests.append(self.total_requests[-1]+1)
        if admitted:
            self.total_trips.append(self.total_trips[-1]+1)

            self.profit.append(self.profit[-1]+(request.net_fare_cents-remuneration))
