import SwiftUI
import Network
import CoreTelephony
import Foundation
import CoreLocation
import MapKit
import Charts

import CocoaMQTT

// MARK: - MQTT Constants
let BROKER_IP   = "194.57.103.203"
let BROKER_PORT = 1883
let TOPIC       = "vehicule/speed"

// MARK: - Models

struct SpeedRecord: Identifiable, Codable {
    let id: UUID
    var name: String
    let date: Date
    var dataPoints: [SpeedDataPoint]
    
    var averageSpeed: Double?
    var standardDeviation: Double?
    
    mutating func calculateStats() {
        guard !dataPoints.isEmpty else {
            averageSpeed = nil
            standardDeviation = nil
            return
        }
        let speeds = dataPoints.compactMap {
            Double($0.speed.replacingOccurrences(of: " Mbps", with: ""))
        }
        let n = Double(speeds.count)
        let sum = speeds.reduce(0, +)
        averageSpeed = sum / n
        
        let sumSq = speeds.map { pow($0 - (averageSpeed ?? 0), 2) }.reduce(0, +)
        standardDeviation = sqrt(sumSq / n)
    }
    
    func bestDataPoint() -> SpeedDataPoint? {
        dataPoints.max(by: { parseSpeed($0.speed) < parseSpeed($1.speed) })
    }
    
    private func parseSpeed(_ speed: String) -> Double {
        Double(speed.replacingOccurrences(of: " Mbps", with: "")) ?? 0.0
    }
}

struct SpeedDataPoint: Identifiable, Codable {
    let id = UUID()
    let time: Date
    let speed: String
    let latitude: Double?
    let longitude: Double?
    
    var coordinate: CLLocationCoordinate2D? {
        guard let lat = latitude, let lon = longitude else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lon)
    }
}

// For grouping data by minute in the histogram
struct AggregatedData: Identifiable {
    let id = UUID()
    let minute: Date
    let avgSpeed: Double
}

// MARK: - Chart View

struct SpeedHistogramView: View {
    let dataPoints: [SpeedDataPoint]
    
    var body: some View {
        if #available(iOS 16.0, *) {
            let aggregatedData = aggregateByMinute(dataPoints)
            if aggregatedData.isEmpty {
                Text("Aucune donnée pour la période sélectionnée.")
                    .foregroundColor(.gray)
                    .padding()
            } else {
                ScrollView(.horizontal) {
                    Chart {
                        ForEach(aggregatedData) { data in
                            BarMark(
                                x: .value("Minute", data.minute),
                                y: .value("Débit (Mbps)", data.avgSpeed)
                            )
                            .foregroundStyle(
                                LinearGradient(
                                    gradient: Gradient(colors: [.purple.opacity(0.6), .purple]),
                                    startPoint: .top,
                                    endPoint: .bottom
                                )
                            )
                            .cornerRadius(3)
                            .annotation(position: .top) {
                                Text(String(format: "%.2f", data.avgSpeed))
                                    .font(.caption)
                                    .foregroundColor(.white)
                            }
                        }
                    }
                    .chartYAxis { AxisMarks(position: .leading) }
                    .chartXAxis {
                        AxisMarks(
                            values: aggregatedData.indices.compactMap { idx in
                                idx % 2 == 0 ? aggregatedData[idx].minute : nil
                            }
                        ) { date in
                            AxisValueLabel(format: .dateTime.hour().minute(), centered: true)
                            AxisGridLine()
                        }
                    }
                    .chartYAxisLabel("Débit (Mbps)", position: .leading)
                    .chartXAxisLabel("Heure", position: .bottom)
                    .frame(
                        width: max(CGFloat(aggregatedData.count) * 35, UIScreen.main.bounds.width),
                        height: 300
                    )
                }
            }
        } else {
            Text("Histogramme non supporté sur iOS < 16.")
                .foregroundColor(.gray)
        }
    }
    
    private func aggregateByMinute(_ dataPoints: [SpeedDataPoint]) -> [AggregatedData] {
        guard !dataPoints.isEmpty else { return [] }
        var minuteDict: [Date: [Double]] = [:]
        let calendar = Calendar.current
        
        dataPoints.forEach { dp in
            let speedVal = Double(dp.speed.replacingOccurrences(of: " Mbps", with: "")) ?? 0.0
            let comps = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: dp.time)
            if let truncatedDate = calendar.date(from: comps) {
                minuteDict[truncatedDate, default: []].append(speedVal)
            }
        }
        
        return minuteDict.map { (key, values) in
            let avg = values.reduce(0, +) / Double(values.count)
            return AggregatedData(minute: key, avgSpeed: avg)
        }
        .sorted { $0.minute < $1.minute }
    }
}

