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

        # ✅ Validate Extracted Data
        origin_city = flight_details.get("origin")
        destination_city = flight_details.get("destination")
        departure_date = convert_to_iso_date(flight_details.get("departure_date"))
        return_date = convert_to_iso_date(flight_details.get("return_date")) if flight_details.get("return_date") else "One-way"
        adults = flight_details.get("adults")
        children = flight_details.get("children", [])
        direct_flight_requested = flight_details.get("direct_flight", False)

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
                price_per_adult = float(flight["price"]["total"])
                infant_price = price_per_adult * 0.5 if any(age < 2 for age in children) else 0  # Discounted infant price
                total_price = (adults * price_per_adult) + (infant_price * sum(1 for age in children if age < 2))

                airline = flight.get("validatingAirlineCodes", ["Unknown"])[0]
                itineraries = flight["itineraries"][0]
                stops_count = len(itineraries["segments"]) - 1
                total_duration = itineraries["duration"]

                stop_details = []
                for segment in itineraries["segments"][:-1]:  # Exclude final arrival segment
                    stop_airport = segment["arrival"]["iataCode"]
                    stop_duration = segment.get("stopDuration", "N/A")
                    stop_details.append(f"{stop_airport} ({stop_duration})")

                stop_details_str = ", ".join(stop_details) if stop_details else "Direct"

                flight_results.append({
                    "Airline": airline,
                    "Stops": stops_count,
                    "Stop Details": stop_details_str,
                    "Total Duration": total_duration,
                    "Price per Adult (GBP)": f"£{price_per_adult:.2f}",
                    "Price per Infant (GBP)": f"£{infant_price:.2f}" if infant_price > 0 else "N/A",
                    "Total Price (GBP)": f"£{total_price:.2f}"
                })

            df = pd.DataFrame(flight_results)
            st.write("🛫 **Flight Results:**")
            st.dataframe(df)

        except ResponseError:
            st.error("❌ Error retrieving flight data. Please try again later.")

    except json.JSONDecodeError:
        st.error("🚨 Error: AI response is not valid JSON.")
