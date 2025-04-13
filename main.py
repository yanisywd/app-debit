
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
import numpy as np
from sklearn.cluster import DBSCAN, KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.spatial.distance import cdist
import colorsys
from sklearn.ensemble import RandomForestRegressor, IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score

import folium
from folium.plugins import MarkerCluster, HeatMap
from streamlit_folium import folium_static


st.set_page_config(page_title="MQTT Dashboard", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] {
        min-width: 500px;
        max-width: 1000px;
    }
    
    .folium-map {
        width: 100%;
        height: 800px !important;
    }
    
    .main .block-container {
        max-width: 1400px;
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)


BROKER_IP = "194.57.103.203"
PORT = 1883
TOPIC = "vehicule/speed"
SAVE_DELAY = 3

RECORDS_DIR = "/Users/yanis/Desktop/app-fouchal-python/records"
os.makedirs(RECORDS_DIR, exist_ok=True)

if 'current_page' not in st.session_state:
    st.session_state.current_page = "Tableau de Bord"

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

        self.metrics = deque()
        self.last_received_time = None

        self.logs = deque(maxlen=500)

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
            print(f"📊 DONNÉES EN TEMPS RÉEL: Latitude={data.get('latitude')}, Longitude={data.get('longitude')}, Vitesse={data.get('speed')}")


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
                dt_str = datetime.fromtimestamp(data["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow([
                    data.get("latitude"),
                    data.get("longitude"),
                    data.get("speed"),
                    data.get("timestamp"),
                    dt_str
                ])

        self._log(f"📁 Data saved to {filepath}")

@st.cache_resource
def get_mqtt_manager():
    """
    Returns a single instance of MQTTManager (cached across reruns).
    Automatically starts the MQTT loop on creation.
    """
    manager = MQTTManager(BROKER_IP, PORT, TOPIC)
    manager.start()
    return manager

manager = get_mqtt_manager()

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
        df_temp["source_file"] = fname
        df_list.append(df_temp)

    return pd.concat(df_list, ignore_index=True)

def load_single_csv(filepath: str) -> pd.DataFrame:
    """
    Load a single CSV into a pandas DataFrame.
    """
    return pd.read_csv(filepath)

def parse_speed_mbps(speed_str: str) -> float:
    """
    Convert a string like "1.54 Mbps" -> 1.54 as float.
    If parsing fails, return None.
    """
    if not isinstance(speed_str, str):
        return None
    try:
        return float(speed_str.replace(" Mbps", "").strip())
    except:
        return None

def get_color(speed_value, min_speed, max_speed):
    """
    Returns a color from green (high speed) to red (low speed)
    """
    if max_speed == min_speed:
        ratio = 0.5
    else:
        ratio = (speed_value - min_speed) / (max_speed - min_speed)
    
    r = int(255 * (1 - ratio))
    g = int(255 * ratio)
    b = 0
    
    return f'#{r:02x}{g:02x}{b:02x}'

def create_folium_map(df: pd.DataFrame, map_center=None, zoom_start=13) -> folium.Map:
    """
    Version sans clustering qui affiche tous les points directement sur la carte.
    Chaque marqueur est coloré selon la vitesse.
    """
    if df.empty:
        m = folium.Map(location=[48.8566, 2.3522], zoom_start=5)
        return m

    df = df.copy()
    df["speed_value"] = df["speed"].apply(parse_speed_mbps)
    min_speed = df["speed_value"].min()
    max_speed = df["speed_value"].max()

    if not map_center:
        center_lat = df["latitude"].mean()
        center_lon = df["longitude"].mean()
        map_center = [center_lat, center_lon]

    m = folium.Map(location=map_center, zoom_start=zoom_start)
    
    for _, row in df.iterrows():
        lat = row["latitude"]
        lon = row["longitude"]
        speed = row["speed"]
        speed_value = row["speed_value"]
        tooltip = f"Débit: {speed}, Heure: {row.get('datetime', '')}"
        
        folium.CircleMarker(
            location=[lat, lon],
            radius=5,
            fill=True,
            fill_color=get_color(speed_value, min_speed, max_speed),
            color=get_color(speed_value, min_speed, max_speed),
            fill_opacity=0.7,
            popup=tooltip,
            tooltip=f"Débit: {speed}"
        ).add_to(m)

    legend_html = '''
    <div style="position: fixed; 
         bottom: 50px; right: 50px; width: 300px; height: 250px; 
         border:2px solid grey; z-index:9999; font-size:12px;
         background-color:white; padding:10px; border-radius:5px">
         <b>Débit (Mbps)</b><br>
         <i style="background:#00ff00; width:15px; height:15px; display:inline-block"></i> {:.2f} (Max)<br>
         <i style="background:#ff0000; width:15px; height:15px; display:inline-block"></i> {:.2f} (Min)
    </div>
    '''.format(max_speed, min_speed)

    m.get_root().html.add_child(folium.Element(legend_html))
    
    return m

def generate_cluster_colors(n_clusters):
    """Generate visually distinct colors for clusters."""
    colors = []
    for i in range(n_clusters):
        h = i / n_clusters
        s = 0.8
        v = 0.9
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        color = f'#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'
        colors.append(color)
    return colors

def perform_kmeans_clustering(df, n_clusters=5):
    """
    Optimized K-means clustering implementation.
    
    Parameters:
    - df: DataFrame with latitude, longitude, and speed_mbps columns
    - n_clusters: Number of clusters to find
    
    Returns:
    - df_clustered: DataFrame with added cluster labels
    - kmeans: Fitted KMeans model
    """
    X = df[['latitude', 'longitude', 'speed_mbps']].values
    
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=3, max_iter=300)
    
    df_clustered = df.copy()
    
    df_clustered['cluster'] = kmeans.fit_predict(X_scaled)
    
    return df_clustered, kmeans

def detect_speed_anomalies(df, contamination=0.05):
    """
    Detect anomalies in speed data using Isolation Forest
    
    Parameters:
    - df: DataFrame with latitude, longitude, and speed_mbps columns
    - contamination: Expected proportion of anomalies (0.0-0.5)
    
    Returns:
    - df_with_anomalies: DataFrame with anomaly flags and scores
    """
    
    X = df[['latitude', 'longitude', 'speed_mbps']].values
    
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    model = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_estimators=100
    )
    
    df_result = df.copy()
    df_result['anomaly'] = model.fit_predict(X_scaled)
    
    df_result['is_anomaly'] = df_result['anomaly'] == -1
    
    df_result['anomaly_score'] = model.decision_function(X_scaled) * -1
    
    return df_result

def train_speed_prediction_model(df):
    """
    Train a model to predict network speed based on location
    
    Parameters:
    - df: DataFrame with latitude, longitude, and speed_mbps columns
    
    Returns:
    - trained_model: Trained RandomForest model
    - scaler: Fitted StandardScaler for preprocessing
    """
    
    X = df[['latitude', 'longitude']].values
    y = df['speed_mbps'].values
    
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    model = RandomForestRegressor(
        n_estimators=100,
        max_depth=10,
        random_state=42
    )
    model.fit(X_scaled, y)
    
    return model, scaler

def predict_speed_for_grid(model, scaler, df, grid_size=20):
    """
    Create a grid of predictions around the data points
    
    Parameters:
    - model: Trained model
    - scaler: Fitted scaler
    - df: DataFrame with latitude and longitude columns
    - grid_size: Number of points in each dimension
    
    Returns:
    - grid_df: DataFrame with grid points and predicted speeds
    """
    lat_min, lat_max = df['latitude'].min(), df['latitude'].max()
    lon_min, lon_max = df['longitude'].min(), df['longitude'].max()
    
    lat_buffer = (lat_max - lat_min) * 0.1
    lon_buffer = (lon_max - lon_min) * 0.1
    
    lat_min -= lat_buffer
    lat_max += lat_buffer
    lon_min -= lon_buffer
    lon_max += lon_buffer
    
    lat_grid = np.linspace(lat_min, lat_max, grid_size)
    lon_grid = np.linspace(lon_min, lon_max, grid_size)
    
    grid_points = []
    for lat in lat_grid:
        for lon in lon_grid:
            grid_points.append([lat, lon])
    
    grid_points = np.array(grid_points)
    
    grid_scaled = scaler.transform(grid_points)
    
    predictions = model.predict(grid_scaled)
    
    grid_df = pd.DataFrame({
        'latitude': grid_points[:, 0],
        'longitude': grid_points[:, 1],
        'predicted_speed_mbps': predictions
    })
    
    return grid_df

def analyze_time_patterns(df):
    """
    Analyze time patterns in the data
    
    Parameters:
    - df: DataFrame with datetime and speed_mbps columns
    
    Returns:
    - time_analysis: Dictionary with time analysis results
    """
    if 'datetime' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['datetime']):
        df = df.copy()
        df['datetime'] = pd.to_datetime(df['datetime'])
    
    df['hour'] = df['datetime'].dt.hour
    df['minute'] = df['datetime'].dt.minute
    df['day_of_week'] = df['datetime'].dt.dayofweek
    
    hourly_avg = df.groupby('hour')['speed_mbps'].mean().reset_index()
    
    dow_avg = df.groupby('day_of_week')['speed_mbps'].mean().reset_index()
    
    peak_hour = hourly_avg.loc[hourly_avg['speed_mbps'].idxmax()]
    low_hour = hourly_avg.loc[hourly_avg['speed_mbps'].idxmin()]
    
    df = df.sort_values('datetime')
    
    time_analysis = {
        'hourly_avg': hourly_avg,
        'day_of_week_avg': dow_avg,
        'peak_hour': int(peak_hour['hour']),
        'peak_speed': float(peak_hour['speed_mbps']),
        'low_hour': int(low_hour['hour']),
        'low_speed': float(low_hour['speed_mbps'])
    }
    
    return time_analysis

