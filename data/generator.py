import pandas as pd
import random

def make_deliveries(n=200):
    """Creates fake but realistic delivery records"""
    
    routes = [
        ("Delhi", "Mumbai", 28.6, 77.2, 19.0, 72.8),
        ("Mumbai", "Chennai", 19.0, 72.8, 13.0, 80.2),
        ("Delhi", "Kolkata", 28.6, 77.2, 22.5, 88.3),
        ("Chennai", "Bengaluru", 13.0, 80.2, 12.9, 77.5),
    ]
    
    climate_events = ["none", "none", "none", "flood", "heatwave", "cyclone"]
    
    records = []
    for i in range(n):
        origin, dest, olat, olon, dlat, dlon = random.choice(routes)
        event = random.choice(climate_events)
        weather = random.uniform(0, 10)
        traffic = random.uniform(0.2, 1.0)
        
        # Delay is higher when there's bad weather or an event
        base_delay = weather * 1.5 + traffic * 2
        if event != "none":
            base_delay += random.uniform(5, 20)
        delay = max(0, base_delay + random.gauss(0, 2))
        
        records.append({
            "delivery_id": f"DEL-{10000 + i}",
            "origin": origin,
            "destination": dest,
            "origin_lat": olat,
            "origin_lon": olon,
            "dest_lat": dlat,
            "dest_lon": dlon,
            "climate_event": event,
            "weather_score": round(weather, 2),
            "traffic_index": round(traffic, 2),
            "delay_hours": round(delay, 1),
            "status": "delayed" if delay > 5 else "on_time"
        })
    
    return pd.DataFrame(records)

if __name__ == "__main__":
    df = make_deliveries(200)
    df.to_csv("data/deliveries.csv", index=False)
    print(f"Created {len(df)} delivery records")
    print(df.head())