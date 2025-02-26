import streamlit as st
import datetime
import pandas as pd
from amadeus import Client, ResponseError
import openai
import os
import json

# ✅ Read API keys from Streamlit Secrets or fallback to environment variables
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

# ✅ Streamlit UI
st.title("✈️ Flight Search Chatbot")
st.markdown("💬 **Ask me to find flights for you!** (e.g., 'Find me a flight from Berlin to Mumbai on May 5 for 2 adults')")

# ✅ Function to Get IATA Code for Any City Using Amadeus API
def get_iata_code(city_name):
    """Retrieve the IATA airport code for a given city using Amadeus API."""
    try:
        response = amadeus.reference_data.locations.get(
            keyword=city_name,
            subType="CITY,AIRPORT"
        )
        if response.data:
            return response.data[0]["iataCode"]  # Get first matching IATA code
        else:
            return None  # No matching IATA code found
    except ResponseError as error:
        st.error(f"❌ Error fetching IATA code for {city_name}: {error}")
        return None

# ✅ Function to Convert Date to `YYYY-MM-DD`
def convert_to_iso_date(date_str):
    try:
        return datetime.datetime.strptime(date_str + " 2025", "%B %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return date_str  # Return original if conversion fails

# ✅ User Input
user_input = st.text_input("You:", placeholder="Type your flight request here and press Enter...")

if user_input:
    # ✅ Step 4: Extract Flight Details Using OpenAI GPT
    response = client.chat.completions.create(
        model="gpt-4",
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

        # ✅ Get IATA codes dynamically
        origin = get_iata_code(origin_city)
        destination = get_iata_code(destination_city)

        if not origin or not destination:
            st.error(f"❌ Could not determine airport codes for '{origin_city}' or '{destination_city}'. Please check your input.")
            st.stop()

        departure_date = convert_to_iso_date(flight_details.get("departure_date", "2025-06-10"))
        return_date = convert_to_iso_date(flight_details.get("return_date", None)) if flight_details.get("return_date") else None
        adults = flight_details.get("adults", 1)

        # ✅ Fix `children` issue
        children_ages = flight_details.get("children", [])
        children_ages = [age for age in children_ages if isinstance(age, (int, float))]  # Remove `null` values
        children_count = len(children_ages)  # ✅ Convert list to count
        infants_count = sum(1 for age in children_ages if age < 2)  # ✅ Count infants properly

        # ✅ Call Flight Search Function
        def search_flights():
            try:
                params = {
                    "originLocationCode": origin,
                    "destinationLocationCode": destination,
                    "departureDate": departure_date,
                    "adults": adults,
                    "children": children_count,  # ✅ Send count, not a list
                    "infants": infants_count,  # ✅ Fixes infant count issue
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

                # ✅ Extract Flight Details
                flight_results = []
                for flight in flights:
                    price = float(flight["price"]["total"])
                    airline = flight["validatingAirlineCodes"][0] if "validatingAirlineCodes" in flight else "Unknown"
                    departure = flight["itineraries"][0]["segments"][0]["departure"]["at"]
                    arrival = flight["itineraries"][0]["segments"][-1]["arrival"]["at"]
                    duration = flight["itineraries"][0]["duration"]
                    stopovers = len(flight["itineraries"][0]["segments"]) - 1  # Stops count

                    total_price = price * (adults + children_count)

                    flight_results.append({
                        "Airline": airline,
                        "Departure": departure,
                        "Arrival": arrival,
                        "Duration": duration,
                        "Stops": stopovers,
                        "Price per Person (GBP)": f"£{price:.2f}",
                        "Total Price (GBP)": f"£{total_price:.2f}"
                    })

                df = pd.DataFrame(flight_results).sort_values(by="Total Price (GBP)")

                st.write("🛫 **Flight Results (Sorted by Price)**:")
                st.dataframe(df)

            except ResponseError as error:
                st.error(f"❌ API Error: {error}")

        search_flights()

    except json.JSONDecodeError as e:
        st.error(f"🚨 Error: AI response is not valid JSON. OpenAI output may have formatting issues. {e}")
