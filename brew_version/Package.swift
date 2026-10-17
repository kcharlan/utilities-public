// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "BrewVersion",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "BrewVersionCore", targets: ["BrewVersionCore"]),
        .library(name: "BrewVersionCLI", targets: ["BrewVersionCLI"]),
        .executable(name: "brew-version", targets: ["brew-version"]),
        .executable(name: "BrewVersion", targets: ["BrewVersion"])
    ],
    targets: [
        .target(name: "BrewVersionCore"),
        .target(name: "BrewVersionCLI", dependencies: ["BrewVersionCore"]),
        .executableTarget(name: "brew-version", dependencies: ["BrewVersionCLI", "BrewVersionCore"]),
        .executableTarget(name: "BrewVersion", dependencies: ["BrewVersionCore"]),
        .testTarget(name: "BrewVersionAppTests", dependencies: ["BrewVersion"]),
        .testTarget(name: "BrewVersionCoreTests", dependencies: ["BrewVersionCore"]),
        .testTarget(name: "BrewVersionCLITests", dependencies: ["BrewVersionCLI", "BrewVersionCore"], resources: [.copy("Fixtures")])
    ],
    swiftLanguageModes: [.v6]
)
