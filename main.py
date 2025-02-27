
# import paho.mqtt.client as mqtt

# # MQTT Broker details (same as in your Swift app)
# BROKER_IP = "194.57.103.203"
# PORT = 1883
# TOPIC = "vehicule/speed"

# # Callback when connected to the broker
# def on_connect(client, userdata, flags, rc):
#     if rc == 0:
#         print("✅ Connected to MQTT Broker!")
#         client.subscribe(TOPIC)  # Subscribe to the topic
#     else:
#         print(f"❌ Failed to connect, return code {rc}")

# # Callback when a message is received
# def on_message(client, userdata, msg):
#     print(f"📡 Received: {msg.topic} → {msg.payload.decode()}")

# # Create MQTT client
# client = mqtt.Client()
# client.on_connect = on_connect
# client.on_message = on_message

# # Connect to MQTT broker
# print(f"🔗 Connecting to MQTT broker at {BROKER_IP}:{PORT}...")
# client.connect(BROKER_IP, PORT, 60)

# # Keep listening
# client.loop_forever()





# 🔗 Connecting to MQTT broker at 194.57.103.203:1883...
# ✅ Connected to MQTT Broker!
# 📡 Received: vehicule/speed → {"latitude":49.243932820584689,"speed":"1.88 Mbps","timestamp":1740652777.0512969,"longitude":4.0625435695314582}
# 📡 Received: vehicule/speed → {"speed":"1.59 Mbps","longitude":4.0625435695314582,"timestamp":1740652778.0780101,"latitude":49.243932820584689}
# 📡 Received: vehicule/speed → {"speed":"1.84 Mbps","latitude":49.243932820584689,"longitude":4.0625435695314582,"timestamp":1740652779.0535998}
# 📡 Received: vehicule/speed → {"timestamp":1740652780.0359678,"latitude":49.243923477557423,"speed":"2.14 Mbps","longitude":4.0626351469028625}
# 📡 Received: vehicule/speed → {"timestamp":1740652781.0534759,"latitude":49.243921897480654,"longitude":4.0626432626501323,"speed":"1.88 Mbps"}
# 📡 Received: vehicule/speed → {"timestamp":1740652782.0616369,"latitude":49.243921897480654,"speed":"1.75 Mbps","longitude":4.0626432626501323}
# 📡 Received: vehicule/speed → {"latitude":49.243929634856798,"timestamp":1740652783.0552011,"longitude":4.062748775197643,"speed":"1.86 Mbps"}
# 📡 Received: vehicule/speed → {"speed":"2.17 Mbps","longitude":4.0625800945715467,"timestamp":1740652784.03635,"latitude":49.243902287479919}
# 📡 Received: vehicule/speed → {"longitude":4.0625800945715467,"latitude":49.243902287479919,"timestamp":1740652785.086421,"speed":"1.60 Mbps"}
# 📡 Received: vehicule/speed → {"speed":"1.53 Mbps","longitude":4.062585945399519,"timestamp":1740652786.085264,"latitude":49.243903241486485}
# 📡 Received: vehicule/speed → {"latitude":49.243924364061741,"longitude":4.0626635263322761,"timestamp":1740652787.0535531,"speed":"1.88 Mbps"}
# 📡 Received: vehicule/speed → {"latitude":49.243927787097682,"timestamp":1740652788.1365781,"longitude":4.0627228231492616,"speed":"1.25 Mbps"}
# 📡 Received: vehicule/speed → {"speed":"2.36 Mbps","longitude":4.0627238432917148,"timestamp":1740652789.023308,"latitude":49.243954603195476}




# import paho.mqtt.client as mqtt
# import json
# import time
# import csv
# import os
# from datetime import datetime

# # MQTT Broker details
# BROKER_IP = "194.57.103.203"
# PORT = 1883
# TOPIC = "vehicule/speed"

# # Variables to store data and track timing
# metrics = []
# last_received_time = None
# SAVE_DELAY = 3  # seconds to wait before saving

# # Ensure output directory exists
# os.makedirs("records", exist_ok=True)

