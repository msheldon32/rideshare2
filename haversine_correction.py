import csv
import math
from datetime import datetime

from util import METERS_PER_MILE


def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def compute_corrections():
    dist_ratios = []

    with open("data/requests_with_clusters.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["status"] != "b'DISPATCHED'":
                continue
            if not row["distance_travelled"] or not row["total_fare"]:
                continue

            reported_dist = float(row["distance_travelled"]) / METERS_PER_MILE
            # Filter out clearly bogus distances (> 100 miles in Austin)
            if reported_dist > 100 or reported_dist < 0.1:
                continue

            start_lat = float(row["start_location_lat"])
            start_lon = float(row["start_location_long"])
            end_lat = float(row["end_location_lat"])
            end_lon = float(row["end_location_long"])

            h_dist = haversine_miles(start_lat, start_lon, end_lat, end_lon)
            if h_dist < 0.1:
                continue

            t_start = datetime.fromisoformat(row["started_on"])
            t_end = datetime.fromisoformat(row["completed_on"])
            reported_time = (t_end - t_start).total_seconds() / 3600
            if reported_time <= 0 or reported_time > 3:
                continue

            dist_ratios.append(reported_dist / h_dist)

    dist_ratios.sort()
    n = len(dist_ratios)

    distance_correction = dist_ratios[n // 2]

    print(f"Trips analyzed: {n}")
    print(f"Per-trip distance ratio (reported / haversine):")
    print(f"  median: {distance_correction:.4f}")
    print(f"  mean:   {sum(dist_ratios)/n:.4f}")
    print(f"  p25:    {dist_ratios[n//4]:.4f}")
    print(f"  p75:    {dist_ratios[3*n//4]:.4f}")

    return distance_correction


if __name__ == "__main__":
    compute_corrections()