// MARK: - ViewModel (NetworkMonitor)

class NetworkMonitor: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published var speed: String = "Calcul en cours..."
    @Published var connectionType: String = "Inconnu"
    @Published var recordings: [SpeedRecord] = []
    @Published var globalRecord: SpeedRecord = SpeedRecord(
        id: UUID(),
        name: "Fichier global",
        date: Date(),
        dataPoints: []
    )
    
    @Published var userLocation: CLLocation? = nil
    
    private var isRecording = false
    private var currentRecord: SpeedRecord? = nil
    
    private var monitor: NWPathMonitor
    private var queue = DispatchQueue(label: "NetworkMonitor")
    private var globalTimer: Timer?
    
    private let locationManager = CLLocationManager()
    
    private var mqttClient: CocoaMQTT?
    
    override init() {
        monitor = NWPathMonitor()
        super.init()
        
        locationManager.delegate = self
        locationManager.requestWhenInUseAuthorization()
        locationManager.startUpdatingLocation()
        
        loadAllRecordings()
        loadGlobalRecord()
        
        monitor.start(queue: queue)
        monitor.pathUpdateHandler = { path in
            DispatchQueue.main.async {
                self.updateConnectionType(path)
            }
        }
        
        globalTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { _ in
            self.testNetworkSpeed()
        }
    }
    
    func startRecording() {
        isRecording = true
        currentRecord = SpeedRecord(
            id: UUID(),
            name: "Sans nom",
            date: Date(),
            dataPoints: []
        )
        locationManager.startUpdatingLocation()
        connectToMQTT()
    }
    
    func stopRecording() {
        isRecording = false
        disconnectFromMQTT()
    }
    
    func finishRecording(name: String) {
        guard var record = currentRecord else { return }
        record.name = name.isEmpty ? "Enregistrement du \(Date())" : name
        record.calculateStats()
        
        recordings.append(record)
        saveAllRecordings()
        
        updateGlobalRecord(with: record)
        
        currentRecord = nil
    }
    
    func deleteRecordings(at offsets: IndexSet) {
        recordings.remove(atOffsets: offsets)
        saveAllRecordings()
    }
    
    private func updateConnectionType(_ path: NWPath) {
        if path.usesInterfaceType(.wifi) {
            connectionType = "Wi-Fi"
        } else if path.usesInterfaceType(.cellular) {
            connectionType = getCellularType()
        } else {
            connectionType = "Inconnu"
        }
    }
    
    private func getCellularType() -> String {
        let networkInfo = CTTelephonyNetworkInfo()
        if let currentRadioTech = networkInfo.serviceCurrentRadioAccessTechnology?.values.first {
            switch currentRadioTech {
            case CTRadioAccessTechnologyLTE:
                return "4G LTE"
            case CTRadioAccessTechnologyWCDMA,
                 CTRadioAccessTechnologyHSDPA,
                 CTRadioAccessTechnologyHSUPA:
                return "3G"
            case CTRadioAccessTechnologyGPRS,
                 CTRadioAccessTechnologyEdge:
                return "2G"
            case CTRadioAccessTechnologyNRNSA,
                 CTRadioAccessTechnologyNR:
                return "5G"
            default:
                return "Cellulaire"
            }
        }
        return "Cellulaire"
    }
    
    private func testNetworkSpeed() {
        let url = URL(string: "https://www.google.com")!
        let startTime = Date()
        let task = URLSession.shared.dataTask(with: url) { data, _, error in
            guard error == nil, let data = data else {
                DispatchQueue.main.async {
                    self.speed = "Erreur de mesure"
                }
                return
            }
            let elapsed = Date().timeIntervalSince(startTime)
            let mbps = (Double(data.count) / elapsed) / 1_000_000 * 8
            let speedStr = String(format: "%.2f Mbps", mbps)
            DispatchQueue.main.async {
                self.speed = speedStr
                
                if self.isRecording, var record = self.currentRecord {
                    let lat = self.userLocation?.coordinate.latitude
                    let lon = self.userLocation?.coordinate.longitude
                    let dp = SpeedDataPoint(time: Date(), speed: speedStr, latitude: lat, longitude: lon)
                    record.dataPoints.append(dp)
                    self.currentRecord = record
                    self.publishDataToMQTT(speedString: speedStr, lat: lat, lon: lon)
                }
            }
        }
        task.resume()
    }
    
    // MARK: - Location Manager Delegate
    
    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let loc = locations.last else { return }
        userLocation = loc
    }
    
    // MARK: - Persistence
    
    private func saveAllRecordings() {
        do {
            let data = try JSONEncoder().encode(recordings)
            UserDefaults.standard.set(data, forKey: "ALL_SPEED_RECORDINGS")
        } catch {
            print("Erreur d'encodage: \(error)")
        }
    }
    
    private func loadAllRecordings() {
        guard let savedData = UserDefaults.standard.data(forKey: "ALL_SPEED_RECORDINGS") else { return }
        do {
            let loaded = try JSONDecoder().decode([SpeedRecord].self, from: savedData)
            recordings = loaded
        } catch {
            print("Erreur de décodage: \(error)")
        }
    }
    
    private func saveGlobalRecord() {
        do {
            let data = try JSONEncoder().encode(globalRecord)
            UserDefaults.standard.set(data, forKey: "GLOBAL_SPEED_RECORD")
        } catch {
            print("Erreur d'encodage (global): \(error)")
        }
    }
    
    private func loadGlobalRecord() {
        guard let savedData = UserDefaults.standard.data(forKey: "GLOBAL_SPEED_RECORD") else { return }
        do {
            let loadedGlobal = try JSONDecoder().decode(SpeedRecord.self, from: savedData)
            globalRecord = loadedGlobal
        } catch {
            print("Erreur de décodage (global): \(error)")
        }
    }
    
    private func updateGlobalRecord(with newRecord: SpeedRecord) {
        globalRecord.dataPoints.append(contentsOf: newRecord.dataPoints)
        globalRecord.calculateStats()
        saveGlobalRecord()
    }
    
    // MARK: - MQTT
    
    private func connectToMQTT() {
        let clientID = "iOS-SpeedApp-\(UUID().uuidString.prefix(6))"
        let mqtt = CocoaMQTT(clientID: clientID, host: BROKER_IP, port: UInt16(BROKER_PORT))
        mqtt.keepAlive = 60
        mqtt.autoReconnect = true
        mqtt.autoReconnectTimeInterval = 5
        mqtt.allowUntrustCACertificate = true
        
        mqtt.delegate = self
        mqttClient = mqtt
        mqtt.connect()
    }
    
    private func publishDataToMQTT(speedString: String, lat: Double?, lon: Double?) {
        guard let mqtt = mqttClient, mqtt.connState == .connected else { return }
        let payload: [String: Any] = [
            "speed": speedString,
            "latitude": lat ?? 0.0,
            "longitude": lon ?? 0.0,
            "timestamp": Date().timeIntervalSince1970
        ]
        do {
            let jsonData = try JSONSerialization.data(withJSONObject: payload, options: [])
            let jsonStr = String(data: jsonData, encoding: .utf8) ?? ""
            mqtt.publish(TOPIC, withString: jsonStr, qos: .qos1)
        } catch {
            print("Error serializing MQTT payload: \(error)")
        }
    }
    
    private func disconnectFromMQTT() {
        mqttClient?.disconnect()
        mqttClient = nil
    }
}

