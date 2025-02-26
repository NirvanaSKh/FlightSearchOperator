import streamlit as st
import datetime
import pandas as pd
from amadeus import Client, ResponseError
import openai
import os
import json  # ✅ Use JSON for safer parsing

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
st.markdown("💬 **Ask me to find flights for you!** (e.g., 'Find me a flight from New York to Singapore on March 10 for 1 adult')")

# ✅ User Input
user_input = st.text_input("You:", placeholder="Type your flight request here and press Enter...")

if user_input:
    # ✅ Step 4: Extract Flight Details Using OpenAI GPT
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Extract flight details from the user's input. Return output in valid JSON format with keys: origin, destination, departure_date, return_date (null if one-way), adults, children (list of ages)."},
            {"role": "user", "content": user_input}
        ]
    )

    flight_info = response.choices[0].message.content  # ✅ Corrected OpenAI API usage

    st.write("🔍 **AI Extracted Flight Details:**")
    st.code(flight_info, language="json")  # ✅ Shows JSON output for debugging

    try:
        # ✅ Parse AI response using `json.loads()` instead of `eval()`
        flight_details = json.loads(flight_info)

        origin = flight_details.get("origin", "LHR")  # Default: London Heathrow
        destination = flight_details.get("destination", "CDG")  # Default: Paris
        departure_date = flight_details.get("departure_date", "2025-06-10")
        return_date = flight_details.get("return_date", None)  # ✅ Converts `null` to `None`
        adults = flight_details.get("adults", 1)
        children_ages = flight_details.get("children", [])

        # ✅ Call Flight Search Function
        def search_flights():
            try:
                params = {
                    "originLocationCode": origin,
                    "destinationLocationCode": destination,
                    "departureDate": departure_date,
                    "adults": adults,
                    "children": len(children_ages),
                    "infants": sum(1 for age in children_ages if age < 2),
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

                    total_price = price * (adults + len(children_ages))

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

