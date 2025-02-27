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

def get_iata_code(city_name):
    if city_name in iata_cache:
        return iata_cache[city_name]
    try:
        response = amadeus.reference_data.locations.get(
            keyword=city_name,
            subType="CITY,AIRPORT"
        )
        if response.data:
            iata_code = response.data[0]["iataCode"]
            iata_cache[city_name] = iata_code
            return iata_code
        else:
            return None
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
            return date_str  

    try:
        return datetime.datetime.strptime(date_str + f" {today.year}", "%B %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return date_str  

# ✅ Streamlit UI
st.title("✈️ Flight Search Chatbot")
st.markdown("💬 **Ask me to find flights for you!** (e.g., 'Find me a direct flight from London to Delhi on May 5 for 2 adults')")

# ✅ Apply Custom CSS for Adaptive Query Table
st.markdown("""
    <style>
        .custom-table-container {
            width: 100%;
            max-width: 100%;
            overflow-x: auto;
            display: block;
        }
        .custom-table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 18px;
        }
        .custom-table th, .custom-table td {
            padding: 10px;
            border-bottom: 1px solid #ddd;
        }
        .custom-table th {
            background-color: #004080;
            color: white;
            text-align: left;
        }
    </style>
""", unsafe_allow_html=True)

# ✅ User Input
user_input = st.text_input("You:", placeholder="Type your flight request here and press Enter...")

if user_input:
    # ✅ Step 4: Extract Flight Details Using OpenAI GPT-3.5 Turbo (Free Model)
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Extract flight details from the user's input. Return output in valid JSON format with keys: origin, destination, departure_date, return_date (null if one-way), adults, children (list of ages), direct_flight (true/false). Ensure children list contains only numbers and is empty if there are no children."},
            {"role": "user", "content": user_input}
        ]
    )

    flight_info = response.choices[0].message.content 

    # ✅ Parse the AI response into a JSON dictionary
    try:
        flight_details = json.loads(flight_info)

        # ✅ Convert Key Details for Display
        origin_city = flight_details.get("origin", "")
        destination_city = flight_details.get("destination", "")
        departure_date = convert_to_iso_date(flight_details.get("departure_date", "2025-06-10"))
        return_date = convert_to_iso_date(flight_details.get("return_date", None)) if flight_details.get("return_date") else "One-way"
        adults = flight_details.get("adults", 1)
        children = flight_details.get("children", [])
        direct_flight_requested = flight_details.get("direct_flight", False)

        # ✅ Format Children’s Ages
        children_str = ", ".join([f"{age} years old" for age in children]) if children else "None"

        # ✅ **Display Extracted Flight Query in Adaptive Table**
        st.markdown(f"""
        <div class="custom-table-container">
        <table class="custom-table">
            <tr><th>Field</th><th>Details</th></tr>
            <tr><td>✈️ From</td><td>{origin_city}</td></tr>
            <tr><td>🏁 To</td><td>{destination_city}</td></tr>
            <tr><td>📅 Departure</td><td>{departure_date}</td></tr>
            <tr><td>🔄 Return</td><td>{return_date}</td></tr>
            <tr><td>👨‍👩‍👧 Adults</td><td>{adults}</td></tr>
            <tr><td>👶 Children</td><td>{children_str}</td></tr>
            <tr><td>🚀 Direct Flight</td><td>{"Yes" if direct_flight_requested else "No"}</td></tr>
        </table>
        </div>
        """, unsafe_allow_html=True)

        # ✅ Search for Flights
        response = amadeus.shopping.flight_offers_search.get(
            originLocationCode=get_iata_code(origin_city),
            destinationLocationCode=get_iata_code(destination_city),
            departureDate=departure_date,
            adults=adults,
            currencyCode="GBP",
            max=10
        )
        flights = response.data

        if not flights:
            st.error("❌ No flights found. Try different dates or locations.")
        else:
            flight_results = []
            for flight in flights:
                price_per_adult = float(flight.get("price", {}).get("total", "0.00"))
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
                    "From": origin_city,
                    "To": destination_city,
                    "Departure": departure_date,
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

    except json.JSONDecodeError as e:
        st.error(f"🚨 Error: AI response is not valid JSON. {e}")
