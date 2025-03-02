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
        flight_data = sorted(flight_data, key=lambda x: float(x["Total Price (USD)"]))[:5]

        return flight_data
    except ResponseError as e:
        st.error(f"🚨 API Error: {e.code} - {e.description}")
        return None

# ✅ Streamlit UI
st.title("✈️ Flight Search Agent")
st.markdown("💬 **Ask me to find flights for you!** (e.g., 'Find me a direct flight from London to Delhi on May 5 for 2 adults')")

# ✅ User Input
user_input = st.text_input("You:", placeholder="Type your flight request here and press Enter...")

if user_input:
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Extract flight details from the user's input. Return output in valid JSON format with keys: origin, destination, departure_date, return_date (null if one-way), adults, children (list of ages)."},
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

        # ✅ Convert to IATA Codes
        origin_code = get_iata_code(origin_city)
        destination_code = get_iata_code(destination_city)
        if not origin_code or not destination_code:
            st.error("❌ Could not determine airport codes. Please check your input.")
            st.stop()

        # ✅ Search Flights
        flights = search_flights(origin_code, destination_code, departure_date, adults)

        if flights:
            df = pd.DataFrame(flights)
            st.write("### ✈️ Top 5 Cheapest Flights")
            st.dataframe(df)
        else:
            st.error("❌ No flights found. Please adjust your search.")

    except json.JSONDecodeError:
        st.error("🚨 Error: AI response is not valid JSON.")