def create_prediction_map(df, grid_df, anomalies_df=None, only_anomalies=False):
    """
    Create a folium map showing actual data points and predicted speed grid
    
    Parameters:
    - df: DataFrame with original data points
    - grid_df: DataFrame with grid points and predictions
    - anomalies_df: Optional DataFrame with anomaly flags
    - only_anomalies: If True, only show anomaly points on the map
    
    Returns:
    - m: Folium map object
    """
    center_lat = df['latitude'].mean()
    center_lon = df['longitude'].mean()
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=15)
    
    min_speed = grid_df['predicted_speed_mbps'].min()
    max_speed = grid_df['predicted_speed_mbps'].max()
    
    for _, row in grid_df.iterrows():
        ratio = (row['predicted_speed_mbps'] - min_speed) / (max_speed - min_speed)
        r = int(255 * (1 - ratio))
        g = int(255 * ratio)
        b = 0
        color = f'#{r:02x}{g:02x}{b:02x}'
        
        folium.CircleMarker(
            location=[row['latitude'], row['longitude']],
            radius=3,
            fill=True,
            fill_color=color,
            color=color,
            fill_opacity=0.3,
            opacity=0.3,
            tooltip=f"Predicted: {row['predicted_speed_mbps']:.2f} Mbps"
        ).add_to(m)
    
    for _, row in df.iterrows():
        is_anomaly = False
        
        if anomalies_df is not None:
            anomaly_row = anomalies_df.loc[anomalies_df.index == row.name]
            if not anomaly_row.empty and anomaly_row['is_anomaly'].iloc[0]:
                is_anomaly = True
        
        if is_anomaly:
            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=7,
                fill=True,
                fill_color='purple',
                color='black',
                fill_opacity=0.9,
                popup=f"Débit: {row['speed']}<br>ANOMALIE"
            ).add_to(m)
        elif not only_anomalies:
            speed_value = row['speed_mbps']
            ratio = (speed_value - min_speed) / (max_speed - min_speed)
            r = int(255 * (1 - ratio))
            g = int(255 * ratio)
            b = 0
            color = f'#{r:02x}{g:02x}{b:02x}'
            
            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=5,
                fill=True,
                fill_color=color,
                color='black',
                fill_opacity=0.7,
                popup=f"Débit: {row['speed']}"
            ).add_to(m)
    
    legend_html = '''
    <div style="position: fixed; 
         bottom: 50px; right: 50px; width: 200px; 
         border:2px solid grey; z-index:9999; font-size:12px;
         background-color:white; padding:10px; border-radius:5px">
         <b>Légende</b><br>
    '''
    
    if not only_anomalies:
        legend_html += '''
        <i style="background:#00ff00; width:15px; height:15px; display:inline-block"></i> Débit élevé<br>
        <i style="background:#ff0000; width:15px; height:15px; display:inline-block"></i> Débit faible<br>
        '''
    
    legend_html += '''
        <i style="background:purple; width:15px; height:15px; display:inline-block"></i> Anomalie<br>
        <i style="opacity:0.3; background:#00ff00; width:15px; height:15px; display:inline-block"></i> Prédiction
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))
    
    return m

def find_optimal_k(df, max_k=10, max_time_seconds=20, sample_size=1000):
    """
    Find optimal number of clusters for K-means using silhouette score and elbow method.
    Optimized for performance with sampling and time limits.
    
    Parameters:
    - df: DataFrame with clustering features
    - max_k: Maximum number of clusters to try
    - max_time_seconds: Maximum time to spend on optimization
    - sample_size: Maximum number of points to use for optimization
    
    Returns:
    - best_k: Optimal number of clusters
    - silhouette_scores, inertia_values, k_values: Metric data for plotting
    """
    import time
    start_time = time.time()
    
    if len(df) > sample_size:
        df_sample = df.sample(sample_size, random_state=42)
    else:
        df_sample = df
    
    X = df_sample[['latitude', 'longitude', 'speed_mbps']].values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    silhouette_scores = []
    inertia_values = []
    k_values = range(2, min(max_k + 1, len(df_sample) // 10))
    
    if len(k_values) == 0:
        return 2, None, None, None
    
    for k in k_values:
        if (time.time() - start_time) > max_time_seconds:
            print(f"Time limit of {max_time_seconds}s exceeded after trying k={k-1}. Stopping early.")
            break
            
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=3)
        labels = kmeans.fit_predict(X_scaled)
        
        try:
            score = silhouette_score(X_scaled, labels)
            silhouette_scores.append(score)
        except:
            silhouette_scores.append(-1)
            
        inertia_values.append(kmeans.inertia_)
    
    if not silhouette_scores:
        return 2, None, None, None
    
    best_k_silhouette = list(k_values)[:len(silhouette_scores)][np.argmax(silhouette_scores)]
    
    if len(inertia_values) > 2:
        second_derivative = np.diff(np.diff(inertia_values))
        elbow_point = np.argmax(second_derivative) if len(second_derivative) > 0 else 0
        best_k_elbow = list(k_values)[:len(inertia_values)][min(elbow_point + 2, len(inertia_values) - 1)]
    else:
        best_k_elbow = best_k_silhouette
    
    if abs(best_k_silhouette - best_k_elbow) > 2:
        best_k = max(2, round((best_k_silhouette + best_k_elbow) / 2))
    else:
        best_k = best_k_silhouette
    
    return best_k, silhouette_scores, inertia_values, list(k_values)[:len(silhouette_scores)]

def create_cluster_map(df_clustered, cluster_col='cluster', zoom_start=14, max_points_per_cluster=500):
    """
    Improved version of the cluster map function with:
    - Fixed color assignment to prevent inconsistent colors for the same cluster
    - Performance optimizations for large datasets
    - Better handling of cluster boundaries
    
    Parameters:
    - df_clustered: DataFrame with cluster labels
    - cluster_col: Name of the column containing cluster labels
    - zoom_start: Initial zoom level
    - max_points_per_cluster: Max points to show per cluster (for performance)
    
    Returns:
    - m: Folium map object
    """
    unique_clusters = sorted(df_clustered[cluster_col].unique())
    n_clusters = len([c for c in unique_clusters if c >= 0])
    
    base_colors = [
        '#e6194B', '#3cb44b', '#ffe119', '#4363d8', '#f58231', 
        '#911eb4', '#42d4f4', '#f032e6', '#bfef45', '#fabed4', 
        '#469990', '#dcbeff', '#9A6324', '#800000', '#aaffc3'
    ]
    
    while len(base_colors) < n_clusters:
        base_colors = base_colors + base_colors
    
    cluster_color_map = {}
    
    cluster_ids = sorted([c for c in unique_clusters if c >= 0])
    for i, cluster_id in enumerate(cluster_ids):
        cluster_color_map[cluster_id] = base_colors[i % len(base_colors)]
    
    if -1 in unique_clusters:
        cluster_color_map[-1] = '#000000'
    
    center_lat = df_clustered['latitude'].mean()
    center_lon = df_clustered['longitude'].mean()
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start)
    
    cluster_groups = {}
    for cluster in unique_clusters:
        cluster_groups[cluster] = folium.FeatureGroup(name=f"Cluster {cluster}")
    
    for cluster in unique_clusters:
        cluster_data = df_clustered[df_clustered[cluster_col] == cluster].copy()
        color = cluster_color_map.get(cluster, '#000000')
        
        if len(cluster_data) > max_points_per_cluster:
            if cluster == -1:
                cluster_data = cluster_data.sample(min(max_points_per_cluster // 2, len(cluster_data)), random_state=42)
            else:
                cluster_data = cluster_data.sample(max_points_per_cluster, random_state=42)
        
        radius = 5 if cluster != -1 else 2
        
        for _, row in cluster_data.iterrows():
            tooltip = f"Débit: {row['speed']} ({row['speed_mbps']:.2f} Mbps)<br>" + \
                    f"Cluster: {cluster if cluster != -1 else 'Bruit'}<br>" + \
                    f"Date: {row.get('datetime', '')}"
            
            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=radius,
                fill=True,
                fill_color=color,
                color=color,
                fill_opacity=0.7,
                popup=tooltip
            ).add_to(cluster_groups[cluster])
    
    from scipy.spatial import ConvexHull
    
    for cluster in [c for c in unique_clusters if c >= 0]:
        cluster_data = df_clustered[df_clustered[cluster_col] == cluster]
        
        if len(cluster_data) < 3:
            continue
            
        cluster_center_lat = cluster_data['latitude'].mean()
        cluster_center_lon = cluster_data['longitude'].mean()
        
        avg_speed = cluster_data['speed_mbps'].mean()
        
        try:
            points = cluster_data[['latitude', 'longitude']].values
            hull = ConvexHull(points)
            hull_points = points[hull.vertices]
            
            hull_points = [[p[0], p[1]] for p in hull_points]
            
            color = cluster_color_map[cluster]
            folium.Polygon(
                locations=hull_points,
                color=color,
                weight=1.5,
                fill=True,
                fill_color=color,
                fill_opacity=0.1,
                dash_array='5, 5',
                popup=f"Cluster {cluster}<br>Points: {len(cluster_data)}<br>Débit moyen: {avg_speed:.2f} Mbps"
            ).add_to(cluster_groups[cluster])
        except Exception as e:
            pass
        
        folium.map.Marker(
            [cluster_center_lat, cluster_center_lon],
            icon=folium.DivIcon(
                icon_size=(50, 50),
                icon_anchor=(25, 25),
                html=f'<div style="font-size: 16pt; color: white; text-align: center; line-height: 50px; background-color: {color}; width: 50px; height: 50px; border-radius: 25px; font-weight: bold;">{cluster}</div>'
            )
        ).add_to(cluster_groups[cluster])
        
        popup_html = f"""
        <div style="font-family: Arial; width: 200px;">
            <h3 style="color: {color};">Cluster {cluster}</h3>
            <table style="width: 100%;">
                <tr><td><b>Points:</b></td><td>{len(cluster_data)}</td></tr>
                <tr><td><b>Débit moyen:</b></td><td>{avg_speed:.2f} Mbps</td></tr>
                <tr><td><b>Débit min:</b></td><td>{cluster_data['speed_mbps'].min():.2f} Mbps</td></tr>
                <tr><td><b>Débit max:</b></td><td>{cluster_data['speed_mbps'].max():.2f} Mbps</td></tr>
                <tr><td><b>Écart-type:</b></td><td>{cluster_data['speed_mbps'].std():.2f} Mbps</td></tr>
            </table>
        </div>
        """
        
        folium.Marker(
            [cluster_center_lat, cluster_center_lon],
            popup=folium.Popup(folium.Html(popup_html, script=True), max_width=300),
            icon=folium.DivIcon(html='')
        ).add_to(cluster_groups[cluster])
    
    if 'kmeans_centers' in st.session_state and cluster_col == 'cluster':
        centers = st.session_state.kmeans_centers
        for i, center in enumerate(centers):
            if i in cluster_color_map:
                folium.Marker(
                    location=[center[0], center[1]],
                    icon=folium.Icon(color='black', icon='star'),
                    tooltip=f"Centre du cluster {i}<br>Débit moyen: {center[2]:.2f} Mbps"
                ).add_to(cluster_groups[i])
    
    legend_html = '''
    <div style="position: fixed; 
         top: 10px; right: 10px; width: 250px; 
         border:2px solid grey; z-index:9999; font-size:12px;
         background-color:white; padding:10px; border-radius:5px">
         <h4 style="margin-top:0;"><b>Légende des Clusters</b></h4>
         <table style="width: 100%;">
    '''
    
    for c in sorted([c for c in unique_clusters if c >= 0]):
        cluster_data = df_clustered[df_clustered[cluster_col] == c]
        avg_speed = cluster_data['speed_mbps'].mean()
        color = cluster_color_map.get(c, '#000000')
        legend_html += f'''
            <tr>
                <td>
                    <div style="background:{color}; width:15px; height:15px; display:inline-block; border-radius:50%;"></div>
                    <b>Cluster {c}</b>
                </td>
                <td>{len(cluster_data)} pts</td>
                <td>{avg_speed:.1f} Mbps</td>
            </tr>
        '''
    
    if -1 in unique_clusters:
        noise_data = df_clustered[df_clustered[cluster_col] == -1]
        if not noise_data.empty:
            avg_speed = noise_data['speed_mbps'].mean()
            legend_html += f'''
                <tr>
                    <td>
                        <div style="background:#000000; width:15px; height:15px; display:inline-block; border-radius:50%;"></div>
                        <b>Bruit</b>
                    </td>
                    <td>{len(noise_data)} pts</td>
                    <td>{avg_speed:.1f} Mbps</td>
                </tr>
            '''
    
    legend_html += '''
         </table>
         <div style="margin-top:5px; font-size:10px; color:#666;">
            Cliquez sur les numéros pour plus de détails
         </div>
    </div>
    '''
    
    m.get_root().html.add_child(folium.Element(legend_html))
    
    for group in cluster_groups.values():
        group.add_to(m)
    
    return m

def analyze_clusters(df_clustered, cluster_col='cluster'):
    """
    Generate statistics and analysis for each cluster.
    
    Parameters:
    - df_clustered: DataFrame with cluster labels
    
    Returns:
    - cluster_analysis: Dictionary with analysis results
    """
    unique_clusters = sorted(df_clustered[cluster_col].unique())
    cluster_analysis = {}
    
    cluster_analysis['total_points'] = len(df_clustered)
    cluster_analysis['n_clusters'] = len([c for c in unique_clusters if c >= 0])
    
    cluster_analysis['clusters'] = {}
    
    for c in unique_clusters:
        cluster_data = df_clustered[df_clustered[cluster_col] == c]
        
        if cluster_data.empty:
            continue
            
        cluster_info = {
            'size': len(cluster_data),
            'percentage': 100 * len(cluster_data) / len(df_clustered),
            'avg_speed': cluster_data['speed_mbps'].mean(),
            'min_speed': cluster_data['speed_mbps'].min(),
            'max_speed': cluster_data['speed_mbps'].max(),
            'std_speed': cluster_data['speed_mbps'].std(),
            'avg_lat': cluster_data['latitude'].mean(),
            'avg_lon': cluster_data['longitude'].mean(),
            'lat_range': (cluster_data['latitude'].max() - cluster_data['latitude'].min()) * 111000,
            'lon_range': (cluster_data['longitude'].max() - cluster_data['longitude'].min()) * 111000 * np.cos(np.radians(cluster_data['latitude'].mean()))
        }
        
        area_sqkm = (cluster_info['lat_range'] / 1000) * (cluster_info['lon_range'] / 1000)
        cluster_info['density'] = cluster_info['size'] / max(area_sqkm, 0.0001)
        
        if 'source_file' in cluster_data.columns:
            cluster_info['source_files'] = cluster_data['source_file'].unique().tolist()
        
        cluster_analysis['clusters'][c] = cluster_info
    
    return cluster_analysis

def perform_dbscan_clustering(df, eps_meters=200, min_samples=5):
    """
    Perform DBSCAN clustering on geographic data.
    
    Parameters:
    - df: DataFrame with latitude, longitude, and speed_mbps columns
    - eps_meters: Maximum distance (in meters) between two points to be considered neighbors
    - min_samples: Minimum number of points to form a dense region
    
    Returns:
    - df_clustered: DataFrame with added cluster labels
    """
    X = df[['latitude', 'longitude']].values
    
    eps_degrees = eps_meters / 111000
    
    dbscan = DBSCAN(eps=eps_degrees, min_samples=min_samples)
    df_clustered = df.copy()
    df_clustered['cluster'] = dbscan.fit_predict(X)
    
    df_clustered['speed_mbps'] = df_clustered['speed'].apply(parse_speed_mbps)
    
    return df_clustered

def calculate_distance(point1, point2):
    """Calculate distance between two GPS points in meters."""
    lat1 = np.radians(point1['latitude'])
    lon1 = np.radians(point1['longitude'])
    lat2 = np.radians(point2['latitude'])
    lon2 = np.radians(point2['longitude'])
    
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    r = 6371000
    
    return c * r

def segment_trajectory(df, min_distance=200, min_points=5):
    """
    Segment a trajectory into logical parts based on distance.
    
    Parameters:
    - df: DataFrame with latitude, longitude, speed columns, sorted by timestamp
    - min_distance: Minimum distance (meters) to consider a new segment
    - min_points: Minimum points per segment to include in results
    
    Returns:
    - segments: List of DataFrames, each representing a segment
    """
    if df.empty:
        return []
    
    if 'timestamp' in df.columns:
        df = df.sort_values('timestamp').copy()
    
    segments = []
    current_segment = [df.iloc[0]]
    
    for i in range(1, len(df)):
        current_point = df.iloc[i]
        last_point = df.iloc[i-1]
        
        distance = calculate_distance(last_point, current_point)
        
        if distance > min_distance:
            if len(current_segment) >= min_points:
                segments.append(pd.DataFrame(current_segment))
            current_segment = []
        
        current_segment.append(current_point)
    
    if len(current_segment) >= min_points:
        segments.append(pd.DataFrame(current_segment))
    
    return segments

def analyze_trajectory_segments(segments):
    """
    Analyze segmented trajectory data.
    
    Parameters:
    - segments: List of DataFrames representing trajectory segments
    
    Returns:
    - segment_stats: DataFrame with statistics for each segment
    """
    if not segments:
        return pd.DataFrame()
    
    segment_stats = []
    
    for i, segment in enumerate(segments):
        avg_speed = segment['speed_mbps'].mean()
        min_speed = segment['speed_mbps'].min()
        max_speed = segment['speed_mbps'].max()
        std_speed = segment['speed_mbps'].std()
        
        segment_length = 0
        for j in range(1, len(segment)):
            segment_length += calculate_distance(segment.iloc[j-1], segment.iloc[j])
        
        center_lat = segment['latitude'].mean()
        center_lon = segment['longitude'].mean()
        
        segment_stats.append({
            'segment_id': i,
            'points': len(segment),
            'avg_speed': avg_speed,
            'min_speed': min_speed,
            'max_speed': max_speed,
            'std_speed': std_speed,
            'length_meters': segment_length,
            'center_lat': center_lat,
            'center_lon': center_lon,
            'start_lat': segment['latitude'].iloc[0],
            'start_lon': segment['longitude'].iloc[0],
            'end_lat': segment['latitude'].iloc[-1],
            'end_lon': segment['longitude'].iloc[-1]
        })
    
    return pd.DataFrame(segment_stats)

def perform_iterative_neighborhood_fixed(df, k=5, linkage_method='single', reference_points=None):
    """
    Properly implements the iterative neighborhood algorithm according to the specification.
    
    The algorithm works as follows:
    1. Start with a reference point X as the initial neighborhood V0 = {X}
    2. Find the closest point Y1 to V0 according to the linkage method, then V1 = {X, Y1}
    3. Find the closest point Y2 to V1 according to the linkage method, then V2 = {X, Y1, Y2}
    4. Continue until k neighbors are found
    
    Parameters:
    - df (DataFrame): DataFrame containing data with lat, lon, speed_mbps
    - k (int): Number of neighbors to find
    - linkage_method (str): Linkage method ('single', 'complete', 'average')
    - reference_points (list): List of tuples (lat, lon) as reference points
    
    Returns:
    - DataFrame with additional columns indicating the neighborhood
    """
    import numpy as np
    import pandas as pd
    from sklearn.metrics.pairwise import haversine_distances
    
    df_result = df.copy()
    
    if reference_points is None or len(reference_points) == 0:
        num_ref_points = min(3, len(df))
        ref_indices = np.random.choice(len(df), num_ref_points, replace=False)
        reference_points = df.iloc[ref_indices][['latitude', 'longitude']].values
    
    df_result['neighborhood'] = -1
    
    coords = df[['latitude', 'longitude']].values
    coords_radians = np.radians(coords)
    distance_matrix = haversine_distances(coords_radians) * 6371
    
    for ref_idx, ref_point in enumerate(reference_points):
        ref_radians = np.radians(np.array([ref_point]).reshape(1, -1))
        distances_to_ref = haversine_distances(coords_radians, ref_radians).flatten() * 6371
        ref_idx_in_df = np.argmin(distances_to_ref)
        
        neighborhood = [ref_idx_in_df]
        
        available_points = list(range(len(df)))
        available_points.remove(ref_idx_in_df)
        
        for i in range(k):
            if not available_points:
                break
            
            min_dist = float('inf')
            next_neighbor = -1
            
            for point_idx in available_points:
                distances_to_neighborhood = []
                
                for neigh_idx in neighborhood:
                    dist = distance_matrix[point_idx, neigh_idx]
                    distances_to_neighborhood.append(dist)
                
                if linkage_method == 'single':
                    dist_to_neighborhood = min(distances_to_neighborhood)
                elif linkage_method == 'complete':
                    dist_to_neighborhood = max(distances_to_neighborhood)
                else:
                    dist_to_neighborhood = sum(distances_to_neighborhood) / len(distances_to_neighborhood)
                
                if dist_to_neighborhood < min_dist:
                    min_dist = dist_to_neighborhood
                    next_neighbor = point_idx
            
            if next_neighbor != -1:
                neighborhood.append(next_neighbor)
                available_points.remove(next_neighbor)
            else:
                break
        
        for idx, point_idx in enumerate(neighborhood):
            df_result.loc[point_idx, 'neighborhood'] = ref_idx
            df_result.loc[point_idx, f'neighbor_rank_{ref_idx}'] = idx
            
            if idx > 0:
                prev_neighborhood = neighborhood[:idx]
                
                distances = [distance_matrix[point_idx, prev_idx] for prev_idx in prev_neighborhood]
                
                if linkage_method == 'single':
                    dist_value = min(distances)
                elif linkage_method == 'complete':
                    dist_value = max(distances)
                else:
                    dist_value = sum(distances) / len(distances)
                
                df_result.loc[point_idx, f'distance_to_neighborhood_{ref_idx}'] = dist_value
    
    return df_result

def create_neighborhood_map_fixed(df, zoom_start=15):
    """
    Create an improved Folium map visualizing neighborhoods.
    
    Parameters:
    - df (DataFrame): DataFrame with columns 'latitude', 'longitude', 'neighborhood'
    - zoom_start (int): Initial zoom level
    
    Returns:
    - Folium map
    """
    import folium
    import numpy as np
    
    center_lat = df['latitude'].mean()
    center_lon = df['longitude'].mean()
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start)
    
    colors = ['#E41A1C', '#377EB8', '#4DAF4A', '#984EA3', '#FF7F00', '#FFFF33', '#A65628', '#F781BF', '#999999']
    
    neighborhoods = df[df['neighborhood'] >= 0]['neighborhood'].unique()
    
    neighborhood_groups = {neigh_id: folium.FeatureGroup(name=f"Neighborhood {neigh_id}") for neigh_id in neighborhoods}
    
    for i, neigh_id in enumerate(neighborhoods):
        color = colors[i % len(colors)]
        
        neigh_df = df[df['neighborhood'] == neigh_id].copy()
        
        rank_col = f'neighbor_rank_{neigh_id}'
        if rank_col in neigh_df.columns:
            neigh_df = neigh_df.sort_values(by=rank_col)
        
        if len(neigh_df) > 1:
            line_coords = neigh_df[['latitude', 'longitude']].values.tolist()
            
            folium.PolyLine(
                locations=line_coords,
                color=color,
                weight=2,
                opacity=0.7,
                dash_array='5, 5',
                popup=f'Neighborhood #{neigh_id} Construction Sequence',
                tooltip=f'Neighborhood #{neigh_id}'
            ).add_to(neighborhood_groups[neigh_id])
        
        for idx, row in neigh_df.iterrows():
            rank = row.get(rank_col, 1)
            radius = 10 if rank == 0 else max(5, 10 - rank * 0.5)
            opacity = 1.0 if rank == 0 else max(0.6, 1.0 - rank * 0.05)
            
            distance_info = ""
            dist_col = f'distance_to_neighborhood_{neigh_id}'
            if dist_col in row and rank > 0:
                distance_info = f"<br>Distance d'ajout: {row[dist_col]:.4f} km"
            
            popup_text = f"""
            <b>{'Point de référence' if rank == 0 else f'Voisin #{rank}'}</b><br>
            Latitude: {row['latitude']:.6f}<br>
            Longitude: {row['longitude']:.6f}<br>
            Débit: {row.get('speed_mbps', 'N/A'):.2f} Mbps{distance_info}
            """
            
            icon_color = 'white' if rank == 0 else 'black'
            
            if rank == 0:
                folium.Marker(
                    location=[row['latitude'], row['longitude']],
                    icon=folium.Icon(color=color, icon='star', prefix='fa'),
                    popup=folium.Popup(popup_text, max_width=300)
                ).add_to(neighborhood_groups[neigh_id])
            else:
                folium.CircleMarker(
                    location=[row['latitude'], row['longitude']],
                    radius=radius,
                    color='black',
                    weight=1,
                    fill=True,
                    fill_color=color,
                    fill_opacity=opacity,
                    popup=folium.Popup(popup_text, max_width=300),
                    tooltip=f"Voisin #{rank}"
                ).add_to(neighborhood_groups[neigh_id])
                
                folium.map.Marker(
                    [row['latitude'], row['longitude']],
                    icon=folium.DivIcon(
                        icon_size=(20, 20),
                        icon_anchor=(10, 10),
                        html=f'<div style="font-size: 10pt; color: {icon_color}; text-align: center; font-weight: bold;">{rank}</div>',
                    )
                ).add_to(neighborhood_groups[neigh_id])
    
    legend_html = '''
    <div style="position: fixed; 
        bottom: 50px; right: 50px; width: 250px; 
        border:2px solid grey; z-index:9999; font-size:12px;
        background-color:white; padding:10px; border-radius:5px">
        <h4 style="margin-top:0;">Légende</h4>
        <div><i class="fa fa-star" style="color:#E41A1C;"></i> Point de référence</div>
        <div style="margin-top:5px;"><i style="background:#377EB8; border-radius:50%; width:10px; height:10px; display:inline-block;"></i> Premiers voisins ajoutés</div>
        <div style="margin-top:5px;"><i style="background:#4DAF4A; border-radius:50%; width:10px; height:10px; display:inline-block;"></i> Voisins ajoutés ensuite</div>
        <div style="margin-top:5px;"><i style="border:1px solid #999; width:40px; display:inline-block; border-style:dashed;"></i> Ordre d'ajout des voisins</div>
        <p style="margin-top:10px; font-size:10px;">Les nombres sur les cercles indiquent l'ordre dans lequel les voisins ont été ajoutés au voisinage.</p>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))
    
    for group in neighborhood_groups.values():
        group.add_to(m)
    
    return m

