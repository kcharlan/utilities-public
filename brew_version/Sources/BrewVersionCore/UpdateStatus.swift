import Foundation

public enum UpdateStatus: Equatable, Codable, Sendable {
    case upToDate, ahead, updateAvailable(installed: String), notInstalled, unversioned
}

public func updateStatus(listing: Listing, installed: InstalledVersion?) -> UpdateStatus {
    guard let installed else { return .notInstalled }
    if listing.kind == .cask && listing.version == "latest" { return .unversioned }
    let available: String
    if listing.kind == .formula {
        available = installedForm(version: listing.version, revision: listing.revision)
    } else if installed.source == .appBundle {
        available = String(listing.version.prefix { $0 != "," })
    } else { available = listing.version }
    switch VersionOrder.compare(installed.version, available) {
    case .orderedSame: return .upToDate
    case .orderedDescending: return .ahead
    case .orderedAscending: return .updateAvailable(installed: installed.version)
    }
}

// Formula releases and installed kegs share Homebrew's revision suffix.
func installedForm(version: String, revision: Int) -> String {
    version + (revision > 0 ? "_\(revision)" : "")
}