extension NetworkMonitor: CocoaMQTTDelegate {
    func mqtt(_ mqtt: CocoaMQTT, didConnectAck ack: CocoaMQTTConnAck) {
        print("MQTT connected with ack: \(ack)")
    }
    
    func mqtt(_ mqtt: CocoaMQTT, didStateChangeTo state: CocoaMQTTConnState) {
        print("MQTT state changed to: \(state)")
    }
    
    func mqtt(_ mqtt: CocoaMQTT, didReceive trust: SecTrust, host: String) -> Bool {
        true
    }
    
    func mqtt(_ mqtt: CocoaMQTT, didPublishMessage message: CocoaMQTTMessage, id: UInt16) {
        print("MQTT didPublishMessage to topic \(message.topic)")
    }
    
    func mqtt(_ mqtt: CocoaMQTT, didPublishAck id: UInt16) {
        print("MQTT didPublishAck: \(id)")
    }
    
    func mqtt(_ mqtt: CocoaMQTT, didReceiveMessage message: CocoaMQTTMessage, id: UInt16) {
        print("Received MQTT message on topic \(message.topic): \(message.string ?? "")")
    }
    
    func mqtt(_ mqtt: CocoaMQTT, didSubscribeTopics success: NSDictionary, failed: [String]) {
        print("MQTT subscribed to topics: \(success.allKeys)")
    }
    
