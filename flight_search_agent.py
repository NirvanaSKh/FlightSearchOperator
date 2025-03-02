import os
import time
import streamlit as st
import datetime
import pandas as pd
from amadeus import Client, ResponseError
import openai
import json
import re

# ✅ Read API keys
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

# ✅ Function to Extract IATA Code (Cache First)
iata_cache = {}

def get_iata_code(city_name):
    """Fetch IATA code for a given city."""
    if city_name in iata_cache:
        return iata_cache[city_name]
    try:
        response = amadeus.reference_data.locations.get(keyword=city_name, subType="CITY,AIRPORT")
        if response.data:
            iata_code = response.data[0]["iataCode"]
            iata_cache[city_name] = iata_code
            return iata_code
    except ResponseError:
        return None

# ✅ Convert Date to `YYYY-MM-DD`
def convert_to_iso_date(date_str):
    """Convert natural language dates to ISO format."""
    today = datetime.date.today()
    if not date_str or not isinstance(date_str, str):
        return None

    date_str = date_str.lower().strip()
    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)  # Remove ordinal suffixes

    try:
        return datetime.datetime.strptime(date_str + f" {today.year}", "%d %B %Y").strftime("%Y-%m-%d")
    except ValueError:
        try:
            return datetime.datetime.strptime(date_str + f" {today.year}", "%B %d %Y").strftime("%Y-%m-%d")
        except ValueError:
            return None

# ✅ Flight Search with Sorting and Filtering
def search_flights(origin_code, destination_code, departure_date, adults):
    """Fetch and return top 5 cheapest flight offers from Amadeus API."""
    try:
        st.write(f"🔍 **Searching flights...**")
        time.sleep(1)  # Prevent hitting API rate limits

        response = amadeus.shopping.flight_offers_search.get(
            originLocationCode=origin_code,
            destinationLocationCode=destination_code,
            departureDate=departure_date,
            adults=adults,
            travelClass="ECONOMY",
            currencyCode="USD",
            max=10  # Fetch 10 flights and sort by price
        )

        if not response.data:
            return None

        # ✅ Process and Sort Flights by Cheapest Price
        flight_data = []
        for flight in response.data:
            segments = flight["itineraries"][0]["segments"]
            price_per_adult = flight["price"]["base"]
            price_per_infant = flight["travelerPricings"][0]["price"]["total"] if "infant" in flight["travelerPricings"][0]["travelerType"].lower() else "N/A"
            total_price = flight["price"]["total"]
            num_stops = len(segments) - 1

            flight_data.append({
                "Airline": segments[0]["carrierCode"],
                "Flight Number": segments[0]["number"],
                "Departure": f"{segments[0]['departure']['iataCode']} {segments[0]['departure']['at']}",
                "Arrival": f"{segments[-1]['arrival']['iataCode']} {segments[-1]['arrival']['at']}",
                "Stops": num_stops,
                "Price per Adult (USD)": price_per_adult,
                "Price per Infant (USD)": price_per_infant,
                "Total Price (USD)": total_price
            })

        # ✅ Sort by total price and keep only top 5
        flight_data = sorted(flight_data, key=lambda x: float(x["Total Price (USD)"]))[:
