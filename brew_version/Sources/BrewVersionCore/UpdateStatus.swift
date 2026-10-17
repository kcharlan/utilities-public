import Foundation

public enum UpdateStatus: Equatable, Codable, Sendable {
    case upToDate, ahead, updateAvailable(installed: String), notInstalled, unversioned
}

public func updateStatus(listing: Listing, installed: InstalledVersion?) -> UpdateStatus {
    guard let installed else { return .notInstalled }
    if listing.kind == .cask && listing.version == "latest" { return .unversioned }
    let available: String
    if listing.kind == .formula {
        available = listing.version + (listing.revision > 0 ? "_\(listing.revision)" : "")
    } else if installed.source == .appBundle {
        available = String(listing.version.prefix { $0 != "," })
    } else { available = listing.version }
    switch VersionOrder.compare(installed.version, available) {
    case .orderedSame: return .upToDate
    case .orderedDescending: return .ahead
    case .orderedAscending: return .updateAvailable(installed: installed.version)
    }
}