    func mqtt(_ mqtt: CocoaMQTT, didUnsubscribeTopics topics: [String]) {
        print("MQTT unsubscribed from topics: \(topics)")
    }
    
    func mqttDidPing(_ mqtt: CocoaMQTT) {
        print("MQTT did Ping")
    }
    
    func mqttDidReceivePong(_ mqtt: CocoaMQTT) {
        print("MQTT did Receive Pong")
    }
    
    func mqttDidDisconnect(_ mqtt: CocoaMQTT, withError err: Error?) {
        print("MQTT disconnected: \(err?.localizedDescription ?? "no error")")
    }
}

// MARK: - NearbyBestMapView
struct NearbyBestMapView: UIViewRepresentable {
    
    let userLocation: CLLocation?
    let allDataPoints: [SpeedDataPoint]
    
    let distanceThreshold: Double = 2000.0
    let maxPoints: Int = 5
    
    func makeUIView(context: Context) -> MKMapView {
        let map = MKMapView()
        map.showsUserLocation = true
        map.isZoomEnabled = true
        map.isScrollEnabled = true
        map.delegate = context.coordinator
        return map
    }
    
    func updateUIView(_ uiView: MKMapView, context: Context) {
        uiView.removeAnnotations(uiView.annotations)
        
        guard let userLoc = userLocation else {
            return
        }
        
        let validPoints = allDataPoints.compactMap { dp -> (SpeedDataPoint, CLLocation) in
            guard let coord = dp.coordinate else { return (dp, CLLocation()) }
            return (dp, CLLocation(latitude: coord.latitude, longitude: coord.longitude))
        }
        
        let closePoints = validPoints.filter { tuple in
            let distance = tuple.1.distance(from: userLoc)
            return distance <= distanceThreshold
        }
        
        let sortedBySpeed = closePoints.sorted(by: { parseSpeed($0.0.speed) > parseSpeed($1.0.speed) })
        
        let topPoints = sortedBySpeed.prefix(maxPoints)
        
        for (dp, loc) in topPoints {
            let annotation = MKPointAnnotation()
            annotation.coordinate = loc.coordinate
            annotation.title = dp.speed
            annotation.subtitle = "Distance: \(Int(loc.distance(from: userLoc)))m"
            uiView.addAnnotation(annotation)
        }
        
        let region = MKCoordinateRegion(
            center: userLoc.coordinate,
            span: MKCoordinateSpan(latitudeDelta: 0.01, longitudeDelta: 0.01)
        )
        uiView.setRegion(region, animated: true)
    }
    
    func makeCoordinator() -> Coordinator {
        Coordinator()
    }
    
    class Coordinator: NSObject, MKMapViewDelegate {
        func mapView(_ mapView: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
            if annotation is MKUserLocation {
                return nil
            }
            let reuseID = "nearbyMapAnnotation"
            var annView = mapView.dequeueReusableAnnotationView(withIdentifier: reuseID) as? MKMarkerAnnotationView
            if annView == nil {
                annView = MKMarkerAnnotationView(annotation: annotation, reuseIdentifier: reuseID)
            }
            annView?.annotation = annotation
            annView?.markerTintColor = .green
            annView?.glyphImage = UIImage(systemName: "flame.fill")
            return annView
        }
    }
    
    private func parseSpeed(_ speedStr: String) -> Double {
        Double(speedStr.replacingOccurrences(of: " Mbps", with: "")) ?? 0.0
    }
}

// MARK: - GlobalMapView
struct GlobalMapView: UIViewRepresentable {
    let record: SpeedRecord
    
    func makeUIView(context: Context) -> MKMapView {
        let map = MKMapView()
        map.showsUserLocation = false
        map.isZoomEnabled = true
        map.isScrollEnabled = true
        map.delegate = context.coordinator
        return map
    }
    
