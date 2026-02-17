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
    reported_distances = []
    haversine_distances = []
    reported_times = []
    computed_times = []

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

            # Compute expected time from haversine assuming average speed
            # We'll compare reported time to haversine distance to get effective speed
            reported_distances.append(reported_dist)
            haversine_distances.append(h_dist)
            reported_times.append(reported_time)

    reported_distances.sort()
    haversine_distances.sort()
    reported_times.sort()

    n = len(reported_distances)
    median_reported_dist = reported_distances[n // 2]
    median_haversine_dist = haversine_distances[n // 2]
    median_reported_time = reported_times[n // 2]

    # Median reported speed (miles per hour) from reported distance and time
    speeds = sorted(rd / rt for rd, rt in zip(reported_distances, reported_times) if rt > 0)
    median_speed = speeds[len(speeds) // 2]

    # Haversine speeds
    h_speeds = sorted(hd / rt for hd, rt in zip(haversine_distances, reported_times) if rt > 0)
    median_h_speed = h_speeds[len(h_speeds) // 2]

    distance_correction = median_reported_dist / median_haversine_dist

    print(f"Trips analyzed: {n}")
    print(f"Median reported distance: {median_reported_dist:.2f} mi")
    print(f"Median haversine distance: {median_haversine_dist:.2f} mi")
    print(f"Distance correction factor: {distance_correction:.4f}")
    print(f"Median reported trip time: {median_reported_time * 60:.1f} min")
    print(f"Median reported speed: {median_speed:.1f} mph")
    print(f"Median haversine speed: {median_h_speed:.1f} mph")

    return distance_correction


if __name__ == "__main__":
    compute_corrections()