def perform_iterative_neighborhood(df, k=5, linkage_method='single', reference_points=None):
    """
    Implements the iterative neighborhood algorithm according to specification.
    
    The algorithm works as follows:
    1. Start with a reference point X as the initial neighborhood V0 = {X}
    2. Find the closest point Y1 to V0 according to the linkage method, then V1 = {X, Y1}
    3. Find the closest point Y2 to V1 according to the linkage method, then V2 = {X, Y1, Y2}
    4. Continue until k neighbors are found
    
    Parameters:
    - df (DataFrame): DataFrame containing data with lat, lon, speed_mbps
    - k (int): Number of neighbors to find
    - linkage_method (str): Linkage method ('single', 'complete', 'average')
    - reference_points (list): List of tuples (lat, lon) as reference points
    
    Returns:
    - DataFrame with additional columns indicating the neighborhood
    """
    import numpy as np
    import pandas as pd
    from sklearn.metrics.pairwise import haversine_distances
    
    df_result = df.copy()
    
    if reference_points is None or len(reference_points) == 0:
        num_ref_points = min(3, len(df))
        ref_indices = np.random.choice(len(df), num_ref_points, replace=False)
        reference_points = df.iloc[ref_indices][['latitude', 'longitude']].values
    
    df_result['neighborhood'] = -1
    
    coords = df[['latitude', 'longitude']].values
    coords_radians = np.radians(coords)
    distance_matrix = haversine_distances(coords_radians) * 6371
    
    for ref_idx, ref_point in enumerate(reference_points):
        ref_radians = np.radians(np.array([ref_point]).reshape(1, -1))
        distances_to_ref = haversine_distances(coords_radians, ref_radians).flatten() * 6371
        ref_idx_in_df = np.argmin(distances_to_ref)
        
        neighborhood = [ref_idx_in_df]
        
        available_points = list(range(len(df)))
        available_points.remove(ref_idx_in_df)
        
        for i in range(k):
            if not available_points:
                break
            
            min_dist = float('inf')
            next_neighbor = -1
            
            for point_idx in available_points:
                distances_to_neighborhood = []
                
                for neigh_idx in neighborhood:
                    dist = distance_matrix[point_idx, neigh_idx]
                    distances_to_neighborhood.append(dist)
                
                if linkage_method == 'single':
                    dist_to_neighborhood = min(distances_to_neighborhood)
                elif linkage_method == 'complete':
                    dist_to_neighborhood = max(distances_to_neighborhood)
                else:
                    dist_to_neighborhood = sum(distances_to_neighborhood) / len(distances_to_neighborhood)
                
                if dist_to_neighborhood < min_dist:
                    min_dist = dist_to_neighborhood
                    next_neighbor = point_idx
            
            if next_neighbor != -1:
                neighborhood.append(next_neighbor)
                available_points.remove(next_neighbor)
            else:
                break
        
        for idx, point_idx in enumerate(neighborhood):
            df_result.loc[point_idx, 'neighborhood'] = ref_idx
            df_result.loc[point_idx, f'neighbor_rank_{ref_idx}'] = idx
            
            if idx > 0:
                prev_neighborhood = neighborhood[:idx]
                
                distances = [distance_matrix[point_idx, prev_idx] for prev_idx in prev_neighborhood]
                
                if linkage_method == 'single':
                    dist_value = min(distances)
                elif linkage_method == 'complete':
                    dist_value = max(distances)
                else:
                    dist_value = sum(distances) / len(distances)
                
                df_result.loc[point_idx, f'distance_to_neighborhood_{ref_idx}'] = dist_value
    
    return df_result

