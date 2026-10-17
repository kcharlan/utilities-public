// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "BrewVersion",
    platforms: [.macOS(.v14)],
    products: [.library(name: "BrewVersionCore", targets: ["BrewVersionCore"])],
    targets: [
        .target(name: "BrewVersionCore"),
        .testTarget(name: "BrewVersionCoreTests", dependencies: ["BrewVersionCore"])
    ],
    swiftLanguageModes: [.v6]
)
