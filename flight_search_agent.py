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

# ✅ Initialize session state for chat history
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "missing_details" not in st.session_state:
    st.session_state.missing_details = {}

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
    except ResponseError:
        return None

# ✅ Convert Date to `YYYY-MM-DD`
def convert_to_iso_date(date_str):
    """Convert natural language dates like 'tomorrow' to ISO format (YYYY-MM-DD)."""
    today = datetime.date.today()
    if not date_str or not isinstance(date_str, str):
        return None

    date_str = date_str.lower().strip()

    if date_str in ["tomorrow", "tmrw"]:
        return (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    match = re.search(r"in (\d+) days", date_str)
    if match:
        days = int(match.group(1))
        return (today + datetime.timedelta(days=days)).strftime("%Y-%m-%d")

    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)

    try:
        return datetime.datetime.strptime(date_str + f" {today.year}", "%d %B %Y").strftime("%Y-%m-%d")
    except ValueError:
        try:
            return datetime.datetime.strptime(date_str + f" {today.year}", "%B %d %Y").strftime("%Y-%m-%d")
        except ValueError:
            return None

# ✅ Flight Search with Retry for Direct Flights & Correct Infant Pricing
def search_flights(origin_code, destination_code, departure_date, adults, children, infants, direct_flight):
    """Fetch and return top 5 cheapest flight offers from Amadeus API, retrying if direct flights fail."""
    try:
        if not origin_code or not destination_code or not departure_date:
            st.error("❌ Missing valid airport codes or date. Please check your input.")
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
            "infants": infants,
            "travelClass": "ECONOMY",
            "currencyCode": "USD",
            "max": 10
        }

        if direct_flight:
            api_params["nonStop"] = True  

        try:
            response = amadeus.shopping.flight_offers_search.get(**api_params)
        except ResponseError as e:
            # ✅ Retry without `nonStop=True` if direct flight search causes a 400 error
            if e.code == 400 and direct_flight:
                st.warning("⚠️ No direct flights found. Searching for connecting flights instead.")
                del api_params["nonStop"]
                response = amadeus.shopping.flight_offers_search.get(**api_params)
            else:
                raise e  # Re-raise other errors

        if not response.data:
            return None

        flight_data = []
        for flight in response.data:
            segments = flight["itineraries"][0]["segments"]
            num_stops = len(segments) - 1
            total_price = flight["price"]["total"]

            if direct_flight and num_stops > 0:
                continue  

            price_per_adult, price_per_child, price_per_infant = "N/A", "N/A", "N/A"

            for traveler in flight["travelerPricings"]:
                traveler_type = traveler["travelerType"]
                traveler_price = traveler["price"]["total"]

                if traveler_type == "ADULT":
                    price_per_adult = traveler_price
                elif traveler_type == "CHILD":
                    price_per_child = traveler_price
                elif traveler_type in ["HELD_INFANT", "SEATED_INFANT"]:
                    price_per_infant = traveler_price  

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

        flight_data = sorted(flight_data, key=lambda x: float(x["Total Price (USD)"]))[:5]

        return flight_data
    except ResponseError as e:
        st.error(f"🚨 API Error: {e.code} - {e.description}")
        return None

# ✅ Streamlit UI
st.title("✈️ Flight Search Agent")

for msg in st.session_state.chat_history:
    st.chat_message(msg["role"]).write(msg["content"])

user_input = st.chat_input("Type your flight request here...")

if user_input:
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    st.chat_message("user").write(user_input)

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "system", "content": "Extract flight details from user input as JSON."},
                  {"role": "user", "content": user_input}]
    )

    flight_details = json.loads(response.choices[0].message.content)

    flights = search_flights(get_iata_code(flight_details["origin"]), get_iata_code(flight_details["destination"]),
                             convert_to_iso_date(flight_details["departure_date"]), flight_details["adults"],
                             flight_details.get("children", []), flight_details.get("infants", 0),
                             flight_details.get("direct_flight", False))

    if flights:
        df = pd.DataFrame(flights)
        st.write("### ✈️ Top 5 Cheapest Flights")
        st.dataframe(df)
