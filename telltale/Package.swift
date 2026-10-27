// swift-tools-version: 6.0
// Port: anker_charge_monitor/Package.swift, Package, 4f965e8.
// Adaptation: Telltale's targets (spec section 13); CZstd holds vendored zstd from Task 2.
import PackageDescription

let package = Package(
    name: "Telltale",
    platforms: [.macOS("27.0")],
    products: [
        .library(name: "TelltaleCore", targets: ["TelltaleCore"]),
        .library(name: "TelltaleCodex", targets: ["TelltaleCodex"]),
        .library(name: "TelltaleOpenAIStatus", targets: ["TelltaleOpenAIStatus"]),
        .executable(name: "Telltale", targets: ["Telltale"])
    ],
    targets: [
        .target(name: "CZstd"),
        .target(name: "TelltaleCore"),
        .target(name: "TelltaleCodex", dependencies: ["TelltaleCore", "CZstd"]),
        .target(name: "TelltaleOpenAIStatus", dependencies: ["TelltaleCore"]),
        .executableTarget(name: "Telltale", dependencies: ["TelltaleCore", "TelltaleCodex", "TelltaleOpenAIStatus"]),
        .target(name: "TelltaleTestSupport", dependencies: ["TelltaleCore", "CZstd"], path: "Tests/TelltaleTestSupport"),
        .testTarget(name: "TelltaleCoreTests", dependencies: ["TelltaleCore", "TelltaleTestSupport"]),
        .testTarget(name: "TelltaleCodexTests", dependencies: ["TelltaleCodex", "TelltaleCore", "TelltaleTestSupport"], resources: [.copy("Fixtures")]),
        .testTarget(name: "TelltaleOpenAIStatusTests", dependencies: ["TelltaleOpenAIStatus", "TelltaleCore", "TelltaleTestSupport"], resources: [.copy("Fixtures")]),
        .testTarget(name: "TelltaleAppTests", dependencies: ["Telltale", "TelltaleCore", "TelltaleTestSupport"]),
        .testTarget(name: "TelltaleIntegrationTests", dependencies: ["TelltaleCore", "TelltaleCodex", "TelltaleOpenAIStatus", "TelltaleTestSupport"])
    ],
    swiftLanguageModes: [.v6]
)