def create_neighborhood_map(df, zoom_start=15):
    """
    Create a Folium map visualizing neighborhoods.
    
    Parameters:
    - df (DataFrame): DataFrame with columns 'latitude', 'longitude', 'neighborhood'
    - zoom_start (int): Initial zoom level
    
    Returns:
    - Folium map
    """
    import folium
    import numpy as np
    
    center_lat = df['latitude'].mean()
    center_lon = df['longitude'].mean()
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start)
    
    colors = ['#E41A1C', '#377EB8', '#4DAF4A', '#984EA3', '#FF7F00', '#FFFF33', '#A65628', '#F781BF', '#999999']
    
    neighborhoods = df[df['neighborhood'] >= 0]['neighborhood'].unique()
    
    neighborhood_groups = {neigh_id: folium.FeatureGroup(name=f"Neighborhood {neigh_id}") for neigh_id in neighborhoods}
    
    for i, neigh_id in enumerate(neighborhoods):
        color = colors[i % len(colors)]
        
        neigh_df = df[df['neighborhood'] == neigh_id].copy()
        
        rank_col = f'neighbor_rank_{neigh_id}'
        if rank_col in neigh_df.columns:
            neigh_df = neigh_df.sort_values(by=rank_col)
        
        if len(neigh_df) > 1:
            line_coords = neigh_df[['latitude', 'longitude']].values.tolist()
            
            folium.PolyLine(
                locations=line_coords,
                color=color,
                weight=2,
                opacity=0.7,
                dash_array='5, 5',
                popup=f'Neighborhood #{neigh_id} Construction Sequence',
                tooltip=f'Neighborhood #{neigh_id}'
            ).add_to(neighborhood_groups[neigh_id])
        
        for idx, row in neigh_df.iterrows():
            rank = row.get(rank_col, 1)
            radius = 10 if rank == 0 else max(5, 10 - rank * 0.5)
            opacity = 1.0 if rank == 0 else max(0.6, 1.0 - rank * 0.05)
            
            distance_info = ""
            dist_col = f'distance_to_neighborhood_{neigh_id}'
            if dist_col in row and rank > 0:
                distance_info = f"<br>Distance d'ajout: {row[dist_col]:.4f} km"
            
            popup_text = f"""
            <b>{'Point de référence' if rank == 0 else f'Voisin #{rank}'}</b><br>
            Latitude: {row['latitude']:.6f}<br>
            Longitude: {row['longitude']:.6f}<br>
            Débit: {row.get('speed_mbps', 'N/A'):.2f} Mbps{distance_info}
            """
            
            icon_color = 'white' if rank == 0 else 'black'
            
            if rank == 0:
                folium.Marker(
                    location=[row['latitude'], row['longitude']],
                    icon=folium.Icon(color=color, icon='star', prefix='fa'),
                    popup=folium.Popup(popup_text, max_width=300)
                ).add_to(neighborhood_groups[neigh_id])
            else:
                folium.CircleMarker(
                    location=[row['latitude'], row['longitude']],
                    radius=radius,
                    color='black',
                    weight=1,
                    fill=True,
                    fill_color=color,
                    fill_opacity=opacity,
                    popup=folium.Popup(popup_text, max_width=300),
                    tooltip=f"Voisin #{rank}"
                ).add_to(neighborhood_groups[neigh_id])
                
                folium.map.Marker(
                    [row['latitude'], row['longitude']],
                    icon=folium.DivIcon(
                        icon_size=(20, 20),
                        icon_anchor=(10, 10),
                        html=f'<div style="font-size: 10pt; color: {icon_color}; text-align: center; font-weight: bold;">{rank}</div>',
                    )
                ).add_to(neighborhood_groups[neigh_id])
    
    legend_html = '''
    <div style="position: fixed; 
        bottom: 50px; right: 50px; width: 250px; 
        border:2px solid grey; z-index:9999; font-size:12px;
        background-color:white; padding:10px; border-radius:5px">
        <h4 style="margin-top:0;">Légende</h4>
        <div><i class="fa fa-star" style="color:#E41A1C;"></i> Point de référence</div>
        <div style="margin-top:5px;"><i style="background:#377EB8; border-radius:50%; width:10px; height:10px; display:inline-block;"></i> Premiers voisins ajoutés</div>
        <div style="margin-top:5px;"><i style="background:#4DAF4A; border-radius:50%; width:10px; height:10px; display:inline-block;"></i> Voisins ajoutés ensuite</div>
        <div style="margin-top:5px;"><i style="border:1px solid #999; width:40px; display:inline-block; border-style:dashed;"></i> Ordre d'ajout des voisins</div>
        <p style="margin-top:10px; font-size:10px;">Les nombres sur les cercles indiquent l'ordre dans lequel les voisins ont été ajoutés au voisinage.</p>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))
    
    for group in neighborhood_groups.values():
        group.add_to(m)
    
    return m

def analyze_neighborhoods(df):
    """
    Generate analysis of neighborhoods.
    
    Parameters:
    - df (DataFrame): DataFrame with 'neighborhood', 'speed_mbps', etc. columns
    
    Returns:
    - dict: Dictionary with analysis results
    """
    import numpy as np
    import pandas as pd
    
    analysis = {
        'neighborhoods': {},
        'global_stats': {},
        'evolution': {}
    }
    
    all_neighborhoods = df[df['neighborhood'] >= 0]['neighborhood'].unique()
    analysis['global_stats']['count'] = len(all_neighborhoods)
    
    for neigh_id in all_neighborhoods:
        neigh_df = df[df['neighborhood'] == neigh_id]
        
        rank_col = f'neighbor_rank_{neigh_id}'
        ref_point = neigh_df[neigh_df[rank_col] == 0] if rank_col in neigh_df.columns else None
        
        stats = {
            'size': len(neigh_df),
            'avg_speed': neigh_df['speed_mbps'].mean(),
            'std_speed': neigh_df['speed_mbps'].std(),
            'min_speed': neigh_df['speed_mbps'].min(),
            'max_speed': neigh_df['speed_mbps'].max(),
            'ref_point': None if ref_point is None or ref_point.empty else {
                'lat': ref_point.iloc[0]['latitude'],
                'lon': ref_point.iloc[0]['longitude'],
                'speed': ref_point.iloc[0]['speed_mbps']
            }
        }
        
        if len(neigh_df) > 1:
            lat_range = neigh_df['latitude'].max() - neigh_df['latitude'].min()
            lon_range = neigh_df['longitude'].max() - neigh_df['longitude'].min()
            
            lat_meters = lat_range * 111320
            lon_meters = lon_range * 111320 * np.cos(np.radians(neigh_df['latitude'].mean()))
            
            stats['dispersion_meters'] = max(lat_meters, lon_meters)
            stats['area_meters2'] = lat_meters * lon_meters
        else:
            stats['dispersion_meters'] = 0
            stats['area_meters2'] = 0
        
        if rank_col in neigh_df.columns:
            evolution = []
            
            neigh_df_sorted = neigh_df.sort_values(by=rank_col)
            
            ref_speed = neigh_df_sorted.iloc[0]['speed_mbps']
            
            for i in range(1, len(neigh_df_sorted)):
                current_neighbors = neigh_df_sorted.iloc[:i+1]
                
                evolution.append({
                    'step': i,
                    'new_point_speed': neigh_df_sorted.iloc[i]['speed_mbps'],
                    'speed_diff_from_ref': neigh_df_sorted.iloc[i]['speed_mbps'] - ref_speed,
                    'neighborhood_avg_speed': current_neighbors['speed_mbps'].mean(),
                    'neighborhood_std_speed': current_neighbors['speed_mbps'].std(),
                    'max_distance': current_neighbors[f'distance_to_neighborhood_{neigh_id}'].max() 
                        if f'distance_to_neighborhood_{neigh_id}' in current_neighbors.columns else None
                })
            
            analysis['evolution'][neigh_id] = evolution
        
        analysis['neighborhoods'][neigh_id] = stats
    
    return analysis

def create_enhanced_selection_map(df, zoom_start=15, max_points=1000, already_selected=None):
    """
    Crée une carte interactive améliorée permettant de sélectionner des points manuellement.
    
    Parameters:
    - df (DataFrame): DataFrame contenant les données avec lat, lon, speed_mbps
    - zoom_start (int): Niveau de zoom initial
    - max_points (int): Nombre maximum de points à afficher pour éviter les problèmes de performance
    - already_selected (list): Liste des IDs des points déjà sélectionnés
    
    Returns:
    - folium.Map: Carte Folium interactive
    """
    import folium
    from folium.plugins import MarkerCluster
    import json
    import numpy as np
    
    if already_selected is None:
        already_selected = []
    
    center_lat = df['latitude'].mean()
    center_lon = df['longitude'].mean()
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start)
    
    if len(df) > max_points:
        selected_indices = [int(id) for id in already_selected if isinstance(id, (int, str)) and str(id).isdigit()]
        selected_indices = [idx for idx in selected_indices if idx < len(df)]
        
        remaining_indices = [i for i in range(len(df)) if i not in selected_indices]
        sample_size = min(max_points - len(selected_indices), len(remaining_indices))
        sampled_indices = np.random.choice(remaining_indices, size=sample_size, replace=False)
        
        display_indices = list(selected_indices) + list(sampled_indices)
        display_df = df.iloc[display_indices].copy()
        
        sample_warning = f"""
        <div style="position:fixed; top:10px; left:50px; z-index:9999; background-color:white; 
        border:2px solid red; padding:10px; border-radius:5px; max-width:250px;">
            <b>⚠️ Attention:</b> Affichage limité à {max_points} points sur {len(df)} pour des raisons de performance.
            <br>Les points déjà sélectionnés sont toujours affichés.
        </div>
        """
        m.get_root().html.add_child(folium.Element(sample_warning))
    else:
        display_df = df.copy()
        display_indices = list(range(len(df)))
    
    marker_cluster = MarkerCluster(name="Tous les points").add_to(m)
    
    min_speed = df['speed_mbps'].min()
    max_speed = df['speed_mbps'].max()
    speed_range = max_speed - min_speed
    
    def get_speed_color(speed):
        normalized = (speed - min_speed) / max(speed_range, 0.001)
        
        if normalized < 0.25:
            return 'red'
        elif normalized < 0.5:
            return 'orange'
        elif normalized < 0.75:
            return 'blue'
        else:
            return 'green'
    
    for i, (idx, row) in enumerate(display_df.iterrows()):
        original_idx = display_indices[i]
        
        popup_text = f"""
        <div style="font-family: Arial; min-width: 180px;">
            <h4 style="margin-top: 0;">Point #{original_idx}</h4>
            <table style="width: 100%;">
                <tr><td><b>Latitude:</b></td><td>{row['latitude']:.6f}</td></tr>
                <tr><td><b>Longitude:</b></td><td>{row['longitude']:.6f}</td></tr>
                <tr><td><b>Débit:</b></td><td>{row['speed_mbps']:.2f} Mbps</td></tr>
                <tr><td><b>Fichier:</b></td><td>{row.get('source_file', 'N/A')}</td></tr>
            </table>
            <div style="margin-top: 5px; text-align: center;">
                <button onclick="selectPoint({original_idx}, {row['latitude']}, {row['longitude']}, {row['speed_mbps']})">
                    Sélectionner comme point de référence
                </button>
            </div>
        </div>
        """
        
        color = get_speed_color(row['speed_mbps'])
        
        is_selected = str(original_idx) in [str(id) for id in already_selected]
        
        if is_selected:
            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=8,
                fill=True,
                fill_color=color,
                color='yellow',
                fill_opacity=0.8,
                weight=3,
                popup=folium.Popup(popup_text, max_width=300),
                tooltip=f"✓ SÉLECTIONNÉ - Point #{original_idx} - {row['speed_mbps']:.2f} Mbps"
            ).add_to(marker_cluster)
        else:
            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=5,
                fill=True,
                fill_color=color,
                color='black',
                fill_opacity=0.7,
                weight=1,
                popup=folium.Popup(popup_text, max_width=300),
                tooltip=f"Point #{original_idx} - {row['speed_mbps']:.2f} Mbps"
            ).add_to(marker_cluster)
    
    selection_counter = """
    <div id="selection_counter" style="position:fixed; top:10px; right:10px; z-index:9999; background-color:white; 
    border:2px solid blue; padding:10px; border-radius:5px;">
        <b>Points sélectionnés:</b> <span id="counter">0</span>
    </div>
    """
    m.get_root().html.add_child(folium.Element(selection_counter))
    
    legend_html = f'''
    <div style="position: fixed; 
        bottom: 50px; right: 50px; width: 220px; 
        border:2px solid grey; z-index:9999; font-size:12px;
        background-color:white; padding:10px; border-radius:5px">
        <h4 style="margin-top: 0;">Légende</h4>
        <div><i style="background:red; border-radius:50%; width:10px; height:10px; display:inline-block;"></i> Faible débit (≈{min_speed:.2f}-{min_speed+speed_range*0.25:.2f} Mbps)</div>
        <div><i style="background:orange; border-radius:50%; width:10px; height:10px; display:inline-block;"></i> Moyen-faible ({min_speed+speed_range*0.25:.2f}-{min_speed+speed_range*0.5:.2f} Mbps)</div>
        <div><i style="background:blue; border-radius:50%; width:10px; height:10px; display:inline-block;"></i> Moyen-élevé ({min_speed+speed_range*0.5:.2f}-{min_speed+speed_range*0.75:.2f} Mbps)</div>
        <div><i style="background:green; border-radius:50%; width:10px; height:10px; display:inline-block;"></i> Élevé ({min_speed+speed_range*0.75:.2f}-{max_speed:.2f} Mbps)</div>
        <div style="margin-top: 5px; border-top: 1px solid #ccc; padding-top: 5px;">
            <b>Instructions:</b> Cliquez sur un point puis sur le bouton "Sélectionner comme point de référence".
        </div>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))
    
    selection_script = """
    <script>
        var selectedPoints = """ + json.dumps([{'id': id, 'lat': lat, 'lon': lon, 'speed': speed} 
                                              for id, lat, lon, speed in already_selected]) + """;
        
        document.getElementById('counter').textContent = selectedPoints.length;
        
        function selectPoint(id, lat, lon, speed) {
            var index = selectedPoints.findIndex(p => p.id === id);
            
            if (index === -1) {
                selectedPoints.push({id: id, lat: lat, lon: lon, speed: speed});
                document.getElementById('counter').textContent = selectedPoints.length;
            } else {
                selectedPoints.splice(index, 1);
                document.getElementById('counter').textContent = selectedPoints.length;
            }
            
            document.getElementById('selected_points').value = JSON.stringify(selectedPoints);
            
            document.getElementById('selected_points').dispatchEvent(new Event('change'));
        }
    </script>
    """
    m.get_root().html.add_child(folium.Element(selection_script))
    
    return m

def generate_neighborhood_insights(analysis):
    """
    Generate insights from neighborhood analysis.
    
    Parameters:
    - analysis (dict): Output from analyze_neighborhoods
    
    Returns:
    - list: List of insight strings
    """
    insights = []
    
    num_neighborhoods = analysis['global_stats']['count']
    insights.append(f"Nombre total de voisinages identifiés: {num_neighborhoods}")
    
    if num_neighborhoods == 0:
        insights.append("Aucun voisinage n'a été formé avec les paramètres actuels.")
        return insights
    
    if num_neighborhoods > 0:
        speeds = [(neigh_id, info['avg_speed']) for neigh_id, info in analysis['neighborhoods'].items()]
        best_neigh = max(speeds, key=lambda x: x[1])
        worst_neigh = min(speeds, key=lambda x: x[1])
        
        insights.append(f"Le voisinage #{best_neigh[0]} a le meilleur débit moyen ({best_neigh[1]:.2f} Mbps)")
        
        if num_neighborhoods > 1:
            insights.append(f"Le voisinage #{worst_neigh[0]} a le débit moyen le plus faible ({worst_neigh[1]:.2f} Mbps)")
            
            speed_diff = best_neigh[1] - worst_neigh[1]
            insights.append(f"Différence de débit entre le meilleur et le pire voisinage: {speed_diff:.2f} Mbps")
        
        dispersions = [(neigh_id, info.get('dispersion_meters', 0)) 
                       for neigh_id, info in analysis['neighborhoods'].items()]
        
        if dispersions:
            most_compact = min(dispersions, key=lambda x: x[1])
            most_spread = max(dispersions, key=lambda x: x[1])
            
            if most_compact[1] > 0:
                insights.append(f"Le voisinage #{most_compact[0]} est le plus compact géographiquement "
                               f"(dispersion de {most_compact[1]:.0f} mètres)")
            
            if num_neighborhoods > 1 and most_spread[1] > 0:
                insights.append(f"Le voisinage #{most_spread[0]} est le plus étendu géographiquement "
                               f"(dispersion de {most_spread[1]:.0f} mètres)")
        
        for neigh_id, evolution in analysis.get('evolution', {}).items():
            if evolution:
                first_neighbor = evolution[0]
                last_neighbor = evolution[-1]
                
                speed_trend = last_neighbor['neighborhood_avg_speed'] - first_neighbor['neighborhood_avg_speed']
                
                if abs(speed_trend) > 0.5:
                    trend_message = "augmente" if speed_trend > 0 else "diminue"
                    insights.append(f"Dans le voisinage #{neigh_id}, le débit moyen {trend_message} "
                                   f"à mesure que l'on ajoute des voisins (delta: {speed_trend:.2f} Mbps)")
                
                if last_neighbor['neighborhood_std_speed'] < 0.5:
                    insights.append(f"Le voisinage #{neigh_id} est très homogène en termes de débit "
                                   f"(écart-type: {last_neighbor['neighborhood_std_speed']:.2f} Mbps)")
                elif last_neighbor['neighborhood_std_speed'] > 2.0:
                    insights.append(f"Le voisinage #{neigh_id} présente une grande variabilité de débit "
                                   f"(écart-type: {last_neighbor['neighborhood_std_speed']:.2f} Mbps)")
    
    return insights

