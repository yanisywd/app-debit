# Network Speed Monitoring and Analysis System

A comprehensive solution for monitoring, visualizing, and analyzing network performance data with real-time capabilities and AI-powered insights.

## 📱 Components

This project consists of two integrated applications:

- **iOS Mobile App**: Collects real-time network speed measurements with GPS coordinates
- **Streamlit Web App**: Analyzes and visualizes the collected data using advanced AI algorithms

## ✨ Key Features

### iOS Application
- Real-time network speed testing
- GPS location tracking and mapping
- Local storage of measurement sessions
- CSV export functionality
- MQTT real-time data transmission
- Visualization of speed data on interactive maps

### Streamlit Dashboard
- Real-time data reception via MQTT
- CSV file import/export
- Interactive maps with color-coded speed indicators
- Advanced analysis using AI algorithms:
  - K-Means and DBSCAN clustering
  - Anomaly detection
  - Speed prediction for unmeasured areas
  - Temporal pattern analysis
  - Iterative neighborhood analysis

## 🔗 Data Flow

The applications communicate through:
- MQTT protocol for real-time data transmission
- Standardized CSV format for asynchronous data exchange

## 🛠️ Technologies

- **iOS App**: Swift, SwiftUI, MapKit, CoreLocation, CocoaMQTT
- **Analytics App**: Python, Streamlit, Pandas, Scikit-learn, Folium, Matplotlib

## 📊 Advanced Analysis

The system provides multiple AI-based analytical capabilities:
- Identification of network coverage zones
- Detection of performance anomalies
- Prediction of network speeds in unmeasured areas
- Temporal pattern recognition
- Geographic clustering of measurement points

## 📝 How to Use

1. Use the iOS app to collect network performance data in different locations
2. Either transmit data in real-time via MQTT or export as CSV
3. Import the data into the Streamlit application for analysis
4. Explore insights through interactive visualizations and AI-powered analytics

---

*Developed by Yanis Yahia Ouahmed as part of a Master's program at Université de Reims Champagne-Ardenne*
