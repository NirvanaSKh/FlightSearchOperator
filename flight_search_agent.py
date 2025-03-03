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

# ✅ Initialize session state for tracking user input
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "flight_request" not in st.session_state:
    st.session_state.flight_request = {
        "origin": None,
        "destination": None,
        "departure_date": None,
        "adults": None,
        "children": [],
        "infants": 0,
        "direct_flight": False
    }

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

# ✅ Extract numbers from user responses
def extract_number(text):
    """Extract numeric values from a string."""
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None

# ✅ Function to Check Missing Details and Ask One at a Time
def ask_for_missing_details():
    """Ask the user for missing flight details one at a time."""
    missing_questions = {
        "origin": "📍 Where are you departing from?",
        "destination": "🏁 Where do you want to fly to?",
        "departure_date": "📅 What date do you want to travel?",
        "adults": "👨‍👩‍👧 How many adults are traveling?"
    }

    for key, question in missing_questions.items():
        if not st.session_state.flight_request[key]:
            st.session_state.chat_history.append({"role": "assistant", "content": question})
            st.chat_message("assistant").write(question)
            return False  # Stops after asking one question

    return True  # All details are available

# ✅ Flight Search Function
def search_flights():
    """Fetch and return top 5 cheapest flight offers from Amadeus API."""
    flight_request = st.session_state.flight_request

    if None in [flight_request["origin"], flight_request["destination"], flight_request["departure_date"], flight_request["adults"]]:
        return None  # Wait until all required info is collected

    origin_code = get_iata_code(flight_request["origin"])
    destination_code = get_iata_code(flight_request["destination"])
    departure_date = convert_to_iso_date(flight_request["departure_date"])

    if not origin_code or not destination_code or not departure_date:
        return None  # Don't proceed if IATA codes or date conversion failed

    st.write(f"🔍 **Searching flights...**")
    st.write(f"✈️ From: {origin_code} | 🏁 To: {destination_code} | 📅 Date: {departure_date} | "
             f"👨‍👩‍👧 Adults: {flight_request['adults']} | 🧒 Children: {len(flight_request['children'])} | 👶 Infants: {flight_request['infants']} | 🚀 Direct: {flight_request['direct_flight']}")

    time.sleep(1)

    api_params = {
        "originLocationCode": origin_code,
        "destinationLocationCode": destination_code,
        "departureDate": departure_date,
        "adults": flight_request["adults"],
        "children": len(flight_request["children"]),
        "infants": flight_request["infants"],
        "travelClass": "ECONOMY",
        "currencyCode": "USD",
        "max": 10
    }

    if flight_request["direct_flight"]:
        api_params["nonStop"] = True  

    response = amadeus.shopping.flight_offers_search.get(**api_params)

    if not response.data:
        return None

    flight_data = []
    for flight in response.data:
        flight_data.append({
            "Airline": flight["validatingAirlineCodes"][0],
            "Flight Number": flight["itineraries"][0]["segments"][0]["number"],
            "Stops": len(flight["itineraries"][0]["segments"]) - 1,
            "Total Price (USD)": flight["price"]["total"]
        })

    flight_data = sorted(flight_data, key=lambda x: float(x["Total Price (USD)"]))[:5]
    return flight_data

# ✅ Streamlit UI
st.title("✈️ Flight Search Agent")

for msg in st.session_state.chat_history:
    st.chat_message(msg["role"]).write(msg["content"])

user_input = st.chat_input("Type your flight request here...")

if user_input:
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    st.chat_message("user").write(user_input)

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "system", "content": "Extract flight details from user input as JSON."},
                      {"role": "user", "content": user_input}]
        )
        flight_details = json.loads(response.choices[0].message.content)

    except json.JSONDecodeError:
        st.chat_message("assistant").write("I didn't understand that. Could you clarify?")
        st.stop()

    for key in flight_details:
        if flight_details[key]:  
            st.session_state.flight_request[key] = flight_details[key]  

    # ✅ Extract number of adults from response
    if isinstance(user_input, str) and "adults" in st.session_state.flight_request and not st.session_state.flight_request["adults"]:
        st.session_state.flight_request["adults"] = extract_number(user_input)

    if not ask_for_missing_details():
        st.stop()

    flights = search_flights()
    if flights:
        df = pd.DataFrame(flights)
        st.write("### ✈️ Top 5 Cheapest Flights")
        st.dataframe(df)
