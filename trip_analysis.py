import csv

from util import *

tc_baseline = [[0 for i in range(N_CLUSTERS)] for j in range(N_PERIODS)]
tc_sim = [[0 for i in range(N_CLUSTERS)] for j in range(N_PERIODS)]

with open("data/trip_counts_baseline.csv") as f:
    reader = csv.reader(f)
    next(reader)

    for row in reader:
        period = int(row[0])
        cluster = int(row[1])
        total_trips = float(row[2])

        tc_baseline[period][cluster] = total_trips

with open("trip_counts.csv") as f:
    reader = csv.reader(f)
    next(reader)

    for row in reader:
        period = int(row[0])
        cluster = int(row[1])
        total_trips = float(row[2])

        tc_sim[period][cluster] = total_trips

overall_ae = 0
overall_trips = 0

for period in range(N_PERIODS):
    ae = [abs(a-b) for a, b in zip(tc_baseline[period], tc_sim[period])]
    total_trips = sum(tc_baseline[period])

    overall_ae += sum(ae)
    overall_trips += sum(tc_baseline[period])

    nmae = sum(ae)/(total_trips)
    print(f"({period}) nmae: {nmae}")

print(f"total nmae: {overall_ae/overall_trips}")