# def save_to_csv():
#     global metrics
#     if metrics:
#         timestamp_now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
#         filename = f"records/enregistrement_{timestamp_now}.csv"
#         with open(filename, mode='w', newline='') as file:
#             writer = csv.writer(file)
#             writer.writerow(["latitude", "longitude", "speed", "timestamp", "datetime"])
#             for metric in metrics:
#                 datetime_str = datetime.fromtimestamp(metric["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
#                 writer.writerow([metric["latitude"], metric["longitude"], metric["speed"], metric["timestamp"], datetime_str])
#         print(f"📁 Data saved to {filename}")
#         metrics = []  # Reset the storage

# # Callback when connected to the broker
# def on_connect(client, userdata, flags, rc):
#     if rc == 0:
#         print("✅ Connected to MQTT Broker!")
#         client.subscribe(TOPIC)
#     else:
#         print(f"❌ Failed to connect, return code {rc}")

# # Callback when a message is received
# def on_message(client, userdata, msg):
#     global last_received_time, metrics
#     try:
#         data = json.loads(msg.payload.decode())
#         metrics.append(data)
#         last_received_time = time.time()
#         print(f"📡 Received: {data}")
#     except json.JSONDecodeError:
#         print("❌ Failed to decode message")

# # Create MQTT client
# client = mqtt.Client()
# client.on_connect = on_connect
# client.on_message = on_message

# # Connect to MQTT broker
# print(f"🔗 Connecting to MQTT broker at {BROKER_IP}:{PORT}...")
# client.connect(BROKER_IP, PORT, 60)

# # Start the loop in a non-blocking way
# client.loop_start()

# while True:
#     time.sleep(1)  # Reduce CPU usage
#     if last_received_time and (time.time() - last_received_time >= SAVE_DELAY):
#         print("⏳ No new messages for 3 seconds. Saving data...")
#         save_to_csv()
#         last_received_time = None



# main.py

import streamlit as st
import paho.mqtt.client as mqtt
import threading
import time
import os
import csv
from datetime import datetime
from collections import deque
import pandas as pd
import altair as alt

# For interactive maps with labeled markers:
import folium
from streamlit_folium import st_folium

# --------------------------------------------------------------------
# 1) Set Page Config at the VERY TOP
# --------------------------------------------------------------------
st.set_page_config(page_title="MQTT Dashboard", layout="wide")