def analyze_neighborhoods_improved(df):
    """
    Generate more comprehensive analysis of neighborhoods.
    
    Parameters:
    - df (DataFrame): DataFrame with 'neighborhood', 'speed_mbps', etc. columns
    
    Returns:
    - dict: Dictionary with analysis results
    """
    import numpy as np
    import pandas as pd
    
    analysis = {
        'neighborhoods': {},
        'global_stats': {},
        'evolution': {}
    }
    
    all_neighborhoods = df[df['neighborhood'] >= 0]['neighborhood'].unique()
    analysis['global_stats']['count'] = len(all_neighborhoods)
    
    for neigh_id in all_neighborhoods:
        neigh_df = df[df['neighborhood'] == neigh_id]
        
        rank_col = f'neighbor_rank_{neigh_id}'
        ref_point = neigh_df[neigh_df[rank_col] == 0] if rank_col in neigh_df.columns else None
        
        stats = {
            'size': len(neigh_df),
            'avg_speed': neigh_df['speed_mbps'].mean(),
            'std_speed': neigh_df['speed_mbps'].std(),
            'min_speed': neigh_df['speed_mbps'].min(),
            'max_speed': neigh_df['speed_mbps'].max(),
            'ref_point': None if ref_point is None or ref_point.empty else {
                'lat': ref_point.iloc[0]['latitude'],
                'lon': ref_point.iloc[0]['longitude'],
                'speed': ref_point.iloc[0]['speed_mbps']
            }
        }
        
        if len(neigh_df) > 1:
            lat_range = neigh_df['latitude'].max() - neigh_df['latitude'].min()
            lon_range = neigh_df['longitude'].max() - neigh_df['longitude'].min()
            
            lat_meters = lat_range * 111320
            lon_meters = lon_range * 111320 * np.cos(np.radians(neigh_df['latitude'].mean()))
            
            stats['dispersion_meters'] = max(lat_meters, lon_meters)
            stats['area_meters2'] = lat_meters * lon_meters
        else:
            stats['dispersion_meters'] = 0
            stats['area_meters2'] = 0
        
        if rank_col in neigh_df.columns:
            evolution = []
            
            neigh_df_sorted = neigh_df.sort_values(by=rank_col)
            
            ref_speed = neigh_df_sorted.iloc[0]['speed_mbps']
            
            for i in range(1, len(neigh_df_sorted)):
                current_neighbors = neigh_df_sorted.iloc[:i+1]
                
                evolution.append({
                    'step': i,
                    'new_point_speed': neigh_df_sorted.iloc[i]['speed_mbps'],
                    'speed_diff_from_ref': neigh_df_sorted.iloc[i]['speed_mbps'] - ref_speed,
                    'neighborhood_avg_speed': current_neighbors['speed_mbps'].mean(),
                    'neighborhood_std_speed': current_neighbors['speed_mbps'].std(),
                    'max_distance': current_neighbors[f'distance_to_neighborhood_{neigh_id}'].max() 
                        if f'distance_to_neighborhood_{neigh_id}' in current_neighbors.columns else None
                })
            
            analysis['evolution'][neigh_id] = evolution
        
        analysis['neighborhoods'][neigh_id] = stats
    
    return analysis

def generate_neighborhood_insights_improved(analysis):
    """
    Generate improved insights from neighborhood analysis.
    
    Parameters:
    - analysis (dict): Output from analyze_neighborhoods_improved
    
    Returns:
    - list: List of insight strings
    """
    insights = []
    
    num_neighborhoods = analysis['global_stats']['count']
    insights.append(f"Nombre total de voisinages identifiés: {num_neighborhoods}")
    
    if num_neighborhoods == 0:
        insights.append("Aucun voisinage n'a été formé avec les paramètres actuels.")
        return insights
    
    if num_neighborhoods > 0:
        speeds = [(neigh_id, info['avg_speed']) for neigh_id, info in analysis['neighborhoods'].items()]
        best_neigh = max(speeds, key=lambda x: x[1])
        worst_neigh = min(speeds, key=lambda x: x[1])
        
        insights.append(f"Le voisinage #{best_neigh[0]} a le meilleur débit moyen ({best_neigh[1]:.2f} Mbps)")
        
        if num_neighborhoods > 1:
            insights.append(f"Le voisinage #{worst_neigh[0]} a le débit moyen le plus faible ({worst_neigh[1]:.2f} Mbps)")
            
            speed_diff = best_neigh[1] - worst_neigh[1]
            insights.append(f"Différence de débit entre le meilleur et le pire voisinage: {speed_diff:.2f} Mbps")
        
        dispersions = [(neigh_id, info.get('dispersion_meters', 0)) 
                       for neigh_id, info in analysis['neighborhoods'].items()]
        
        if dispersions:
            most_compact = min(dispersions, key=lambda x: x[1])
            most_spread = max(dispersions, key=lambda x: x[1])
            
            if most_compact[1] > 0:
                insights.append(f"Le voisinage #{most_compact[0]} est le plus compact géographiquement "
                               f"(dispersion de {most_compact[1]:.0f} mètres)")
            
            if num_neighborhoods > 1 and most_spread[1] > 0:
                insights.append(f"Le voisinage #{most_spread[0]} est le plus étendu géographiquement "
                               f"(dispersion de {most_spread[1]:.0f} mètres)")
        
        for neigh_id, evolution in analysis.get('evolution', {}).items():
            if evolution:
                first_neighbor = evolution[0]
                last_neighbor = evolution[-1]
                
                speed_trend = last_neighbor['neighborhood_avg_speed'] - first_neighbor['neighborhood_avg_speed']
                
                if abs(speed_trend) > 0.5:
                    trend_message = "augmente" if speed_trend > 0 else "diminue"
                    insights.append(f"Dans le voisinage #{neigh_id}, le débit moyen {trend_message} "
                                   f"à mesure que l'on ajoute des voisins (delta: {speed_trend:.2f} Mbps)")
                
                if last_neighbor['neighborhood_std_speed'] < 0.5:
                    insights.append(f"Le voisinage #{neigh_id} est très homogène en termes de débit "
                                   f"(écart-type: {last_neighbor['neighborhood_std_speed']:.2f} Mbps)")
                elif last_neighbor['neighborhood_std_speed'] > 2.0:
                    insights.append(f"Le voisinage #{neigh_id} présente une grande variabilité de débit "
                                   f"(écart-type: {last_neighbor['neighborhood_std_speed']:.2f} Mbps)")
    
    return insights

def generate_cluster_insights(analysis):
    """
    Generate human-readable insights from cluster analysis.
    
    Parameters:
    - analysis: Output from analyze_clusters function
    
    Returns:
    - insights: List of insight strings
    """
    insights = []
    
    if 'clusters' not in analysis or not analysis['clusters']:
        return ["Pas assez de données pour générer des insights."]
    
    valid_clusters = {k: v for k, v in analysis['clusters'].items() if k != -1}
    
    if not valid_clusters:
        return ["Tous les points ont été classés comme bruit. Essayez d'ajuster les paramètres."]
    
    speeds = [(k, v['avg_speed']) for k, v in valid_clusters.items()]
    fastest_cluster = max(speeds, key=lambda x: x[1])
    slowest_cluster = min(speeds, key=lambda x: x[1])
    
    if fastest_cluster[0] != slowest_cluster[0]:
        speed_diff = fastest_cluster[1] - slowest_cluster[1]
        insights.append(f"Le cluster {fastest_cluster[0]} a le meilleur débit moyen ({fastest_cluster[1]:.2f} Mbps), " + 
                       f"tandis que le cluster {slowest_cluster[0]} a le débit le plus bas ({slowest_cluster[1]:.2f} Mbps). " +
                       f"La différence est de {speed_diff:.2f} Mbps.")
    
    sizes = [(k, v['size']) for k, v in valid_clusters.items()]
    largest_cluster = max(sizes, key=lambda x: x[1])
    smallest_cluster = min(sizes, key=lambda x: x[1])
    
    insights.append(f"Le cluster {largest_cluster[0]} contient le plus de points ({largest_cluster[1]} points, " +
                   f"{valid_clusters[largest_cluster[0]]['percentage']:.1f}% du total).")
    
    stds = [(k, v['std_speed']) for k, v in valid_clusters.items()]
    most_consistent = min(stds, key=lambda x: x[1])
    least_consistent = max(stds, key=lambda x: x[1])
    
    insights.append(f"Le cluster {most_consistent[0]} a la meilleure consistance de débit " +
                   f"(écart-type: {most_consistent[1]:.2f} Mbps).")
    
    if most_consistent[0] != least_consistent[0]:
        insights.append(f"Le cluster {least_consistent[0]} présente la plus grande variation de débit " +
                       f"(écart-type: {least_consistent[1]:.2f} Mbps).")
    
    densities = [(k, v['density']) for k, v in valid_clusters.items() if v['density'] < float('inf')]
    if densities:
        most_dense = max(densities, key=lambda x: x[1])
        insights.append(f"Le cluster {most_dense[0]} est le plus dense géographiquement avec " +
                       f"{most_dense[1]:.1f} points par km².")
    
    if -1 in analysis['clusters']:
        noise_pct = analysis['clusters'][-1]['percentage']
        if noise_pct > 20:
            insights.append(f"Une proportion importante de points ({noise_pct:.1f}%) a été classée comme bruit. " +
                           "Cela suggère des mesures isolées ou des conditions de réseau très variables.")
    
    if len(valid_clusters) >= 2:
        coords = [(c, v['avg_lat'], v['avg_lon']) for c, v in valid_clusters.items()]
        min_distance = float('inf')
        closest_pair = None
        
        for i in range(len(coords)):
            for j in range(i+1, len(coords)):
                c1, lat1, lon1 = coords[i]
                c2, lat2, lon2 = coords[j]
                dist = np.sqrt((lat1-lat2)**2 + (lon1-lon2)**2) * 111000
                if dist < min_distance:
                    min_distance = dist
                    closest_pair = (c1, c2)
        
        if min_distance < 200:
            insights.append(f"Les clusters {closest_pair[0]} et {closest_pair[1]} sont très proches géographiquement " +
                           f"({min_distance:.0f}m) mais présentent des caractéristiques de débit différentes.")
    
    return insights

with st.sidebar:
    st.header("Navigation")
    page = st.radio("Aller à:", ["Tableau de Bord", "Analyse Avancée", "Analyse IA"])
    st.session_state.current_page = page
    
    st.markdown("---")

if st.session_state.current_page == "Tableau de Bord":
    with st.sidebar:
        st.header("Explorer les fichiers")

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

                if not df_csv.empty:
                    df_csv["speed_mbps"] = df_csv["speed"].apply(parse_speed_mbps)

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

                    st.subheader("Statistiques de ce trajet")
                    min_speed = df_csv["speed_mbps"].min()
                    max_speed = df_csv["speed_mbps"].max()
                    avg_speed = df_csv["speed_mbps"].mean()
                    
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Débit min", f"{min_speed:.2f} Mbps")
                    col2.metric("Débit max", f"{max_speed:.2f} Mbps")
                    col3.metric("Débit moyen", f"{avg_speed:.2f} Mbps")

                    st.subheader("Carte du trajet")
                    map_for_file = create_folium_map(df_csv, zoom_start=16)
                    folium_static(map_for_file, width=1200, height=700)
        else:
            st.write("Aucun fichier CSV trouvé.")

    st.title("Tableau de Bord - Données Globales")

    all_data_df = load_all_csvs(RECORDS_DIR)

    if all_data_df.empty:
        st.write("Aucune donnée disponible (aucun CSV).")
    else:
        st.write("**Carte globale** avec tous les points de tous les fichiers CSV :")

        col1, col2, col3 = st.columns(3)
        all_data_df["speed_mbps"] = all_data_df["speed"].apply(parse_speed_mbps)
        
        min_speed = all_data_df["speed_mbps"].min()
        max_speed = all_data_df["speed_mbps"].max()
        avg_speed = all_data_df["speed_mbps"].mean()
        
        col1.metric("Débit minimum", f"{min_speed:.2f} Mbps")
        col2.metric("Débit maximum", f"{max_speed:.2f} Mbps")
        col3.metric("Débit moyen", f"{avg_speed:.2f} Mbps")

        combined_map = create_folium_map(all_data_df, zoom_start=15)
        folium_static(combined_map, width=1200, height=700)

        st.write("**Aperçu de toutes les données combinées** :")
        st.dataframe(all_data_df.head(50))

    st.write("---")
    st.write("Les données sont automatiquement sauvegardées toutes les 3 secondes d'inactivité MQTT.")

