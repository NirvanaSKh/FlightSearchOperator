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
    except ResponseError:
        return None
    return None

# ✅ Function to Convert Contextual Dates to `YYYY-MM-DD`
def convert_to_iso_date(date_str):
    """Convert contextual dates like 'tomorrow' or 'in 3 days' to YYYY-MM-DD"""
    today = datetime.date.today()

    if not date_str or not isinstance(date_str, str) or date_str.strip() == "":
        return None  # This will trigger the clarification step

    date_str = date_str.lower().strip()

    if date_str == "tomorrow":
        return (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    if "in " in date_str and " days" in date_str:
        try:
            days = int(date_str.split("in ")[1].split(" days")[0])
            return (today + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        except ValueError:
            return None  

    try:
        return datetime.datetime.strptime(date_str + f" {today.year}", "%B %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None  # Will trigger clarification

# ✅ Function to Ask for Missing Details
def request_missing_info(missing_fields):
    clarification_needed = []
    if "origin" in missing_fields:
        clarification_needed.append("📍 Where are you departing from?")
    if "destination" in missing_fields:
        clarification_needed.append("🏁 Where are you flying to?")
    if "departure_date" in missing_fields:
        clarification_needed.append("📅 What date do you want to travel?")
    if "adults" in missing_fields:
        clarification_needed.append("👨‍👩‍👧 How many adults are traveling?")
    if "children" in missing_fields:
        clarification_needed.append("👶 How many children (and their ages)?")
    
    return "\n".join(clarification_needed) if clarification_needed else None

# ✅ Streamlit UI
st.title("✈️ Flight Search Agent")
st.markdown("💬 **Ask me to find flights for you!** (e.g., 'Find me a direct flight from London to Delhi on May 5 for 2 adults')")

# ✅ User Input
user_input = st.text_input("You:", placeholder="Type your flight request here and press Enter...")

if user_input:
    # ✅ Extract Flight Details Using OpenAI GPT-3.5 Turbo
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Extract flight details from the user's input. Return output in valid JSON format with keys: origin, destination, departure_date, return_date (null if one-way), adults, children (list of ages), direct_flight (true/false)."},
            {"role": "user", "content": user_input}
        ]
    )

    flight_info = response.choices[0].message.content

    try:
        flight_details = json.loads(flight_info)
        
        # ✅ Debugging: Print extracted details
        st.write("🔍 Extracted Flight Details (Raw JSON):", flight_details)

        # ✅ Validate Extracted Data
        missing_fields = []
        origin_city = flight_details.get("origin")
        destination_city = flight_details.get("destination")
        
        # ✅ Ensure departure date is properly converted
        extracted_date = flight_details.get("departure_date")
        departure_date = convert_to_iso_date(extracted_date) if extracted_date else None
        
        # ✅ If `return_date` is null, set it to `"One-way"`
        return_date = flight_details.get("return_date")
        return_date = convert_to_iso_date(return_date) if return_date else "One-way"

        adults = flight_details.get("adults")
        children = flight_details.get("children", [])
        direct_flight_requested = flight_details.get("direct_flight", False)

        # ✅ Check for missing fields
        if not origin_city: missing_fields.append("origin")
        if not destination_city: missing_fields.append("destination")
        if not departure_date: missing_fields.append("departure_date")
        if adults is None: missing_fields.append("adults")
        if children is None: missing_fields.append("children")

        if missing_fields:
            clarification_message = request_missing_info(missing_fields)
            st.warning(clarification_message)
            st.stop()

        # ✅ Convert to IATA Codes
        origin_code = get_iata_code(origin_city)
        destination_code = get_iata_code(destination_city)
        if not origin_code or not destination_code:
            st.error("❌ Could not determine airport codes for your cities. Please check your input.")
            st.stop()

        # ✅ Display Flight Search Query
        st.markdown(f"""
        **Your Flight Search Query**
        - ✈️ From: {origin_city}
        - 🏁 To: {destination_city}
        - 📅 Departure: {departure_date}
        - 🔄 Return: {return_date}
        - 👨‍👩‍👧 Adults: {adults}
        - 👶 Children: {", ".join([f"{age} years old" for age in children]) if children else "None"}
        - 🚀 Direct Flight: {"Yes" if direct_flight_requested else "No"}
        """)

        # ✅ Search for Flights
        try:
            response = amadeus.shopping.flight_offers_search.get(
                originLocationCode=origin_code,
                destinationLocationCode=destination_code,
                departureDate=departure_date,
                adults=adults,
                currencyCode="GBP",
                max=10
            )
            flights = response.data

            if not flights:
                st.warning("❌ No flights found. Would you like to try a different date or airport?")
                st.stop()

            # ✅ Format Flight Results
            flight_results = []
            for flight in flights:
                price = float(flight["price"]["total"])
                airline = flight["validatingAirlineCodes"][0]
                stops = len(flight["itineraries"][0]["segments"]) - 1
                duration = flight["itineraries"][0]["duration"]

                flight_results.append({
                    "Airline": airline,
                    "Stops": stops,
                    "Duration": duration,
                    "Price (GBP)": f"£{price:.2f}"
                })

            df = pd.DataFrame(flight_results)
            st.write("🛫 **Flight Results:**")
            st.dataframe(df)

        except ResponseError:
            st.error("❌ Error retrieving flight data. Please try again later.")

    except json.JSONDecodeError:
        st.error("🚨 Error: AI response is not valid JSON.")