    func updateUIView(_ uiView: MKMapView, context: Context) {
        uiView.removeOverlays(uiView.overlays)
        uiView.removeAnnotations(uiView.annotations)
        
        let coords = record.dataPoints.compactMap { $0.coordinate }
        guard !coords.isEmpty else { return }
        
        let polyline = MKPolyline(coordinates: coords, count: coords.count)
        uiView.addOverlay(polyline)
        
        let bestID = record.bestDataPoint()?.id
        
        for (index, dp) in record.dataPoints.enumerated() {
            if let c = dp.coordinate {
                let annotation = MKPointAnnotation()
                annotation.coordinate = c
                if dp.id == bestID {
                    annotation.title = "Meilleur débit"
                } else {
                    annotation.title = "Point #\(index + 1)"
                }
                annotation.subtitle = dp.speed
                uiView.addAnnotation(annotation)
            }
        }
        
        let rect = polyline.boundingMapRect
        uiView.setVisibleMapRect(rect, edgePadding: .init(top: 40, left: 40, bottom: 40, right: 40), animated: false)
    }
    
    func makeCoordinator() -> GlobalMapViewCoordinator {
        GlobalMapViewCoordinator()
    }
    
    class GlobalMapViewCoordinator: NSObject, MKMapViewDelegate {
        func mapView(_ mapView: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
            guard let poly = overlay as? MKPolyline else {
                return MKOverlayRenderer(overlay: overlay)
            }
            let renderer = MKPolylineRenderer(polyline: poly)
            renderer.strokeColor = .orange
            renderer.lineWidth = 3
            return renderer
        }
        
        func mapView(_ mapView: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
            if annotation is MKUserLocation { return nil }
            let reuseID = "globalMapAnnotation"
            var annView = mapView.dequeueReusableAnnotationView(withIdentifier: reuseID) as? MKMarkerAnnotationView
            if annView == nil {
                annView = MKMarkerAnnotationView(annotation: annotation, reuseIdentifier: reuseID)
            }
            annView?.annotation = annotation
            
            if annotation.title == "Meilleur débit" {
                annView?.glyphImage = UIImage(systemName: "star.fill")
                annView?.markerTintColor = .red
            } else {
                annView?.glyphImage = UIImage(systemName: "circle.fill")
                annView?.markerTintColor = .cyan
            }
            return annView
        }
    }
}

// MARK: - ContentView (Main UI)

struct ContentView: View {
    @StateObject private var networkMonitor = NetworkMonitor()
    @State private var isRecording = false
    @State private var showNameSheet = false
    @State private var newRecordingName = ""
    
