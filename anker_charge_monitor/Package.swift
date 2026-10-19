// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "PrimeMonitor",
    platforms: [.macOS("27.0")],
    products: [
        .library(name: "PrimeMonitorCore", targets: ["PrimeMonitorCore"]),
        .library(name: "AnkerCloud", targets: ["AnkerCloud"]),
        .executable(name: "PrimeMonitor", targets: ["PrimeMonitor"])
    ],
    targets: [
        .target(name: "PrimeMonitorCore"),
        .target(name: "AnkerCloud", dependencies: ["PrimeMonitorCore"]),
        .executableTarget(name: "PrimeMonitor", dependencies: ["PrimeMonitorCore", "AnkerCloud"]),
        .testTarget(name: "PrimeMonitorCoreTests", dependencies: ["PrimeMonitorCore"]),
        .testTarget(name: "AnkerCloudTests", dependencies: ["AnkerCloud", "PrimeMonitorCore"], resources: [.copy("Fixtures")]),
        .testTarget(name: "PrimeMonitorAppTests", dependencies: ["PrimeMonitor", "PrimeMonitorCore", "AnkerCloud"])
    ],
    swiftLanguageModes: [.v6]
)
