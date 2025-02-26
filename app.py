import os
import streamlit as st
import datetime
import pandas as pd
from amadeus import Client, ResponseError
import openai
import json

# ✅ Force reinstall `amadeus` to prevent import issues
os.system("pip install --upgrade --force-reinstall amadeus")

# ✅ Read API keys from Streamlit Secrets or environment variables
API_KEY = st.secrets.get("AMADEUS_API_KEY", os.getenv("AMADEUS_API_KEY"))
API_SECRET = st.secrets.get("AMADEUS_API_SECRET", os.getenv("AMADEUS_API_SECRET"))
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))

# ✅ Stop if keys are missing
if not API_KEY or not API_SECRET or not OPENAI_API_KEY:
    st.error("🚨 API keys are missing! Please set them in Streamlit Secrets.")
    st.stop()

# ✅ Initialize API Clients
amadeus = Client(client_id=API_KEY, client_secret=API_SECRET)
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# ✅ Cache for storing known IATA codes (to reduce API calls)
iata_cache = {
    "London": "LON",
    "Delhi": "DEL",
    "New York": "NYC",
    "Los Angeles": "LAX",
    "Paris": "PAR",
    "Tokyo": "TYO",
    "Dubai": "DXB",
    "Mumbai": "BOM",
    "Singapore": "SIN",
    "Berlin": "BER"
}

# ✅ Function to Get IATA Code (Uses Cache First)
def get_iata_code(city_name):
    """Retrieve IATA airport code using cache, otherwise fetch from Amadeus API."""
    if city_name in iata_cache:
        return iata_cache[city_name]

    try:
        response = amadeus.reference_data.locations.get(
            keyword=city_name,
            subType="CITY,AIRPORT"
        )
        if response.data:
            iata_code = response.data[0]["iataCode"]
            iata_cache[city_name] = iata_code  # Cache the new IATA code
            return iata_code
        else:
            return None  # No matching IATA code found
    except ResponseError as error:
        st.error(f"❌ Error fetching IATA code for {city_name}: {error}")
        return None

# ✅ Function to Convert Contextual Dates to `YYYY-MM-DD`
def convert_to_iso_date(date_str):
    today = datetime.date.today()

    if date_str.lower() == "tomorrow":
        return (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    if "in " in date_str and " days" in date_str:
        try:
            days = int(date_str.split("in ")[1].split(" days")[0])
            return (today + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        except:
            return date_str  # If parsing fails, return original text

    if "next" in date_str.lower():
        weekdays = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6
        }
        for day in weekdays:
            if day in date_str.lower():
                today_weekday = today.weekday()
                target_weekday = weekdays[day]
                days_until_next = (target_weekday - today_weekday + 7) % 7
                if days_until_next == 0:
                    days_until_next += 7  # If today is already the target day, move to next week
                return (today + datetime.timedelta(days=days_until_next)).strftime("%Y-%m-%d")

    try:
        return datetime.datetime.strptime(date_str + f" {today.year}", "%B %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return date_str  # Return original if conversion fails

# ✅ Streamlit UI
st.title("✈️ Flight Search Chatbot")
st.markdown("💬 **Ask me to find flights for you!** (e.g., 'Find
