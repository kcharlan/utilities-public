// swift-tools-version: 6.0
// Port: anker_charge_monitor/Package.swift, Package, 4f965e8.
// Adaptation: Telltale's targets (spec section 13); CZstd holds vendored zstd.
import PackageDescription

let package = Package(
    name: "Telltale",
    platforms: [.macOS("27.0")],
    products: [
        .library(name: "TelltaleCore", targets: ["TelltaleCore"]),
        .library(name: "TelltaleClaude", targets: ["TelltaleClaude"]),
        .library(name: "TelltaleCodex", targets: ["TelltaleCodex"]),
        .library(name: "TelltaleOpenAIStatus", targets: ["TelltaleOpenAIStatus"]),
        .library(name: "TelltaleStatuspage", targets: ["TelltaleStatuspage"]),
        .executable(name: "Telltale", targets: ["Telltale"])
    ],
    targets: [
        // Vendored zstd v1.5.7 decompression only; Sources/CZstd/VERSION records the provenance and
        // the defines below (Tests/ReleaseChecks/check_vendor.sh verifies the digests).
        .target(
            name: "CZstd",
            exclude: ["LICENSE", "VERSION"],
            cSettings: [
                .headerSearchPath("."),
                .define("XXH_NAMESPACE", to: "ZSTD_"),
                .define("ZSTD_DISABLE_ASM", to: "1"),
                .define("ZSTD_LEGACY_SUPPORT", to: "0")
            ]
        ),
        .target(name: "TelltaleCore"),
        .target(name: "TelltaleClaude", dependencies: ["TelltaleCore"]),
        .target(name: "TelltaleCodex", dependencies: ["TelltaleCore", "CZstd"]),
        .target(name: "TelltaleOpenAIStatus", dependencies: ["TelltaleCore"]),
        .target(name: "TelltaleStatuspage", dependencies: ["TelltaleCore"]),
        .executableTarget(name: "Telltale", dependencies: ["TelltaleCore", "TelltaleCodex", "TelltaleClaude", "TelltaleOpenAIStatus", "TelltaleStatuspage"]),
        .target(name: "TelltaleTestSupport", dependencies: ["TelltaleCore", "CZstd"], path: "Tests/TelltaleTestSupport"),
        .testTarget(name: "TelltaleCoreTests", dependencies: ["TelltaleCore", "TelltaleTestSupport"]),
        .testTarget(name: "TelltaleClaudeTests", dependencies: ["TelltaleClaude", "TelltaleCore", "TelltaleTestSupport"], resources: [.copy("Fixtures")]),
        .testTarget(name: "TelltaleCodexTests", dependencies: ["TelltaleCodex", "TelltaleCore", "TelltaleTestSupport"], resources: [.copy("Fixtures")]),
        .testTarget(name: "TelltaleOpenAIStatusTests", dependencies: ["TelltaleOpenAIStatus", "TelltaleCore", "TelltaleTestSupport"], resources: [.copy("Fixtures")]),
        .testTarget(name: "TelltaleStatuspageTests", dependencies: ["TelltaleStatuspage", "TelltaleCore"], resources: [.copy("Fixtures")]),
        .testTarget(name: "TelltaleAppTests", dependencies: ["Telltale", "TelltaleCore", "TelltaleTestSupport"]),
        .testTarget(name: "TelltaleIntegrationTests", dependencies: ["TelltaleCore", "TelltaleCodex", "TelltaleClaude", "TelltaleOpenAIStatus", "TelltaleStatuspage", "TelltaleTestSupport"])
    ],
    swiftLanguageModes: [.v6]
)