    var body: some View {
        NavigationView {
            ZStack {
                LinearGradient(
                    gradient: Gradient(colors: [Color.black, Color.black.opacity(0.9)]),
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()
                
                ScrollView(showsIndicators: false) {
                    VStack(spacing: 15) {
                        
                        Text("Suivi du Débit")
                            .font(.largeTitle)
                            .foregroundColor(.white)
                            .bold()
                            .padding(.top, 15)
                        
                        VStack(spacing: 6) {
                            Text("Vitesse Actuelle")
                                .font(.subheadline)
                                .foregroundColor(.white.opacity(0.7))
                            
                            Text(networkMonitor.speed)
                                .font(.system(size: 34, weight: .bold))
                                .foregroundColor(.white)
                            
                            Text("Connexion: \(networkMonitor.connectionType)")
                                .font(.footnote)
                                .foregroundColor(.gray)
                        }
                        .padding(12)
                        .background(
                            RoundedRectangle(cornerRadius: 12)
                                .fill(Color.gray.opacity(0.2))
                        )
                        .padding(.horizontal)
                        
                        Button {
                            if isRecording {
                                networkMonitor.stopRecording()
                                showNameSheet = true
                            } else {
                                networkMonitor.startRecording()
                            }
                            isRecording.toggle()
                        } label: {
                            Text(isRecording ? "Arrêter" : "Démarrer")
                                .font(.headline)
                                .padding()
                                .frame(maxWidth: .infinity)
                                .background(
                                    LinearGradient(
                                        gradient: Gradient(colors: isRecording
                                                           ? [.red.opacity(0.7), .red]
                                                           : [.green.opacity(0.7), .green]),
                                        startPoint: .leading,
                                        endPoint: .trailing
                                    )
                                )
                                .foregroundColor(.white)
                                .cornerRadius(12)
                                .shadow(color: .black.opacity(0.3), radius: 5, x: 2, y: 4)
                        }
                        .padding(.horizontal)
                        
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Meilleurs débits autour de moi")
                                .font(.headline)
                                .foregroundColor(.white)
                            
                            if networkMonitor.userLocation == nil {
                                Text("Localisation non disponible.")
                                    .font(.footnote)
                                    .foregroundColor(.gray)
                            } else {
                                NearbyBestMapView(
                                    userLocation: networkMonitor.userLocation,
                                    allDataPoints: networkMonitor.globalRecord.dataPoints
                                )
                                .frame(height: 250)
                                .cornerRadius(12)
                            }
                        }
                        .padding()
                        .background(
                            RoundedRectangle(cornerRadius: 12)
                                .stroke(Color.white.opacity(0.3), lineWidth: 1)
                                .background(Color.black.opacity(0.2).cornerRadius(12))
                        )
                        .padding(.horizontal)
                        
                        VStack(alignment: .leading, spacing: 6) {
                            Text(networkMonitor.globalRecord.name.uppercased())
                                .font(.headline)
                                .foregroundColor(.white)
                            
                            if let avg = networkMonitor.globalRecord.averageSpeed {
                                Text(String(format: "Moyenne: %.2f Mbps", avg))
                                    .foregroundColor(.white)
                            }
                            if let std = networkMonitor.globalRecord.standardDeviation {
                                Text(String(format: "Écart type: %.2f Mbps", std))
                                    .foregroundColor(.white)
                            }
                            if let bestDP = networkMonitor.globalRecord.bestDataPoint() {
                                let best = Double(bestDP.speed.replacingOccurrences(of: " Mbps", with: "")) ?? 0.0
                                Text(String(format: "Meilleur débit: %.2f Mbps", best))
                                    .foregroundColor(.yellow)
                            } else {
                                Text("Aucune donnée")
                                    .foregroundColor(.gray)
                            }
                            
                            NavigationLink(destination: RecordingDetailView(record: networkMonitor.globalRecord)) {
                                Text("Détails du fichier global")
                                    .font(.footnote)
                                    .underline()
                                    .foregroundColor(.blue)
                            }
                        }
                        .padding()
                        .background(
                            RoundedRectangle(cornerRadius: 12)
                                .stroke(Color.blue, lineWidth: 1.2)
                                .background(Color.black.opacity(0.25).cornerRadius(12))
                        )
                        .padding(.horizontal)
                        
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Mes Enregistrements")
                                .font(.headline)
                                .foregroundColor(.white)
                            
                            if networkMonitor.recordings.isEmpty {
                                Text("Aucun enregistrement disponible.")
                                    .foregroundColor(.gray)
                                    .font(.footnote)
                            } else {
                                ForEach(networkMonitor.recordings) { record in
                                    NavigationLink(destination: RecordingDetailView(record: record)) {
                                        HStack {
                                            VStack(alignment: .leading, spacing: 2) {
                                                Text(record.name)
                                                    .foregroundColor(.white)
                                                Text("\(record.date, formatter: shortDateFormatter)")
                                                    .font(.caption)
                                                    .foregroundColor(.gray)
                                            }
                                            Spacer()
                                            Image(systemName: "chevron.right")
                                                .foregroundColor(.gray)
                                        }
                                        .padding(.vertical, 5)
                                    }
                                }
                                .onDelete { offsets in
                                    networkMonitor.deleteRecordings(at: offsets)
                                }
                            }
                        }
                        .padding()
                        .background(
                            RoundedRectangle(cornerRadius: 12)
                                .fill(Color.gray.opacity(0.15))
                        )
                        .padding(.horizontal)
                        .padding(.bottom, 40)
                    }
                }
            }
            .navigationBarTitle("Suivi du débit", displayMode: .inline)
            .sheet(isPresented: $showNameSheet, onDismiss: {
                networkMonitor.finishRecording(name: newRecordingName)
                newRecordingName = ""
            }) {
                VStack(spacing: 20) {
                    Text("Nom de l'enregistrement")
                        .font(.headline)
                        .foregroundColor(.white)
                    
                    TextField("Ex: Test du 7 février", text: $newRecordingName)
                        .textFieldStyle(RoundedBorderTextFieldStyle())
                        .padding()
                    
                    Button("Enregistrer") {
                        showNameSheet = false
                    }
                    .font(.title3)
                    .padding()
                    .background(Color.blue)
                    .foregroundColor(.white)
                    .cornerRadius(8)
                }
                .padding()
                .background(Color.black.edgesIgnoringSafeArea(.all))
            }
        }
    }
}

// MARK: - Detail View

struct RecordingDetailView: View {
    let record: SpeedRecord
    @State private var focusOnBest = false
    
    @State private var csvURL: URL? = nil
    