elif st.session_state.current_page == "Analyse Avancée":
    with st.sidebar:
        st.header("Options d'analyse")
        
        st.subheader("Sélectionner des fichiers pour comparer")
        
        csv_files = sorted(
            [f for f in os.listdir(RECORDS_DIR) if f.endswith(".csv")],
            reverse=True
        )
        
        if csv_files:
            selected_files = st.multiselect(
                "Choisir les fichiers à comparer", 
                options=csv_files,
                default=csv_files[:min(2, len(csv_files))]
            )
        else:
            st.write("Aucun fichier CSV trouvé.")
            selected_files = []

    st.title("Analyse Avancée des Données")
    
    if not selected_files:
        st.warning("Veuillez sélectionner au moins un fichier dans la barre latérale pour commencer l'analyse.")
    else:
        selected_dfs = {}
        for file in selected_files:
            path = os.path.join(RECORDS_DIR, file)
            df = load_single_csv(path)
            df["speed_mbps"] = df["speed"].apply(parse_speed_mbps)
            selected_dfs[file] = df
        
        st.header("Comparaison des Débits")
        
        stats_df = pd.DataFrame({
            'Fichier': [],
            'Points': [],
            'Débit Min (Mbps)': [],
            'Débit Max (Mbps)': [],
            'Débit Moyen (Mbps)': [],
            'Écart Type (Mbps)': []
        })
        
        for file, df in selected_dfs.items():
            new_row = pd.DataFrame({
                'Fichier': [file],
                'Points': [len(df)],
                'Débit Min (Mbps)': [df['speed_mbps'].min()],
                'Débit Max (Mbps)': [df['speed_mbps'].max()],
                'Débit Moyen (Mbps)': [df['speed_mbps'].mean()],
                'Écart Type (Mbps)': [df['speed_mbps'].std()]
            })
            stats_df = pd.concat([stats_df, new_row], ignore_index=True)
        
        st.dataframe(stats_df.style.format({
            'Débit Min (Mbps)': '{:.2f}',
            'Débit Max (Mbps)': '{:.2f}',
            'Débit Moyen (Mbps)': '{:.2f}',
            'Écart Type (Mbps)': '{:.2f}'
        }))
        
        st.header("Distribution des Débits")
        
        chart_data = pd.DataFrame()
        for file, df in selected_dfs.items():
            file_df = pd.DataFrame({
                'Débit (Mbps)': df['speed_mbps'],
                'Fichier': file
            })
            chart_data = pd.concat([chart_data, file_df], ignore_index=True)
        
        if len(selected_files) > 0:
            density_chart = alt.Chart(chart_data).transform_density(
                'Débit (Mbps)',
                as_=['Débit (Mbps)', 'Densité'],
                groupby=['Fichier']
            ).mark_area(opacity=0.5).encode(
                x=alt.X('Débit (Mbps):Q', title='Débit (Mbps)'),
                y=alt.Y('Densité:Q', title='Densité'),
                color='Fichier:N'
            ).properties(
                title='Distribution des Débits par Fichier',
                width=700, 
                height=400
            )
            
            st.altair_chart(density_chart, use_container_width=True)
        
        st.header("Carte comparative des trajets")
        
        if len(selected_files) > 0:
            combined_df = pd.concat([df for df in selected_dfs.values()], ignore_index=True)
            combined_df["source_file"] = combined_df.index.map(
                lambda i: list(selected_dfs.keys())[sum(len(df) <= i for df in selected_dfs.values())-1]
            )
            
            m = folium.Map(
                location=[combined_df['latitude'].mean(), combined_df['longitude'].mean()],
                zoom_start=14
            )
            
            colors = ['blue', 'red', 'green', 'purple', 'orange', 'darkblue', 'darkred', 'cadetblue', 'darkgreen', 'darkpurple']
            
            for i, (file, df) in enumerate(selected_dfs.items()):
                color = colors[i % len(colors)]
                
                folium.PolyLine(
                    locations=df[['latitude', 'longitude']].values,
                    color=color,
                    weight=3,
                    opacity=0.7,
                    tooltip=file
                ).add_to(m)
                
                folium.Marker(
                    location=[df['latitude'].iloc[0], df['longitude'].iloc[0]],
                    tooltip=f"Début: {file}",
                    icon=folium.Icon(color=color, icon="play", prefix="fa")
                ).add_to(m)
                
                folium.Marker(
                    location=[df['latitude'].iloc[-1], df['longitude'].iloc[-1]],
                    tooltip=f"Fin: {file}",
                    icon=folium.Icon(color=color, icon="stop", prefix="fa")
                ).add_to(m)
            
            folium_static(m, width=1200, height=700)
        
        st.header("Analyse des zones de faible débit")
        
        threshold = st.slider(
            "Seuil de débit faible (Mbps) : toutes les point en dessous du seuil:", 
            min_value=0.0,
            max_value=5.0,
            value=1.5,
            step=0.1
        )
        
        for file, df in selected_dfs.items():
            low_speed_df = df[df['speed_mbps'] < threshold].copy()
            
            st.subheader(f"Points à faible débit dans {file}:")
            if low_speed_df.empty:
                st.write(f"Aucun point avec un débit inférieur à {threshold} Mbps.")
            else:
                st.write(f"Nombre de points à faible débit: {len(low_speed_df)} sur {len(df)} ({len(low_speed_df)/len(df)*100:.1f}%)")
                
                if not low_speed_df.empty:
                    low_speed_map = folium.Map(
                        location=[low_speed_df['latitude'].mean(), low_speed_df['longitude'].mean()],
                        zoom_start=16
                    )
                    
                    for _, row in df.iterrows():
                        folium.CircleMarker(
                            location=[row['latitude'], row['longitude']],
                            radius=3,
                            fill=True,
                            fill_color='lightgray',
                            color='lightgray',
                            fill_opacity=0.3
                        ).add_to(low_speed_map)
                    
                    folium.PolyLine(
                        locations=df[['latitude', 'longitude']].values,
                        color='gray',
                        weight=2,
                        opacity=0.5
                    ).add_to(low_speed_map)
                    
                    for _, row in low_speed_df.iterrows():
                        folium.CircleMarker(
                            location=[row['latitude'], row['longitude']],
                            radius=6,
                            fill=True,
                            fill_color='red',
                            color='black',
                            fill_opacity=0.7,
                            popup=f"Débit: {row['speed']}, Heure: {row.get('datetime', '')}"
                        ).add_to(low_speed_map)
                    
                    folium_static(low_speed_map, width=1200, height=700)
        
        st.write("---")
        st.info("Cette page d'analyse peut être étendue avec d'autres fonctionnalités selon vos besoins.")