# Custom CSS to widen the sidebar
st.markdown(
    """
    <style>
    /* Increase the sidebar width */
    [data-testid="stSidebar"] {
        min-width: 500px;
        max-width: 1000px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------
BROKER_IP = "194.57.103.203"  # Your broker IP
PORT = 1883
TOPIC = "vehicule/speed"
SAVE_DELAY = 3  # seconds of inactivity before auto-save

# Path to the folder where we store CSV files
RECORDS_DIR = "/Users/yanis/Desktop/app-fouchal-python/records"
os.makedirs(RECORDS_DIR, exist_ok=True)

# --------------------------------------------------------------------
# MQTT Manager Class
# --------------------------------------------------------------------
class MQTTManager:
    """
    Manages an MQTT client in a background thread. Auto-saves to CSV on inactivity.
    Stores logs, so we can display them in the UI if needed.
    """

    def __init__(self, broker_ip, port, topic):
        self.broker_ip = broker_ip
        self.port = port
        self.topic = topic

        self.client = None
        self.connected = False
        self.stop_flag = False
        self.thread = None

        # Incoming messages (to be saved to CSV):
        self.metrics = deque()
        self.last_received_time = None

        # Optional logs if you want to show them on UI
        self.logs = deque(maxlen=500)  # store up to 500 lines of logs

    def _log(self, message):
        """Utility to store logs in a deque and also print to terminal."""
        self.logs.append(message)
        print(message)

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            self._log("✅ Connected to MQTT Broker!")
            client.subscribe(self.topic)
        else:
            self._log(f"❌ Failed to connect, return code {rc}")

    def on_message(self, client, userdata, msg):
        """
        Called whenever a message arrives on the subscribed topic.
        """
        try:
            import json
            data = json.loads(msg.payload.decode())
            self.metrics.append(data)
            self.last_received_time = time.time()

            self._log(f"📡 Received data: {data}")
        except json.JSONDecodeError:
            self._log("❌ Failed to decode JSON message")

    def connect(self):
        """Create and connect MQTT client."""
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self._log(f"🔗 Connecting to MQTT broker at {self.broker_ip}:{self.port}...")
        self.client.connect(self.broker_ip, self.port, keepalive=60)

    def loop_forever(self):
        """
        Background thread entry point.
        Processes MQTT events continuously, checks inactivity to save data.
        """
        while not self.stop_flag:
            self.client.loop(timeout=1.0)

            # If we have not received messages for SAVE_DELAY seconds, save to CSV:
            if (
                self.last_received_time is not None
                and (time.time() - self.last_received_time >= SAVE_DELAY)
            ):
                self._log("⏳ No new messages for 3 seconds. Saving data...")
                self.save_to_csv()
                self.last_received_time = None

        if self.connected:
            self.client.disconnect()
            self.connected = False
        self._log("🛑 MQTT thread stopped.")

    def start(self):
        """Start the background thread if not already running."""
        if self.thread is not None and self.thread.is_alive():
            self._log("MQTTManager: Thread already running.")
            return

        self.stop_flag = False
        self.connect()
        self.thread = threading.Thread(target=self.loop_forever, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the background thread and disconnect."""
        self.stop_flag = True
        if self.thread is not None:
            self.thread.join()
        self.thread = None
        self._log("MQTTManager: stopped.")

    def save_to_csv(self):
        """Save collected data to a new CSV file in RECORDS_DIR."""
        if not self.metrics:
            return

        timestamp_now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"enregistrement_{timestamp_now}.csv"
        filepath = os.path.join(RECORDS_DIR, filename)

        with open(filepath, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["latitude", "longitude", "speed", "timestamp", "datetime"])

            while self.metrics:
                data = self.metrics.popleft()
                # Convert numeric timestamp to human-readable
                dt_str = datetime.fromtimestamp(data["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([
                    data.get("latitude"),
                    data.get("longitude"),
                    data.get("speed"),
                    data.get("timestamp"),
                    dt_str
                ])

        self._log(f"📁 Data saved to {filepath}")

# --------------------------------------------------------------------
# 2) Caching the Manager
# --------------------------------------------------------------------
@st.cache_resource
def get_mqtt_manager():
    """
    Returns a single instance of MQTTManager (cached across reruns).
    Automatically starts the MQTT loop on creation.
    """
    manager = MQTTManager(BROKER_IP, PORT, TOPIC)
    manager.start()  # <-- Start automatically
    return manager

manager = get_mqtt_manager()  # Trigger creation and start

# --------------------------------------------------------------------
# 3) Utilities for Loading CSV Data
# --------------------------------------------------------------------
def load_all_csvs(records_path: str) -> pd.DataFrame:
    """
    Loads all CSV files in records_path and combines them into a single DataFrame.
    Returns an empty DataFrame if none found.
    """
    files = [f for f in os.listdir(records_path) if f.endswith(".csv")]
    if not files:
        return pd.DataFrame(columns=["latitude", "longitude", "speed", "timestamp", "datetime"])

    df_list = []
    for fname in files:
        path = os.path.join(records_path, fname)
        df_temp = pd.read_csv(path)
        df_temp["source_file"] = fname  # so we know which file it came from
        df_list.append(df_temp)

    return pd.concat(df_list, ignore_index=True)

def load_single_csv(filepath: str) -> pd.DataFrame:
    """
    Load a single CSV into a pandas DataFrame.
    """
    return pd.read_csv(filepath)

# --------------------------------------------------------------------
# 4) Folium Map with Markers (labeled by speed)
# --------------------------------------------------------------------
def create_folium_map(df: pd.DataFrame, map_center=None, zoom_start=13) -> folium.Map:
    """
    Create a Folium map for all points in df.
    Each marker will have a tooltip = speed/debit.
    If map_center is not given, we center on the mean lat/lon or a fallback.
    """
    if df.empty:
        # Default location: e.g. Paris
        m = folium.Map(location=[48.8566, 2.3522], zoom_start=5)
        return m

    if not map_center:
        center_lat = df["latitude"].mean()
        center_lon = df["longitude"].mean()
        map_center = [center_lat, center_lon]

    m = folium.Map(location=map_center, zoom_start=zoom_start)

    for _, row in df.iterrows():
        lat = row["latitude"]
        lon = row["longitude"]
        speed = row["speed"]  # e.g. "1.54 Mbps"
        tooltip = f"Débit: {speed}"
        folium.Marker(location=[lat, lon], tooltip=tooltip).add_to(m)

    return m

# --------------------------------------------------------------------
# 5) Parsing "speed" to numeric for plots
# --------------------------------------------------------------------
def parse_speed_mbps(speed_str: str) -> float:
    """
    Convert a string like "1.54 Mbps" -> 1.54 as float.
    If parsing fails, return None.
    """
    if not isinstance(speed_str, str):
        return None
    # Simple approach: remove " Mbps" if present, then convert to float
    try:
        return float(speed_str.replace(" Mbps", "").strip())
    except:
        return None

# --------------------------------------------------------------------
# 6) Streamlit App
# --------------------------------------------------------------------
# ========== SIDEBAR ==========
with st.sidebar:
    st.header("Explorer les fichiers")

    # List CSV files in the RECORDS_DIR
    csv_files = sorted(
        [f for f in os.listdir(RECORDS_DIR) if f.endswith(".csv")],
        reverse=True
    )

    if csv_files:
        selected_csv = st.selectbox("Sélectionner un CSV", csv_files)
        if selected_csv:
            path_csv = os.path.join(RECORDS_DIR, selected_csv)
            df_csv = load_single_csv(path_csv)

            st.subheader(f"Contenu du fichier: {selected_csv}")
            st.dataframe(df_csv.head())

            # ----- PLOTS -----
            if not df_csv.empty:
                # Parse "speed" into a numeric column
                df_csv["speed_mbps"] = df_csv["speed"].apply(parse_speed_mbps)
                # Convert timestamp to a real datetime for plotting
                df_csv["time_dt"] = pd.to_datetime(df_csv["timestamp"], unit="s")

                # 1) Histogram of speed
                hist_chart = (
                    alt.Chart(df_csv)
                    .mark_bar()
                    .encode(
                        x=alt.X("speed_mbps:Q", bin=alt.Bin(maxbins=20), title="Speed (Mbps)"),
                        y="count()",
                    )
                    .properties(title="Histogram of Speed (Mbps)")
                )
                st.altair_chart(hist_chart, use_container_width=True)

                # 2) Speed vs. Time (line chart)
                # We only plot if there's more than one row
                if len(df_csv) > 1:
                    line_chart = (
                        alt.Chart(df_csv)
                        .mark_line(point=True)
                        .encode(
                            x=alt.X("time_dt:T", title="Time"),
                            y=alt.Y("speed_mbps:Q", title="Speed (Mbps)"),
                        )
                        .properties(title="Speed vs. Time")
                    )
                    st.altair_chart(line_chart, use_container_width=True)

            # ----- MAP for this file -----   
            st.write("**Carte des points pour ce fichier**")
            map_for_file = create_folium_map(df_csv)
            st_folium(map_for_file, use_container_width=True, height=500)

    else:
        st.write("Aucun fichier CSV trouvé.")

    # st.write("---")
    # # Optionally, a 'Stop' button for MQTT if you want:
    # if st.button("Arrêter le MQTT"):
    #     manager.stop()
    #     st.warning("Le client MQTT est arrêté.")

# ========== MAIN PAGE CONTENT ==========
st.title("Tableau de Bord - Données Globales")

# Load and combine all CSV data
all_data_df = load_all_csvs(RECORDS_DIR)

if all_data_df.empty:
    st.write("Aucune donnée disponible (aucun CSV).")
else:
    st.write("**Carte globale** avec tous les points de tous les fichiers CSV :")

    # Create one big folium map
    combined_map = create_folium_map(all_data_df, zoom_start=12)
    st_folium(combined_map, width=800, height=500)

    st.write("**Aperçu de toutes les données combinées** :")
    st.dataframe(all_data_df.head(50))

st.write("---")
st.write("Les données sont automatiquement sauvegardées toutes les 3 secondes d'inactivité MQTT.")