    private let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .none
        f.timeStyle = .medium
        return f
    }()
    
    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(record.name)
                        .font(.title2)
                        .bold()
                        .foregroundColor(.white)
                    
                    Text("Date: \(record.date, formatter: shortDateFormatter)")
                        .font(.subheadline)
                        .foregroundColor(.gray)
                    
                    if let avg = record.averageSpeed {
                        Text(String(format: "Moyenne: %.2f Mbps", avg))
                            .foregroundColor(.white)
                    }
                    if let std = record.standardDeviation {
                        Text(String(format: "Écart type: %.2f Mbps", std))
                            .foregroundColor(.white)
                    }
                    
                    if let bestDP = record.bestDataPoint() {
                        let bestVal = Double(bestDP.speed.replacingOccurrences(of: " Mbps", with: "")) ?? 0.0
                        Text(String(format: "Meilleur débit: %.2f Mbps", bestVal))
                            .foregroundColor(.yellow)
                        
                        Text("Enregistré à \(bestDP.time, formatter: shortDateFormatter)")
                            .font(.caption)
                            .foregroundColor(.gray)
                        
                        if let lat = bestDP.latitude, let lon = bestDP.longitude {
                            Text(String(format: "Localisation: %.4f, %.4f", lat, lon))
                                .font(.caption2)
                                .foregroundColor(.gray)
                        }
                    } else {
                        Text("Aucune donnée")
                            .foregroundColor(.gray)
                    }
                }
                .padding()
                .background(Color.gray.opacity(0.2))
                .cornerRadius(12)
                
                SpeedHistogramView(dataPoints: record.dataPoints)
                    .padding(.bottom, 10)
                
                if record.dataPoints.contains(where: { $0.coordinate != nil }) {
                    ZStack(alignment: .topTrailing) {
                        RecordingMapView(
                            dataPoints: record.dataPoints,
                            bestDataPoint: record.bestDataPoint(),
                            focusOnBestPoint: $focusOnBest
                        )
                        .frame(height: 300)
                        .cornerRadius(12)
                        
                        if record.bestDataPoint() != nil {
                            Button("Trouver le meilleur débit") {
                                focusOnBest = true
                            }
                            .padding(8)
                            .background(Color.white.opacity(0.8))
                            .cornerRadius(8)
                            .shadow(radius: 2)
                            .padding()
                        }
                    }
                } else {
                    Text("Pas de localisation disponible")
                        .foregroundColor(.gray)
                }
                
                VStack(alignment: .leading, spacing: 8) {
                    Text("Mesures (\(record.dataPoints.count))")
                        .font(.headline)
                        .foregroundColor(.white)
                    
                    ForEach(record.dataPoints) { dp in
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Heure: \(dp.time, formatter: dateFormatter)")
                                .font(.subheadline)
                                .foregroundColor(.white)
                            
                            Text("Débit: \(dp.speed)")
                                .foregroundColor(.white)
                            
                            if let lat = dp.latitude, let lon = dp.longitude {
                                Text(String(format: "Lat: %.4f, Lon: %.4f", lat, lon))
                                    .font(.caption)
                                    .foregroundColor(.gray)
                            } else {
                                Text("Localisation indisponible")
                                    .font(.caption)
                                    .foregroundColor(.gray)
                            }
                        }
                        .padding()
                        .background(Color.gray.opacity(0.2))
                        .cornerRadius(8)
                    }
                }
                
                Button(action: {
                    if let url = exportCSV(for: record) {
                        csvURL = url
                    }
                }) {
                    HStack {
                        Image(systemName: "square.and.arrow.up")
                        Text("Exporter CSV")
                    }
                    .padding()
                    .background(Color.blue)
                    .foregroundColor(.white)
                    .cornerRadius(8)
                }
                .padding(.top, 10)
            }
            .padding()
        }
        .background(Color.black.ignoresSafeArea())
        .navigationTitle("Détails")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $csvURL) { fileURL in
            ShareSheet(activityItems: [fileURL])
        }
    }
}

// MARK: - RecordingMapView

struct RecordingMapView: UIViewRepresentable {
    let dataPoints: [SpeedDataPoint]
    let bestDataPoint: SpeedDataPoint?
    @Binding var focusOnBestPoint: Bool
    
    func makeUIView(context: Context) -> MKMapView {
        let mapView = MKMapView()
        mapView.isZoomEnabled = true
        mapView.isScrollEnabled = true
        mapView.delegate = context.coordinator
        return mapView
    }
    
