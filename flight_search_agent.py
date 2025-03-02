import os
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

# ✅ Function to Extract IATA Code (Cache First)
iata_cache = {}

def get_iata_code(city_name):
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

    if date_str == "tomorrow":
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

# ✅ Flight Search
def search_flights(origin_code, destination_code, departure_date, adults):
    try:
        st.write(f"🔍 **Searching flights...**")
        response = amadeus.shopping.flight_offers_search.get(
            originLocationCode=origin_code,
            destinationLocationCode=destination_code,
            departureDate=departure_date,
            adults=adults,
            travelClass="ECONOMY",
            currencyCode="USD"
        )
        return response.data if response.data else None
    except ResponseError as e:
        return None

# ✅ Display chat history
for msg in st.session_state.chat_history:
    st.chat_message(msg["role"]).write(msg["content"])

# ✅ User Input
user_input = st.chat_input("Type your flight request here...")

if user_input:
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    st.chat_message("user").write(user_input)

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

        # ✅ Fix AttributeError: Ensure departure_date is a string before calling replace()
        raw_date = flight_details.get("departure_date", "")
        if raw_date:
            raw_date = raw_date.replace(",", "").strip()
        departure_date = convert_to_iso_date(raw_date)

        adults = flight_details.get("adults", 1)

        # ✅ Store missing details in session state
        missing_details = []
        if not origin_city:
            missing_details.append("📍 Where are you departing from?")
            st.session_state["missing_origin"] = True
        else:
            st.session_state["missing_origin"] = False
        
        if not destination_city:
            missing_details.append("🏁 Where do you want to fly to?")
            st.session_state["missing_destination"] = True
        else:
            st.session_state["missing_destination"] = False

        if not departure_date:
            missing_details.append("📅 What date do you want to travel?")
            st.session_state["missing_date"] = True
        else:
            st.session_state["missing_date"] = False

        if adults is None:
            missing_details.append("👨‍👩‍👧 How many adults are traveling?")
            st.session_state["missing_adults"] = True
        else:
            st.session_state["missing_adults"] = False

        # ✅ If missing details, ask the user persistently
        if missing_details:
            prompt = "\n".join(missing_details)
            st.session_state.chat_history.append({"role": "assistant", "content": prompt})
            st.chat_message("assistant").write(prompt)
            st.stop()

        # ✅ Convert to IATA Codes
        origin_code = get_iata_code(origin_city)
        destination_code = get_iata_code(destination_city)
        if not origin_code or not destination_code:
            error_msg = "❌ Could not determine airport codes. Please check your input."
            st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
            st.chat_message("assistant").write(error_msg)
            st.stop()

        # ✅ Search Flights
        flights = search_flights(origin_code, destination_code, departure_date, adults)

        if flights:
            flight_data = []
            for flight in flights:
                segments = flight["itineraries"][0]["segments"]
                flight_info = {
                    "Airline": segments[0]["carrierCode"],
                    "Flight Number": segments[0]["number"],
                    "Departure": segments[0]["departure"]["iataCode"] + " " + segments[0]["departure"]["at"],
                    "Arrival": segments[-1]["arrival"]["iataCode"] + " " + segments[-1]["arrival"]["at"],
                    "Duration": flight["itineraries"][0]["duration"],
                    "Price (USD)": flight["price"]["total"]
                }
                flight_data.append(flight_info)

            df = pd.DataFrame(flight_data)
            response_msg = "### ✈️ Available Flights"
            st.session_state.chat_history.append({"role": "assistant", "content": response_msg})
            st.chat_message("assistant").write(response_msg)
            st.dataframe(df)
        else:
            error_msg = "❌ No flights found. Please adjust your search."
            st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
            st.chat_message("assistant").write(error_msg)

    except json.JSONDecodeError:
        error_msg = "🚨 Error: AI response is not valid JSON."
        st.session_state.chat_history.append({"role": "assistant", "content": error_msg})
        st.chat_message("assistant").write(error_msg)
