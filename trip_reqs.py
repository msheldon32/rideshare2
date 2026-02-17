import csv
import math

from datetime import datetime
from dataclasses import dataclass

from grid import Grid

from util import *

DISTANCE_CORRECTION = 1.45
TIME_CORRECTION = 1

def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def get_trip_requests():
    _grid = Grid()
    out_reqs = []
    with open("data/requests_with_clusters.csv") as csvfile:
        reader = csv.DictReader(csvfile)

        for i, row in enumerate(reader):
            t = datetime.fromisoformat(row["started_on"])
            start = int(row["start_cluster"])
            end = int(row["end_cluster"])

            period = get_period(t.hour)

            if row["status"] == "b'DISPATCHED'":
                travel_time = (datetime.fromisoformat(row["completed_on"]) - t).total_seconds() / 3600
            else:
                travel_time = _grid.times[period][start][end] * TIME_CORRECTION

            tip = float(row["tip"]) if len(row["tip"]) > 0 else 0

            if len(row["total_fare"]) == 0:
                continue

            if travel_time < 0:
                continue

            # travel_distance = float(row["distance_travelled"]) / METERS_PER_MILE
            # travel_cost = travel_distance * COST_PER_MILE + travel_time * RESERVATION
            # total_fare = float(row["total_fare"]) + tip - travel_cost - BOOKING_FEE
            #
            # if float(row["total_fare"]) + tip > 100:
            #     continue
            #
            # total_fare = int(total_fare*100)

            start_lat = float(row["start_location_lat"])
            start_lon = float(row["start_location_long"])
            end_lat = float(row["end_location_lat"])
            end_lon = float(row["end_location_long"])

            travel_distance = haversine_miles(start_lat, start_lon, end_lat, end_lon) * DISTANCE_CORRECTION
            travel_cost = travel_distance * COST_PER_MILE + travel_time * RESERVATION

            rate_per_mile = float(row["rate_per_mile"]) if row["rate_per_mile"] else 0.99
            rate_per_minute = float(row["rate_per_minute"]) if row["rate_per_minute"] else 0.25
            travel_time_minutes = travel_time * 60

            total_fare = float(row["base_fare"]) + rate_per_mile * travel_distance + rate_per_minute * travel_time_minutes + tip - travel_cost - BOOKING_FEE

            if total_fare > 100 * 100:
                continue

            total_fare = int(total_fare * 100)

            out_reqs.append([t, start, end, period, total_fare, travel_time])
            
    out_reqs.sort()

    epoch = out_reqs[0][0]

    out_reqs = [
            Request((r[0] - epoch).total_seconds()/(3600), r[1], r[2], r[3], r[4], r[5]) for r in out_reqs
            ]

    return out_reqs, epoch

if __name__ == "__main__":
    reqs, _ = get_trip_requests()

    for req in reqs:
        print(req)
        input("continue")

