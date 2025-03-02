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
    if not city_name:
        return None
    if city_name in iata_cache:
        return iata_cache[city_name]
    try:
        response = amadeus.reference_data.locations.get(keyword=city_name, subType="CITY,AIRPORT")
        if response.data:
            iata_code = response.data[0]["iataCode"]
            iata_cache[city_name] = iata_code
            return iata_code
    except ResponseError as e:
        return None

# ✅ Convert Date to `YYYY-MM-DD`
def convert_to_iso_date(date_str):
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

# ✅ Flight Search with Fixes for IATA Codes and Infants
def search_flights(origin_code, destination_code, departure_date, adults, children, infants, direct_flight):
    """Fetch and return top 5 cheapest direct flight offers from Amadeus API."""
    try:
        if not origin_code or not destination_code:
            st.error("❌ Missing valid airport codes. Please check city names.")
            return None

        st.write(f"🔍 **Searching flights...**")
        st.write(f"✈️ From: {origin_code} | 🏁 To: {destination_code} | 📅 Date: {departure_date} | "
                 f"👨‍👩‍👧 Adults: {adults} | 🧒 Children: {len(children)} | 👶 Infants: {infants} | 🚀 Direct: {direct_flight}")

        time.sleep(1)  # Prevent hitting API rate limits

        # ✅ Build API request with proper parameters
        api_params = {
            "originLocationCode": origin_code,
            "destinationLocationCode": destination_code,
            "departureDate": departure_date,
            "adults": adults,
            "children": len(children),
            "infants": infants,  # ✅ Explicitly passing infants
            "travelClass": "ECONOMY",
            "currencyCode": "USD",
            "max": 10
        }

        if direct_flight:
            api_params["nonStop"] = True  # ✅ Ensure direct flights

        response = amadeus.shopping.flight_offers_search.get(**api_params)

        if not response.data:
            return None

        # ✅ Process and Sort Flights by Cheapest Price
        flight_data = []
        for flight in response.data:
            segments = flight["itineraries"][0]["segments"]
            num_stops = len(segments) - 1
            total_price = flight["price"]["total"]

            # ✅ Ensure only direct flights are included if requested
            if direct_flight and num_stops > 0:
                continue  # Skip flights with stops

            # ✅ Extract pricing per traveler type
            price_per_adult, price_per_child, price_per_infant = "N/A", "N/A", "N/A"

            for traveler in flight["travelerPricings"]:
                traveler_type = traveler["travelerType"]
                traveler_price = traveler["price"]["total"]

                if traveler_type == "ADULT":
                    price_per_adult = traveler_price
                elif traveler_type == "CHILD":
                    price_per_child = traveler_price
                elif traveler_type in ["HELD_INFANT", "SEATED_INFANT"]:
                    price_per_infant = traveler_price  # ✅ Ensure infant price is captured

            flight_data.append({
                "Airline": segments[0]["carrierCode"],
                "Flight Number": segments[0]["number"],
                "Departure": f"{segments[0]['departure']['iataCode']} {segments[0]['departure']['at']}",
                "Arrival": f"{segments[-1]['arrival']['iataCode']} {segments[-1]['arrival']['at']}",
                "Stops": num_stops,
                "Price per Adult (USD)": price_per_adult,
                "Price per Child (USD)": price_per_child,
                "Price per Infant (USD)": price_per_infant,
                "Total Price (USD)": total_price
            })

        # ✅ Sort by total price and keep only top 5
        flight_data = sorted(flight_data, key=lambda x: float(x["Total Price (USD)"]))[:5]

        return flight_data
    except ResponseError as e:
        st.error(f"🚨 API Error: {e.code} - {e.description}")
        return None

# ✅ Streamlit UI
st.title("✈️ Flight Search Agent")

user_input = st.text_input("You:", placeholder="Type your flight request here and press Enter...")

if user_input:
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Extract flight details from the user's input. Return output in valid JSON format with keys: origin, destination, departure_date, return_date (null if one-way), adults, children (list of ages), infants, direct_flight (true/false)."},
            {"role": "user", "content": user_input}
        ]
    )

    try:
        flight_details = json.loads(response.choices[0].message.content)

        origin_city = flight_details.get("origin")
        destination_city = flight_details.get("destination")

        raw_date = flight_details.get("departure_date", "")
        if raw_date:
            raw_date = raw_date.replace(",", "").strip()
        departure_date = convert_to_iso_date(raw_date)

        adults = flight_details.get("adults", 1)
        children = flight_details.get("children", [])
        infants = flight_details.get("infants", 0)
        direct_flight = flight_details.get("direct_flight", False)

        # ✅ Get IATA Codes
        origin_code = get_iata_code(origin_city)
        destination_code = get_iata_code(destination_city)

        # ✅ Search Flights
        flights = search_flights(origin_code, destination_code, departure_date, adults, children, infants, direct_flight)

        if flights:
            df = pd.DataFrame(flights)
            st.write("### ✈️ Top 5 Cheapest Direct Flights")
            st.dataframe(df)
        else:
            st.error("❌ No direct flights found. Please adjust your search.")

    except json.JSONDecodeError:
        st.error("🚨 Error: AI response is not valid JSON.")
