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
st.markdown("💬 **Ask me to find flights for you!** (e.g., 'Find me a flight from Berlin to Mumbai on May 5 for 2 adults')")

# ✅ User Input
user_input = st.text_input("You:", placeholder="Type your flight request here and press Enter...")

if user_input:
    # ✅ Step 4: Extract Flight Details Using OpenAI GPT
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Extract flight details from the user's input. Return output in valid JSON format with keys: origin, destination, departure_date, return_date (null if one-way), adults, children (list of ages). Ensure children list contains only numbers and is empty if there are no children."},
            {"role": "user", "content": user_input}
        ]
    )

    flight_info = response.choices[0].message.content  # ✅ Corrected OpenAI API usage

    st.write("🔍 **AI Extracted Flight Details:**")
    st.code(flight_info, language="json")  # ✅ Shows JSON output for debugging

    try:
        # ✅ Parse AI response using `json.loads()`
        flight_details = json.loads(flight_info)

        # ✅ Convert Data for Amadeus API Compatibility
        origin_city = flight_details.get("origin", "")
        destination_city = flight_details.get("destination", "")

        # ✅ Get IATA codes dynamically (cached to reduce API calls)
        origin = get_iata_code(origin_city)
        destination = get_iata_code(destination_city)

        if not origin or not destination:
            st.error(f"❌ Could not determine airport codes for '{origin_city}' or '{destination_city}'. Please check your input.")
            st.stop()

        departure_date = convert_to_iso_date(flight_details.get("departure_date", "2025-06-10"))
        return_date = convert_to_iso_date(flight_details.get("return_date", None)) if flight_details.get("return_date") else None
        adults = flight_details.get("adults", 1)
        children = flight_details.get("children", [])
        total_passengers = adults + len(children)

        # ✅ Search for Flights
        def search_flights():
            try:
                params = {
                    "originLocationCode": origin,
                    "destinationLocationCode": destination,
                    "departureDate": departure_date,
                    "adults": adults,
                    "currencyCode": "GBP",
                    "max": 10
                }

                if return_date:
                    params["returnDate"] = return_date

                response = amadeus.shopping.flight_offers_search.get(**params)
                flights = response.data

                if not flights:
                    st.error("❌ No flights found. Try different dates or locations.")
                    return

                # ✅ Extract and Format Flight Data
                flight_results = []
                for flight in flights:
                    price_per_person = float(flight.get("price", {}).get("total", "0.00"))
                    total_price = price_per_person * total_passengers
                    airline = flight.get("validatingAirlineCodes", ["Unknown"])[0]
                    segments = flight.get("itineraries", [])[0].get("segments", [])

                    if not segments:
                        continue

                    departure_airport = segments[0].get("departure", {}).get("iataCode", "N/A")
                    departure_time = segments[0].get("departure", {}).get("at", "N/A")
                    arrival_airport = segments[-1].get("arrival", {}).get("iataCode", "N/A")
                    arrival_time = segments[-1].get("arrival", {}).get("at", "N/A")
                    duration = flight.get("itineraries", [])[0].get("duration", "N/A")
                    stopovers = len(segments) - 1

                    flight_results.append({
                        "Airline": airline,
                        "From": departure_airport,
                        "Departure Time": departure_time,
                        "To": arrival_airport,
                        "Arrival Time": arrival_time,
                        "Duration": duration,
                        "Stops": stopovers,
                        "Price per Person (GBP)": f"£{price_per_person:.2f}",
                        "Total Price (GBP)": f"£{total_price:.2f}"
                    })

                df = pd.DataFrame(flight_results)
                st.write("🛫 **Flight Results:**")
                st.dataframe(df)

            except ResponseError as error:
                st.error(f"❌ API Error: {error}")

        search_flights()

    except json.JSONDecodeError as e:
        st.error(f"🚨 Error: AI response is not valid JSON. OpenAI output may have formatting issues. {e}")