    func updateUIView(_ uiView: MKMapView, context: Context) {
        uiView.removeOverlays(uiView.overlays)
        uiView.removeAnnotations(uiView.annotations)
        
        let coords = dataPoints.compactMap { $0.coordinate }
        guard !coords.isEmpty else { return }
        
        let polyline = MKPolyline(coordinates: coords, count: coords.count)
        uiView.addOverlay(polyline)
        
        let bestID = bestDataPoint?.id
        
        for (index, dp) in dataPoints.enumerated() {
            if let c = dp.coordinate {
                let annotation = MKPointAnnotation()
                annotation.coordinate = c
                if dp.id == bestID {
                    annotation.title = "Meilleur débit"
                } else {
                    annotation.title = "Point #\(index + 1)"
                }
                annotation.subtitle = dp.speed
                uiView.addAnnotation(annotation)
            }
        }
        
        let rect = polyline.boundingMapRect
        uiView.setVisibleMapRect(rect, edgePadding: .init(top: 40, left: 40, bottom: 40, right: 40), animated: false)
        
        if focusOnBestPoint, let bestDP = bestDataPoint, let bestCoord = bestDP.coordinate {
            let region = MKCoordinateRegion(
                center: bestCoord,
                span: MKCoordinateSpan(latitudeDelta: 0.0005, longitudeDelta: 0.0005)
            )
            uiView.setRegion(region, animated: true)
            
            DispatchQueue.main.async {
                focusOnBestPoint = false
            }
        }
    }
    
    func makeCoordinator() -> MapCoordinator {
        MapCoordinator()
    }
    
    class MapCoordinator: NSObject, MKMapViewDelegate {
        func mapView(_ mapView: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
            if let poly = overlay as? MKPolyline {
                let renderer = MKPolylineRenderer(polyline: poly)
                renderer.strokeColor = .purple
                renderer.lineWidth = 3.0
                return renderer
            }
            return MKOverlayRenderer(overlay: overlay)
        }
        
        func mapView(_ mapView: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
            if annotation is MKUserLocation { return nil }
            let reuseID = "recordingMapAnnotation"
            var annView = mapView.dequeueReusableAnnotationView(withIdentifier: reuseID) as? MKMarkerAnnotationView
            if annView == nil {
                annView = MKMarkerAnnotationView(annotation: annotation, reuseIdentifier: reuseID)
            }
            annView?.annotation = annotation
            
            if annotation.title == "Meilleur débit" {
                annView?.glyphImage = UIImage(systemName: "star.fill")
                annView?.markerTintColor = .orange
            } else {
                annView?.glyphImage = UIImage(systemName: "circle.fill")
                annView?.markerTintColor = .blue
            }
            return annView
        }
    }
}

// MARK: - Global Formatters

let shortDateFormatter: DateFormatter = {
    let f = DateFormatter()
    f.dateStyle = .short
    f.timeStyle = .short
    return f
}()

// MARK: - CSV Export Helper

func exportCSV(for record: SpeedRecord) -> URL? {
    let header = "latitude,longitude,speed,timestamp,datetime\n"
    var csv = header
    let dateFormatter = DateFormatter()
    dateFormatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
    for dp in record.dataPoints {
        let lat = dp.latitude != nil ? "\(dp.latitude!)" : ""
        let lon = dp.longitude != nil ? "\(dp.longitude!)" : ""
        let speed = dp.speed
        let timestamp = Int(dp.time.timeIntervalSince1970)
        let datetime = dateFormatter.string(from: dp.time)
        csv.append("\(lat),\(lon),\(speed),\(timestamp),\(datetime)\n")
    }
    
    let fileManager = FileManager.default
    guard let documentsURL = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first else {
        return nil
    }
    
    let dateFormatterFile = DateFormatter()
    dateFormatterFile.dateFormat = "yyyy-MM-dd_HH-mm-ss"
    let safeDateString = dateFormatterFile.string(from: record.date)
    let fileName = "enregistrement_\(safeDateString).csv"
    let fileURL = documentsURL.appendingPathComponent(fileName)
    do {
        try csv.write(to: fileURL, atomically: true, encoding: .utf8)
        print("CSV file saved at \(fileURL)")
        return fileURL
    } catch {
        print("Error saving CSV: \(error)")
        return nil
    }
}

// MARK: - ShareSheet

struct ShareSheet: UIViewControllerRepresentable {
    var activityItems: [Any]
    var applicationActivities: [UIActivity]? = nil
    
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: activityItems, applicationActivities: applicationActivities)
    }
    
    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

// MARK: - URL Identifiable Extension

extension URL: Identifiable {
    public var id: String { absoluteString }
}
