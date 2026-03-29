import requests

def get_weather(lat, lon):
    """
    Gets real weather data for any location using Open-Meteo.
    This API is completely free - no key needed!
    """
    url = "https://api.open-meteo.com/v1/forecast"
    
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ["temperature_2m", "precipitation", "windspeed_10m"],
        "daily": ["precipitation_sum", "temperature_2m_max"],
        "forecast_days": 1
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        current = data.get("current", {})
        daily = data.get("daily", {})
        
        return {
            "temperature_c": current.get("temperature_2m", 30),
            "rainfall_mm": daily.get("precipitation_sum", [0])[0],
            "wind_kmh": current.get("windspeed_10m", 10),
            "source": "Open-Meteo (live)"
        }
    except Exception as e:
        # If internet is down, return safe fallback values
        print(f"Weather API error: {e}. Using fallback.")
        return {
            "temperature_c": 30,
            "rainfall_mm": 5,
            "wind_kmh": 15,
            "source": "fallback"
        }

if __name__ == "__main__":
    # Test it with Delhi coordinates
    weather = get_weather(28.6, 77.2)
    print("Delhi weather right now:", weather)