elif st.session_state.current_page == "Analyse IA":
    with st.sidebar:
        st.header("Paramètres d'analyse avancée")
        
        algorithm = st.radio(
            "Type d'analyse:",
            ["K-Means (Groupes de mesures)", "DBSCAN (Zones de couverture)", "Voisinage à Liaison Itérative", 
            "Détection d'Anomalies", "Prédiction de Débit", "Analyse Temporelle"],
            help="Choisissez le type d'analyse que vous souhaitez effectuer sur les données."
        )
        
        st.subheader("Sélection des données")
        data_option = st.radio(
            "Utiliser les données de:",
            ["Tous les fichiers CSV", "Sélection de fichiers spécifiques"]
        )
        
        if data_option == "Sélection de fichiers spécifiques":
            csv_files = sorted([f for f in os.listdir(RECORDS_DIR) if f.endswith(".csv")], reverse=True)
            
            if csv_files:
                selected_files = st.multiselect(
                    "Choisir les fichiers pour l'analyse", 
                    options=csv_files,
                    default=csv_files[:min(3, len(csv_files))]
                )
            else:
                st.write("Aucun fichier CSV trouvé.")
                selected_files = []
        else:
            selected_files = sorted([f for f in os.listdir(RECORDS_DIR) if f.endswith(".csv")], reverse=True)
        
        if algorithm == "K-Means (Groupes de mesures)":
            st.subheader("Paramètres K-Means")
            auto_k = st.checkbox("Détecter automatiquement le nombre de clusters", value=True)
            
            if not auto_k:
                n_clusters = st.slider(
                    "Nombre de clusters (K):", 
                    min_value=2, 
                    max_value=15, 
                    value=5
                )
            else:
                st.info("Le nombre optimal de clusters sera détecté automatiquement.")
                n_clusters = None
        
        elif algorithm == "DBSCAN (Zones de couverture)":
            st.subheader("Paramètres DBSCAN")
            eps = st.slider(
                "Distance maximale entre points (en mètres):", 
                min_value=50, 
                max_value=500, 
                value=200,
                step=50,
                help="La distance maximale entre deux points pour qu'ils soient considérés comme voisins."
            )
            min_samples = st.slider(
                "Nombre minimum de points par cluster:", 
                min_value=2, 
                max_value=20, 
                value=5,
                help="Le nombre minimum de points pour former un cluster."
            )
        
        elif algorithm == "Voisinage à Liaison Itérative":
            st.subheader("Paramètres du Voisinage")
            k_neighbors = st.slider(
                "Nombre de voisins (k):", 
                min_value=3, 
                max_value=20, 
                value=5,
                help="Le nombre de voisins à rechercher pour chaque point de référence."
            )
            
            linkage_method = st.selectbox(
                "Méthode de liaison:", 
                options=["single", "complete", "average"]
            )
            
            ref_point_method = st.radio(
                "Sélection des points de référence:",
                ["Aléatoire", "Points à faible débit", "Points à haut débit", "Sélection manuelle"]
            )

            if ref_point_method == "Sélection manuelle":
                num_ref_points = st.slider(
                    "Nombre maximum de points à sélectionner manuellement:", 
                    min_value=1, 
                    max_value=10, 
                    value=3
                )
            elif ref_point_method == "Aléatoire":
                num_ref_points = st.slider(
                    "Nombre de points de référence aléatoires:", 
                    min_value=1, 
                    max_value=10, 
                    value=3
                )
            else:
                num_ref_points = st.slider(
                    "Nombre de points de référence:", 
                    min_value=1, 
                    max_value=5, 
                    value=2
                )
                threshold_percentile = st.slider(
                    f"Percentile de débit {'inférieur' if ref_point_method == 'Points à faible débit' else 'supérieur'}:", 
                    min_value=1, 
                    max_value=50, 
                    value=10
                )
        
        elif algorithm == "Détection d'Anomalies":
            st.subheader("Paramètres de Détection d'Anomalies")
            contamination = st.slider(
                "Sensibilité (% attendu d'anomalies):", 
                min_value=0.01, 
                max_value=0.2, 
                value=0.05,
                format="%.2f",
                help="Plus le pourcentage est élevé, plus le modèle détectera d'anomalies."
            )
        
        elif algorithm == "Prédiction de Débit":
            st.subheader("Paramètres de Prédiction")
            grid_size = st.slider(
                "Densité de la grille de prédiction:", 
                min_value=10, 
                max_value=50, 
                value=25,
                help="Plus la valeur est élevée, plus la carte de prédiction sera précise (mais plus lente à générer)."
            )

    st.title("Analyse Avancée par Intelligence Artificielle")
    
    if not selected_files:
        st.warning("Aucun fichier sélectionné ou disponible. Veuillez choisir des fichiers pour l'analyse.")
    else:
        with st.spinner("Chargement et préparation des données..."):
            dfs = []
            for file in selected_files:
                path = os.path.join(RECORDS_DIR, file)
                df = load_single_csv(path)
                df["speed_mbps"] = df["speed"].apply(parse_speed_mbps)
                df["source_file"] = file
                dfs.append(df)
            
            df_combined = pd.concat(dfs, ignore_index=True)
            
            df_combined = df_combined.dropna(subset=['latitude', 'longitude', 'speed_mbps'])
            
            st.write(f"Nombre total de points: {len(df_combined)}")
            st.write(f"Fichiers inclus: {len(selected_files)}")
            
            summary = pd.DataFrame({
                'Statistique': ['Nombre de points', 'Débit moyen (Mbps)', 'Débit minimum (Mbps)', 'Débit maximum (Mbps)'],
                'Valeur': [
                    len(df_combined),
                    df_combined['speed_mbps'].mean(),
                    df_combined['speed_mbps'].min(),
                    df_combined['speed_mbps'].max()
                ]
            })
            
            st.dataframe(summary.style.format({
                'Valeur': lambda x: f'{x:.2f}' if isinstance(x, float) else str(x)
            }))
        
        if algorithm == "K-Means (Groupes de mesures)":
            with st.spinner("Application de l'algorithme K-Means..."):
                if auto_k:
                    st.info("Recherche du nombre optimal de clusters...")
                    n_clusters, silhouette_scores, inertia_values, k_values = find_optimal_k(df_combined)
                    st.success(f"Nombre optimal de clusters: {n_clusters}")
                    
                    if silhouette_scores and inertia_values:
                        col1, col2 = st.columns(2)
                        with col1:
                            st.subheader("Méthode de la silhouette")
                            fig, ax = plt.subplots()
                            ax.plot(k_values, silhouette_scores, 'o-')
                            ax.set_xlabel('Nombre de clusters (k)')
                            ax.set_ylabel('Score de silhouette')
                            ax.set_title('Score de silhouette par nombre de clusters')
                            st.pyplot(fig)
                            
                        with col2:
                            st.subheader("Méthode du coude (Elbow)")
                            fig, ax = plt.subplots()
                            ax.plot(k_values, inertia_values, 'o-')
                            ax.set_xlabel('Nombre de clusters (k)')
                            ax.set_ylabel('Inertie')
                            ax.set_title('Méthode du coude pour déterminer k')
                            st.pyplot(fig)
                
                df_clustered, kmeans_model = perform_kmeans_clustering(df_combined, n_clusters=n_clusters)
                
                scaler = StandardScaler()
                X_scaled = scaler.fit_transform(df_combined[['latitude', 'longitude', 'speed_mbps']].values)
                centers_scaled = kmeans_model.cluster_centers_
                                
                centers_orig = scaler.inverse_transform(centers_scaled)

                st.session_state.kmeans_centers = centers_orig

                st.session_state.kmeans_centers_info = {}
                for i, center in enumerate(centers_orig):
                    cluster_data = df_clustered[df_clustered['cluster'] == i]
                    st.session_state.kmeans_centers_info[i] = {
                        'latitude': center[0],
                        'longitude': center[1],
                        'avg_speed': center[2],
                        'points_count': len(cluster_data),
                        'std_speed': cluster_data['speed_mbps'].std(),
                        'min_speed': cluster_data['speed_mbps'].min(),
                        'max_speed': cluster_data['speed_mbps'].max()
                    }
            
            with st.spinner("Analyse des résultats du clustering..."):
                cluster_analysis = analyze_clusters(df_clustered)
                insights = generate_cluster_insights(cluster_analysis)
                
                st.header("Insights sur les Clusters")
                for insight in insights:
                    st.markdown(f"- {insight}")
                
                st.header("Statistiques détaillées par cluster")
                
                cluster_stats = []
                for cluster_id, info in cluster_analysis['clusters'].items():
                    if cluster_id != -1:
                        cluster_stats.append({
                            'Cluster': cluster_id,
                            'Points': info['size'],
                            'Débit Moyen (Mbps)': info['avg_speed'],
                            'Écart-Type (Mbps)': info['std_speed'],
                            'Débit Min (Mbps)': info['min_speed'],
                            'Débit Max (Mbps)': info['max_speed'],
                            'Taille Approx. (m)': max(info['lat_range'], info['lon_range'])
                        })
                
                if -1 in cluster_analysis['clusters']:
                    noise_info = cluster_analysis['clusters'][-1]
                    cluster_stats.append({
                        'Cluster': 'Bruit (-1)',
                        'Points': noise_info['size'],
                        'Débit Moyen (Mbps)': noise_info['avg_speed'],
                        'Écart-Type (Mbps)': noise_info['std_speed'],
                        'Débit Min (Mbps)': noise_info['min_speed'],
                        'Débit Max (Mbps)': noise_info['max_speed'],
                        'Taille Approx. (m)': max(noise_info['lat_range'], noise_info['lon_range'])
                    })
                
                stats_df = pd.DataFrame(cluster_stats)
                st.dataframe(stats_df.style.format({
                    'Débit Moyen (Mbps)': '{:.2f}',
                    'Écart-Type (Mbps)': '{:.2f}',
                    'Débit Min (Mbps)': '{:.2f}',
                    'Débit Max (Mbps)': '{:.2f}',
                    'Taille Approx. (m)': '{:.0f}'
                }))
            
            st.header("Carte des Clusters")
            cluster_map = create_cluster_map(df_clustered, zoom_start=15)
            folium_static(cluster_map, width=1200, height=700)
            
            st.header("Distribution des Débits par Cluster")
            speed_cluster_df = df_clustered.copy()
            speed_cluster_df['cluster_label'] = speed_cluster_df['cluster'].apply(
                lambda x: f"Cluster {x}" if x >= 0 else "Bruit (-1)"
            )
            
            fig, ax = plt.subplots(figsize=(10, 6))
            sns.violinplot(x='cluster_label', y='speed_mbps', data=speed_cluster_df, ax=ax)
            ax.set_title('Distribution des Débits par Cluster')
            ax.set_xlabel('Cluster')
            ax.set_ylabel('Débit (Mbps)')
            st.pyplot(fig)

        elif algorithm == "DBSCAN (Zones de couverture)":
            with st.spinner("Application de l'algorithme DBSCAN..."):
                df_clustered = perform_dbscan_clustering(df_combined, eps_meters=eps, min_samples=min_samples)
                
                n_clusters = len(set(df_clustered['cluster'].unique()) - {-1})
                st.success(f"Nombre de zones détectées: {n_clusters}")
                
                cluster_densities = {}
                for cluster in sorted([c for c in df_clustered['cluster'].unique() if c >= 0]):
                    cluster_data = df_clustered[df_clustered['cluster'] == cluster]
                    
                    min_lat, max_lat = cluster_data['latitude'].min(), cluster_data['latitude'].max()
                    min_lon, max_lon = cluster_data['longitude'].min(), cluster_data['longitude'].max()
                    
                    lat_range_km = (max_lat - min_lat) * 111.32
                    lon_range_km = (max_lon - min_lon) * 111.32 * np.cos(np.radians(cluster_data['latitude'].mean()))
                    
                    area_km2 = lat_range_km * lon_range_km
                    
                    density = len(cluster_data) / max(area_km2, 0.0001)
                    
                    cluster_densities[cluster] = {
                        'area_km2': area_km2,
                        'density': density,
                        'points': len(cluster_data)
                    }

                density_df = pd.DataFrame([
                    {
                        'Cluster': cluster,
                        'Points': info['points'],
                        'Superficie (km²)': info['area_km2'],
                        'Densité (pts/km²)': info['density']
                    }
                    for cluster, info in cluster_densities.items()
                ])

                st.subheader("Densité des Zones")
                st.dataframe(density_df.style.format({
                    'Superficie (km²)': '{:.4f}',
                    'Densité (pts/km²)': '{:.1f}'
                }))

                st.info("""
                DBSCAN identifie des zones de densité homogène. Un avantage clé est qu'il détecte automatiquement 
                le nombre de zones et identifie les points isolés comme "bruit".

                **Paramètres importants:**
                - **Distance max (eps):** Distance maximale (en mètres) entre deux points pour qu'ils soient considérés comme voisins.
                - **Points min:** Nombre minimum de points pour former une zone dense.

                **Interprétation:**
                - Plus la densité est élevée, plus la zone contient de mesures sur une petite surface.
                - Les points classés comme "bruit" sont des mesures isolées qui ne font partie d'aucune zone dense.
                """)

                speed_summary = df_clustered.groupby('cluster')['speed_mbps'].agg([
                    ('Moyenne', 'mean'),
                    ('Min', 'min'),
                    ('Max', 'max'),
                    ('Écart-type', 'std')
                ]).reset_index()

                speed_summary = speed_summary.rename(columns={'cluster': 'Cluster'})
                speed_summary = speed_summary.sort_values('Cluster')

                speed_summary['Cluster'] = speed_summary['Cluster'].apply(lambda x: 'Bruit (-1)' if x == -1 else x)

                st.subheader("Résumé des Débits par Zone")
                st.dataframe(speed_summary.style.format({
                    'Moyenne': '{:.2f} Mbps',
                    'Min': '{:.2f} Mbps',
                    'Max': '{:.2f} Mbps',
                    'Écart-type': '{:.2f} Mbps'
                }))
                
                cluster_analysis = analyze_clusters(df_clustered)
                insights = generate_cluster_insights(cluster_analysis)
                
                st.header("Insights sur les Zones")
                for insight in insights:
                    st.markdown(f"- {insight}")
                
                st.header("Carte des Zones de Couverture")
                cluster_map = create_cluster_map(df_clustered, zoom_start=15)
                folium_static(cluster_map, width=1200, height=700)

        elif algorithm == "Voisinage à Liaison Itérative":

            if 'neighborhood_analysis_started' not in st.session_state:
                st.session_state.neighborhood_analysis_started = False
            
            if 'selected_reference_points' not in st.session_state:
                st.session_state.selected_reference_points = None
                
            if ref_point_method == "Sélection manuelle" and not st.session_state.neighborhood_analysis_started:
                st.header("Sélection manuelle des points de référence")
                
                selection_df = df_combined[['latitude', 'longitude', 'speed_mbps', 'source_file']].copy()
                selection_df = selection_df.reset_index().rename(columns={'index': 'id'})
                
                sort_option = st.selectbox(
                    "Trier les points par:",
                    ["Aucun tri", "Débit croissant", "Débit décroissant"]
                )
                
                if sort_option == "Débit croissant":
                    selection_df = selection_df.sort_values('speed_mbps')
                elif sort_option == "Débit décroissant":
                    selection_df = selection_df.sort_values('speed_mbps', ascending=False)
                
                st.subheader("Carte des points disponibles")
                
                m = folium.Map(
                    location=[selection_df['latitude'].mean(), selection_df['longitude'].mean()],
                    zoom_start=15
                )
                
                for idx, row in selection_df.iterrows():
                    min_speed = selection_df['speed_mbps'].min()
                    max_speed = selection_df['speed_mbps'].max()
                    speed_ratio = (row['speed_mbps'] - min_speed) / max(max_speed - min_speed, 0.001)
                    color = f'#{int(255 * (1 - speed_ratio)):02x}{int(255 * speed_ratio):02x}00'
                    
                    folium.CircleMarker(
                        location=[row['latitude'], row['longitude']],
                        radius=5,
                        fill=True,
                        fill_color=color,
                        color='black',
                        fill_opacity=0.7,
                        tooltip=f"ID: {row['id']}, Débit: {row['speed_mbps']:.2f} Mbps"
                    ).add_to(m)
                
                folium_static(m, width=1200, height=500)
                
                st.subheader("Sélection des points")
                st.write(f"Choisissez jusqu'à {num_ref_points} points comme références pour l'analyse de voisinage.")
                
                with st.expander("Voir tous les points disponibles", expanded=True):
                    search_id = st.number_input("Rechercher un ID spécifique:", min_value=0, max_value=len(selection_df)-1, value=0)
                    
                    if search_id > 0:
                        st.dataframe(selection_df[selection_df['id'] == search_id], height=100)
                    else:
                        st.dataframe(selection_df, height=300)
                
                selected_ids = st.multiselect(
                    "Sélectionnez des IDs de points comme références:",
                    options=selection_df['id'].tolist(),
                    max_selections=num_ref_points,
                    help="Vous pouvez voir les IDs dans le tableau ci-dessus ou en survolant les points sur la carte."
                )
                
                if selected_ids:
                    selected_points_df = selection_df[selection_df['id'].isin(selected_ids)]
                    
                    st.subheader("Points sélectionnés")
                    st.dataframe(selected_points_df)
                    
                    reference_points = selected_points_df[['latitude', 'longitude']].values
                    
                    st.success(f"{len(reference_points)} points ont été sélectionnés comme références.")
                    
                    if st.button("Lancer l'analyse de voisinage avec ces points"):
                        st.session_state.selected_reference_points = reference_points
                        st.session_state.neighborhood_analysis_started = True
                        st.rerun()

                    else:
                        st.info("Cliquez sur 'Lancer l'analyse' quand vous êtes prêt.")
                else:
                    st.warning("Veuillez sélectionner au moins un point de référence.")
            
            if (ref_point_method != "Sélection manuelle") or st.session_state.neighborhood_analysis_started:
                with st.spinner("Application de l'algorithme de voisinage à liaison itérative..."):
                    if ref_point_method == "Sélection manuelle" and st.session_state.selected_reference_points is not None:
                        reference_points = st.session_state.selected_reference_points
                        st.success(f"Analyse lancée avec {len(reference_points)} points de référence sélectionnés manuellement.")
                    elif ref_point_method == "Aléatoire":
                        random_indices = np.random.choice(len(df_combined), size=num_ref_points, replace=False)
                        reference_points = df_combined.iloc[random_indices][['latitude', 'longitude']].values
                        
                        st.info(f"{num_ref_points} points de référence aléatoires ont été sélectionnés.")
                    elif ref_point_method == "Points à faible débit":
                        threshold = np.percentile(df_combined['speed_mbps'], threshold_percentile)
                        low_speed_points = df_combined[df_combined['speed_mbps'] <= threshold]
                        
                        if len(low_speed_points) >= num_ref_points:
                            selected_points = low_speed_points.nsmallest(num_ref_points, 'speed_mbps')
                            reference_points = selected_points[['latitude', 'longitude']].values
                            
                            st.info(f"{num_ref_points} points avec le débit le plus faible ont été sélectionnés "
                                f"(< {threshold:.2f} Mbps, percentile {threshold_percentile}).")
                        else:
                            st.warning(f"Pas assez de points à faible débit. Utilisation de {len(low_speed_points)} points.")
                            reference_points = low_speed_points[['latitude', 'longitude']].values
                    elif ref_point_method == "Points à haut débit":
                        threshold = np.percentile(df_combined['speed_mbps'], 100 - threshold_percentile)
                        high_speed_points = df_combined[df_combined['speed_mbps'] >= threshold]
                        
                        if len(high_speed_points) >= num_ref_points:
                            selected_points = high_speed_points.nlargest(num_ref_points, 'speed_mbps')
                            reference_points = selected_points[['latitude', 'longitude']].values
                            
                            st.info(f"{num_ref_points} points avec le débit le plus élevé ont été sélectionnés "
                                f"(> {threshold:.2f} Mbps, percentile {100-threshold_percentile}).")
                        else:
                            st.warning(f"Pas assez de points à haut débit. Utilisation de {len(high_speed_points)} points.")
                            reference_points = high_speed_points[['latitude', 'longitude']].values
                            
                    df_neighborhoods = perform_iterative_neighborhood_fixed(
                        df_combined, 
                        k=k_neighbors, 
                        linkage_method=linkage_method,
                        reference_points=reference_points
                    )
                    
                    n_neighborhoods = len(df_neighborhoods[df_neighborhoods['neighborhood'] >= 0]['neighborhood'].unique())
                    st.success(f"{n_neighborhoods} voisinages ont été créés avec {k_neighbors} voisins chacun.")
                    
                with st.spinner("Analyse des voisinages..."):
                    neighborhood_analysis = analyze_neighborhoods_improved(df_neighborhoods)
                    insights = generate_neighborhood_insights_improved(neighborhood_analysis)
                    
                    st.header("Insights sur les Voisinages")
                    for insight in insights:
                        st.markdown(f"- {insight}")
                    
                    st.header("Statistiques détaillées par voisinage")
                    
                    neighborhood_stats = []
                    for neigh_id, info in neighborhood_analysis['neighborhoods'].items():
                        if 'ref_point' in info and info['ref_point']:
                            ref_lat = info['ref_point']['lat']
                            ref_lon = info['ref_point']['lon']
                            ref_speed = info['ref_point']['speed']
                        else:
                            ref_lat, ref_lon, ref_speed = 'N/A', 'N/A', 'N/A'
                            
                        neighborhood_stats.append({
                            'Voisinage': neigh_id,
                            'Points': info['size'],
                            'Débit Moyen (Mbps)': info['avg_speed'],
                            'Écart-Type (Mbps)': info['std_speed'],
                            'Débit Min (Mbps)': info['min_speed'],
                            'Débit Max (Mbps)': info['max_speed'],
                            'Dispersion (m)': info.get('dispersion_meters', 0),
                            'Point Réf. Lat': ref_lat,
                            'Point Réf. Lon': ref_lon,
                            'Point Réf. Débit': ref_speed
                        })
                    
                    if neighborhood_stats:
                        stats_df = pd.DataFrame(neighborhood_stats)
                        st.dataframe(stats_df.style.format({
                            'Débit Moyen (Mbps)': '{:.2f}',
                            'Écart-Type (Mbps)': '{:.2f}',
                            'Débit Min (Mbps)': '{:.2f}',
                            'Débit Max (Mbps)': '{:.2f}',
                            'Dispersion (m)': '{:.0f}',
                            'Point Réf. Débit': '{:.2f}' if isinstance(stats_df['Point Réf. Débit'].iloc[0], float) else '{}'
                        }))
                    else:
                        st.write("Aucun voisinage trouvé avec les paramètres actuels.")
                
                st.header("Carte des Voisinages")
                neighborhood_map = create_neighborhood_map_fixed(df_neighborhoods, zoom_start=15)
                folium_static(neighborhood_map, width=1200, height=700)
                
                if ref_point_method == "Sélection manuelle" and st.button("Sélectionner d'autres points de référence"):
                    st.session_state.neighborhood_analysis_started = False
                    st.session_state.selected_reference_points = None
                    st.rerun()
                
                with st.expander("Explication de l'algorithme de voisinage à liaison itérative"):
                    st.markdown("""
                    ### Principe de l'algorithme
                    
                    L'algorithme de voisinage à liaison itérative est une alternative à la méthode des k plus proches voisins classique.
                    
                    **Fonctionnement :**
                    1. On commence par un point de référence X (V0 = {X})
                    2. Le premier voisin Y1 est le point le plus proche de V0, formant V1 = {X, Y1}
                    3. Le deuxième voisin Y2 est le point le plus proche de V1, formant V2 = {X, Y1, Y2}
                    4. Et ainsi de suite jusqu'au k-ième voisin
                    
                    **Méthodes de liaison :**
                    - **Simple (minimale)** : distance minimale entre un point candidat et n'importe quel point du voisinage actuel
                    - **Complète (maximale)** : distance maximale entre un point candidat et n'importe quel point du voisinage actuel
                    - **Moyenne** : distance moyenne entre un point candidat et tous les points du voisinage actuel
                    
                    **Avantages :**
                    - Cette méthode permet de capturer des voisinages plus structurés et cohérents que la simple distance euclidienne
                    - Elle prend en compte l'évolution du voisinage pendant sa construction
                    - Elle peut révéler des relations spatiales intéressantes dans les données qui ne sont pas visibles avec les méthodes classiques
                    """)
                
                if n_neighborhoods > 0:
                    st.header("Analyse de l'évolution des voisinages")
                    
                    selected_neigh = st.selectbox(
                        "Sélectionner un voisinage à analyser en détail:",
                        options=list(neighborhood_analysis['evolution'].keys()),
                        format_func=lambda x: f"Voisinage #{x}"
                    )
                    
                    if selected_neigh in neighborhood_analysis['evolution']:
                        evolution_data = neighborhood_analysis['evolution'][selected_neigh]
                        
                        if evolution_data:
                            evolution_df = pd.DataFrame(evolution_data)
                            
                            st.subheader("Évolution du débit en ajoutant des voisins")
                            
                            fig, ax = plt.subplots(figsize=(10, 6))
                            ax.plot(evolution_df['step'], evolution_df['neighborhood_avg_speed'], 'o-', label='Débit moyen du voisinage')
                            ax.plot(evolution_df['step'], evolution_df['new_point_speed'], 'x-', label='Débit du nouveau voisin')
                            
                            ref_speed = df_neighborhoods[
                                (df_neighborhoods['neighborhood'] == selected_neigh) & 
                                (df_neighborhoods[f'neighbor_rank_{selected_neigh}'] == 0)
                            ]['speed_mbps'].values[0]
                            ax.axhline(y=ref_speed, color='r', linestyle='--', label='Débit du point de référence')
                            
                            ax.set_xlabel('Étape (nombre de voisins)')
                            ax.set_ylabel('Débit (Mbps)')
                            ax.set_title(f'Évolution du débit pour le voisinage #{selected_neigh}')
                            ax.legend()
                            ax.grid(True, linestyle='--', alpha=0.7)
                            st.pyplot(fig)
                            
                            if 'max_distance' in evolution_df.columns and not evolution_df['max_distance'].isna().all():
                                st.subheader("Évolution de la distance en ajoutant des voisins")
                                
                                fig, ax = plt.subplots(figsize=(10, 6))
                                ax.plot(evolution_df['step'], evolution_df['max_distance'], 'o-', color='green')
                                ax.set_xlabel('Étape (nombre de voisins)')
                                ax.set_ylabel('Distance maximale (km)')
                                ax.set_title(f'Évolution de la distance pour le voisinage #{selected_neigh}')
                                ax.grid(True, linestyle='--', alpha=0.7)
                                st.pyplot(fig)
                            
                            st.subheader("Données détaillées de l'évolution")
                            display_evolution = evolution_df.copy()
                            display_evolution.columns = [
                                'Étape', 'Débit du nouveau voisin', 'Différence avec point réf.', 
                                'Débit moyen du voisinage', 'Écart-type du voisinage', 'Distance max'
                            ]
                            
                            st.dataframe(display_evolution.style.format({
                                'Étape': '{:.0f}',
                                'Débit du nouveau voisin': '{:.2f} Mbps',
                                'Différence avec point réf.': '{:.2f} Mbps',
                                'Débit moyen du voisinage': '{:.2f} Mbps',
                                'Écart-type du voisinage': '{:.2f} Mbps',
                                'Distance max': '{:.4f} km'
                            }))
                        else:
                            st.write("Pas de données d'évolution disponibles pour ce voisinage.")
                    else:
                        st.write("Aucun voisinage sélectionné.")
                
                st.write("---")
                st.subheader("Télécharger les Résultats")
                
                csv = df_neighborhoods.to_csv(index=False)
                st.download_button(
                    label="Télécharger les données de voisinage (CSV)",
                    data=csv,
                    file_name="neighborhood_data.csv",
                    mime="text/csv",
                )

        elif algorithm == "Détection d'Anomalies":
            with st.spinner("Détection des anomalies de débit..."):
                df_anomalies = detect_speed_anomalies(df_combined, contamination=contamination)
                
                anomaly_count = df_anomalies['is_anomaly'].sum()
                anomaly_percent = 100 * anomaly_count / len(df_anomalies)
                
                st.header("Résultats de la Détection d'Anomalies")
                st.write(f"Nombre d'anomalies détectées: {anomaly_count} ({anomaly_percent:.1f}% des points)")
                
                st.subheader("Top 10 Anomalies (les plus suspectes)")
                top_anomalies = df_anomalies[df_anomalies['is_anomaly']].sort_values('anomaly_score', ascending=False).head(10)
                
                display_anomalies = top_anomalies[['latitude', 'longitude', 'speed', 'speed_mbps', 'anomaly_score', 'source_file']].copy()
                display_anomalies.columns = ['Latitude', 'Longitude', 'Débit', 'Débit (Mbps)', 'Score d\'Anomalie', 'Fichier Source']
                
                st.dataframe(display_anomalies.style.format({
                    'Débit (Mbps)': '{:.2f}',
                    'Score d\'Anomalie': '{:.4f}'
                }))
                
                st.info("Les anomalies sont des points avec des valeurs de débit inhabituelles pour leur emplacement géographique. "
                        "Un score d'anomalie plus élevé indique une anomalie plus significative.")
                
                st.subheader("Carte des Anomalies Détectées")
                
                model, scaler = train_speed_prediction_model(df_combined)
                grid_df = predict_speed_for_grid(model, scaler, df_combined, grid_size=15)
                
                anomaly_map = create_prediction_map(df_combined, grid_df, df_anomalies, only_anomalies=True)
                folium_static(anomaly_map, width=1200, height=700)
                
                st.subheader("Statistiques des Anomalies")
                
                anomaly_speeds = df_anomalies[df_anomalies['is_anomaly']]['speed_mbps']
                normal_speeds = df_anomalies[~df_anomalies['is_anomaly']]['speed_mbps']
                
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Débit moyen (points normaux)", f"{normal_speeds.mean():.2f} Mbps")
                    st.metric("Écart-type (points normaux)", f"{normal_speeds.std():.2f} Mbps")
                
                with col2:
                    st.metric("Débit moyen (anomalies)", f"{anomaly_speeds.mean():.2f} Mbps")
                    st.metric("Écart-type (anomalies)", f"{anomaly_speeds.std():.2f} Mbps")
                
                st.subheader("Distribution des Débits: Normal vs Anomalies")
                
                fig, ax = plt.subplots(figsize=(10, 6))
                sns.histplot(normal_speeds, kde=True, color='blue', alpha=0.5, label='Points normaux', ax=ax)
                sns.histplot(anomaly_speeds, kde=True, color='red', alpha=0.5, label='Anomalies', ax=ax)
                ax.set_xlabel('Débit (Mbps)')
                ax.set_ylabel('Densité')
                ax.legend()
                st.pyplot(fig)
        
        elif algorithm == "Prédiction de Débit":
            with st.spinner("Entraînement du modèle de prédiction..."):
                model, scaler = train_speed_prediction_model(df_combined)
                
                grid_df = predict_speed_for_grid(model, scaler, df_combined, grid_size=grid_size)
                
                feature_importance = model.feature_importances_
                
                st.header("Carte de Prédiction du Débit")
                st.info("Cette carte montre les débits mesurés (cercles plus grands) et les prédictions du modèle (points plus petits et semi-transparents) "
                        "sur une grille couvrant la zone. Les zones vertes indiquent un débit élevé, les zones rouges un débit faible.")
                
                prediction_map = create_prediction_map(df_combined, grid_df)
                folium_static(prediction_map, width=1200, height=700)
                
                st.subheader("Informations sur le Modèle de Prédiction")
                
                from sklearn.model_selection import train_test_split
                from sklearn.metrics import mean_squared_error, r2_score
                
                X = df_combined[['latitude', 'longitude']].values
                y = df_combined['speed_mbps'].values
                
                X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
                X_train_scaled = scaler.transform(X_train)
                X_test_scaled = scaler.transform(X_test)
                
                test_model = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42)
                test_model.fit(X_train_scaled, y_train)
                
                y_pred = test_model.predict(X_test_scaled)
                
                mse = mean_squared_error(y_test, y_pred)
                rmse = np.sqrt(mse)
                r2 = r2_score(y_test, y_pred)
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Erreur Quadratique Moyenne", f"{mse:.4f}")
                col2.metric("Racine de l'EQM", f"{rmse:.2f} Mbps")
                col3.metric("Coefficient R²", f"{r2:.4f}")
                
                st.write("**Interprétation:**")
                st.write(f"- Un R² de {r2:.2f} signifie que le modèle explique environ {r2*100:.0f}% de la variance dans les débits.")
                st.write(f"- La REQM de {rmse:.2f} Mbps représente l'erreur moyenne de prédiction.")
                
                st.subheader("Valeurs Prédites vs Valeurs Réelles")
                
                fig, ax = plt.subplots(figsize=(8, 8))
                ax.scatter(y_test, y_pred, alpha=0.5)
                ax.plot([y.min(), y.max()], [y.min(), y.max()], 'k--', lw=2)
                ax.set_xlabel('Débit Réel (Mbps)')
                ax.set_ylabel('Débit Prédit (Mbps)')
                ax.set_title('Prédictions vs Valeurs Réelles')
                st.pyplot(fig)
                
                st.subheader("Zones d'Importance pour le Débit")
                st.write("Plus une zone est foncée, plus elle a d'influence sur la prédiction du débit.")

        elif algorithm == "Analyse Temporelle":
            if 'datetime' not in df_combined.columns:
                st.error("Les données ne contiennent pas d'information temporelle pour l'analyse.")
            else:
                with st.spinner("Analyse des tendances temporelles..."):
                    df_combined['datetime'] = pd.to_datetime(df_combined['datetime'])
                    
                    time_analysis = analyze_time_patterns(df_combined)
                    
                    st.header("Analyse des Tendances Temporelles")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Heure de pointe (meilleur débit)", 
                                 f"{time_analysis['peak_hour']}:00", 
                                 f"{time_analysis['peak_speed']:.2f} Mbps")
                    
                    with col2:
                        st.metric("Heure creuse (débit le plus bas)", 
                                 f"{time_analysis['low_hour']}:00", 
                                 f"{time_analysis['low_speed']:.2f} Mbps")
                    
                    st.subheader("Tendance des Débits par Heure")
                    
                    hour_labels = [f"{h:02d}h" for h in time_analysis['hourly_avg']['hour']]
                    
                    fig, ax = plt.subplots(figsize=(12, 6))
                    ax.bar(hour_labels, time_analysis['hourly_avg']['speed_mbps'], color='skyblue')
                    ax.set_xlabel('Heure de la journée')
                    ax.set_ylabel('Débit moyen (Mbps)')
                    ax.set_title('Débit moyen par heure de la journée')
                    plt.xticks(rotation=45)
                    st.pyplot(fig)
                    
                    if len(time_analysis['day_of_week_avg']) > 1:
                        st.subheader("Tendance des Débits par Jour de la Semaine")
                        
                        day_map = {0: 'Lundi', 1: 'Mardi', 2: 'Mercredi', 3: 'Jeudi', 
                                  4: 'Vendredi', 5: 'Samedi', 6: 'Dimanche'}
                        
                        day_data = time_analysis['day_of_week_avg'].copy()
                        day_data['day_name'] = day_data['day_of_week'].map(day_map)
                        
                        fig, ax = plt.subplots(figsize=(10, 6))
                        ax.bar(day_data['day_name'], day_data['speed_mbps'], color='lightgreen')
                        ax.set_xlabel('Jour de la semaine')
                        ax.set_ylabel('Débit moyen (Mbps)')
                        ax.set_title('Débit moyen par jour de la semaine')
                        st.pyplot(fig)
                    
                    st.subheader("Évolution du Débit au Fil du Temps")
                    
                    time_series_df = df_combined.sort_values('datetime').copy()
                    time_series_df['date_rounded'] = time_series_df['datetime'].dt.floor('H')
                    
                    hourly_series = time_series_df.groupby('date_rounded')['speed_mbps'].mean().reset_index()
                    
                    fig, ax = plt.subplots(figsize=(12, 6))
                    ax.plot(hourly_series['date_rounded'], hourly_series['speed_mbps'], marker='o', linestyle='-')
                    ax.set_xlabel('Date et Heure')
                    ax.set_ylabel('Débit moyen (Mbps)')
                    ax.set_title('Évolution du débit au fil du temps')
                    fig.autofmt_xdate()
                    st.pyplot(fig)
                    
                    st.subheader("Conclusions et Recommandations")
                    
                    time_insights = []
                    
                    peak_diff = time_analysis['peak_speed'] - time_analysis['low_speed']
                    if peak_diff > 0.5:
                        time_insights.append(f"Le débit est significativement meilleur à {time_analysis['peak_hour']}h " 
                                           f"qu'à {time_analysis['low_hour']}h (différence de {peak_diff:.2f} Mbps).")
                    
                    peak_period = []
                    low_period = []
                    
                    hourly_data = time_analysis['hourly_avg']
                    avg_speed = hourly_data['speed_mbps'].mean()
                    
                    for _, row in hourly_data.iterrows():
                        if row['speed_mbps'] > avg_speed * 1.1:
                            peak_period.append(int(row['hour']))
                        elif row['speed_mbps'] < avg_speed * 0.9:
                            low_period.append(int(row['hour']))
                    
                    def format_hour_ranges(hours):
                        if not hours:
                            return "aucune période spécifique"
                        
                        hours.sort()
                        ranges = []
                        start = hours[0]
                        end = hours[0]
                        
                        for i in range(1, len(hours)):
                            if hours[i] == end + 1:
                                end = hours[i]
                            else:
                                if start == end:
                                    ranges.append(f"{start}h")
                                else:
                                    ranges.append(f"{start}h-{end}h")
                                start = end = hours[i]
                        
                        if start == end:
                            ranges.append(f"{start}h")
                        else:
                            ranges.append(f"{start}h-{end}h")
                        
                        return ", ".join(ranges)
                    
                    peak_range = format_hour_ranges(peak_period)
                    low_range = format_hour_ranges(low_period)
                    
                    if peak_period:
                        time_insights.append(f"Les meilleures périodes pour un débit optimal sont: {peak_range}.")
                    
                    if low_period:
                        time_insights.append(f"Les périodes à éviter en raison d'un débit plus faible sont: {low_range}.")
                    
                    for insight in time_insights:
                        st.markdown(f"- {insight}")
                    
                    if not time_insights:
                        st.write("Pas de tendance temporelle significative détectée dans les données.")
        
        st.write("---")
        st.subheader("Télécharger les Résultats")
        
        if algorithm == "K-Means (Groupes de mesures)":
            csv = df_clustered.to_csv(index=False)
            st.download_button(
                label="Télécharger les données clusterisées (CSV)",
                data=csv,
                file_name="clusters_data.csv",
                mime="text/csv",
            )
        elif algorithm == "DBSCAN (Zones de couverture)":
            csv = df_clustered.to_csv(index=False)
            st.download_button(
                label="Télécharger les données zonées (CSV)",
                data=csv,
                file_name="zones_data.csv",
                mime="text/csv",
            )

        elif algorithm == "Détection d'Anomalies":
            csv = df_anomalies.to_csv(index=False)
            st.download_button(
                label="Télécharger les données avec flags d'anomalies (CSV)",
                data=csv,
                file_name="anomalies_data.csv",
                mime="text/csv",
            )
        elif algorithm == "Prédiction de Débit":
            csv = grid_df.to_csv(index=False)
            st.download_button(
                label="Télécharger la grille de prédiction (CSV)",
                data=csv,
                file_name="speed_predictions.csv",
                mime="text/csv",
            )
