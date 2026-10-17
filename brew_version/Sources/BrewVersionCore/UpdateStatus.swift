import Foundation

public enum UpdateStatus: Equatable, Codable, Sendable {
    case upToDate, ahead, updateAvailable(installed: String), notInstalled, unversioned
}

public func updateStatus(listing: Listing, installed: InstalledVersion?) -> UpdateStatus {
    guard let installed else { return .notInstalled }
    if listing.kind == .cask && listing.version == "latest" { return .unversioned }
    let comparison: ComparisonResult
    if listing.kind == .formula {
        comparison = FormulaVersion(keg: installed.version).compare(FormulaVersion(version: listing.version, revision: listing.revision))
    } else {
        let available = installed.source == .appBundle ? String(listing.version.prefix { $0 != "," }) : listing.version
        comparison = VersionOrder.compare(installed.version, available)
    }
    switch comparison {
    case .orderedSame: return .upToDate
    case .orderedDescending: return .ahead
    case .orderedAscending: return .updateAvailable(installed: installed.version)
    }
}

// Display only: formula comparisons keep upstream version and revision separate.
func installedForm(version: String, revision: Int) -> String {
    version + (revision > 0 ? "_\(revision)" : "")
}

// Homebrew PkgVersion semantics: compare Version first, then numeric revision.
struct FormulaVersion {
    private let version: String
    private let revision: String

    init(version: String, revision: Int) {
        self.version = version
        self.revision = String(revision)
    }

    init(keg: String) {
        if let separator = keg.lastIndex(of: "_") {
            let suffix = keg[keg.index(after: separator)...]
            if !suffix.isEmpty && suffix.allSatisfy({ $0.isASCII && $0.isNumber }) {
                version = String(keg[..<separator])
                revision = String(suffix)
                return
            }
        }
        version = keg
        revision = "0"
    }

    func compare(_ other: FormulaVersion) -> ComparisonResult {
        let upstream = VersionOrder.compare(version, other.version)
        // Numeric-only VersionOrder tokens preserve arbitrary precision and leading zeroes.
        return upstream == .orderedSame ? VersionOrder.compare(revision, other.revision) : upstream
    }
}
