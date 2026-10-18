import Foundation

/// Semantic port of Homebrew Tap file discovery and remote normalization.
/// Copyright and BSD redistribution terms: Resources/Homebrew-LICENSE.txt.
/// Source: Library/Homebrew/tap.rb at 3073d6a8c34f71da054b000cfdbb62594a07c969.
public struct GitHubRepository: Hashable, Sendable {
    public let owner: String
    public let repo: String
}

public struct TapEntry: Hashable, Sendable {
    public let name: PackageName
    public let kind: PackageKind
    public let path: String
    public let repository: GitHubRepository?
}

public struct TapIndex: Sendable {
    private struct Tap: Sendable {
        let repository: GitHubRepository?
    }
    private let sources: [TapName: Tap]
    private let packages: [TapEntry]
    public static let empty = TapIndex(sources: [:], packages: [])
    public var taps: Set<TapName> { Set(sources.keys) }

    public static func scan(prefixes: [HomebrewPrefix]) -> TapIndex {
        var sources: [TapName: Tap] = [:]
        var packages: [TapEntry] = []
        for prefix in prefixes {
            let direct = prefix.root.appendingPathComponent("Library/Taps")
            let taps = directory(direct) ? direct : prefix.root.appendingPathComponent("Homebrew/Library/Taps")
            for owner in children(taps) where directory(owner) {
                for root in children(owner) where directory(root) {
                    let rawTap = "\(owner.lastPathComponent)/\(root.lastPathComponent)"
                    guard let tap = TapName(rawTap), !tap.isOfficial,
                          FileManager.default.fileExists(atPath: root.appendingPathComponent(".git").path),
                          sources[tap] == nil else { continue }
                    let repository = repository(at: root)
                    sources[tap] = Tap(repository: repository)
                    let formulaDirectory = ["Formula", "HomebrewFormula"].map { root.appendingPathComponent($0) }
                        .first(where: directory) ?? root
                    for (kind, folder, recursive) in [(PackageKind.formula, formulaDirectory, formulaDirectory != root),
                                                       (.cask, root.appendingPathComponent("Casks"), true)] {
                        var files: [String: String] = [:]
                        for file in rubyFiles(folder, recursive: recursive) {
                            let shortName = file.deletingPathExtension().lastPathComponent
                            guard PackageName(shortName) != nil else { continue }
                            let path = String(file.path.dropFirst(root.path.count + 1))
                            if files[shortName].map({ $0.count < path.count }) ?? true { files[shortName] = path }
                        }
                        for (shortName, path) in files {
                            // Normalize the directory input exactly once, including repeated reserved prefixes.
                            guard let name = PackageName("\(rawTap)/\(shortName)") else { continue }
                            packages.append(TapEntry(name: name, kind: kind, path: path, repository: repository))
                        }
                    }
                }
            }
        }
        packages.sort {
            if $0.name.rawValue != $1.name.rawValue { return $0.name.rawValue < $1.name.rawValue }
            return $0.kind == .formula && $1.kind == .cask
        }
        return TapIndex(sources: sources, packages: packages)
    }

    public func entries(shortName: String, kinds: KindPreference) -> [TapEntry] {
        packages.filter { $0.name.shortName == shortName && kinds.candidates.contains($0.kind) }
    }
    public func entry(_ name: PackageName, kind: PackageKind?) -> TapEntry? {
        let matches = packages.filter { $0.name == name }
        if let kind { return matches.first { $0.kind == kind } }
        return matches.first
    }
    public func suggestions(prefix: String) -> [TapEntry] {
        packages.filter { $0.name.shortName.hasPrefix(prefix) }
    }
    public func repository(for tap: TapName) -> GitHubRepository? { sources[tap]?.repository }

    private static func directory(_ url: URL) -> Bool {
        (try? url.resolvingSymlinksInPath().resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
    }
    private static func children(_ url: URL) -> [URL] {
        // Foundation does not enumerate a directory symlink directly. Keep the
        // lexical tap-relative path even when its selected formula directory is linked.
        ((try? FileManager.default.contentsOfDirectory(at: url.resolvingSymlinksInPath(), includingPropertiesForKeys: [.isDirectoryKey],
                                                      options: [.skipsHiddenFiles])) ?? [])
            .map { url.appendingPathComponent($0.lastPathComponent) }.sorted { $0.path < $1.path }
    }
    private static func rubyFiles(_ folder: URL, recursive: Bool) -> [URL] {
        children(folder).flatMap { file -> [URL] in
            if directory(file) {
                let symbolicLink = (try? file.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) == true
                return recursive && !symbolicLink ? rubyFiles(file, recursive: true) : []
            }
            return file.pathExtension == "rb" ? [file] : []
        }.sorted { $0.path < $1.path }
    }

    private static func repository(at root: URL) -> GitHubRepository? {
        guard let config = try? String(contentsOf: root.appendingPathComponent(".git/config"), encoding: .utf8) else { return nil }
        var origin = false
        var remote: String?
        for line in config.components(separatedBy: .newlines) {
            let line = line.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("[") {
                origin = line.range(of: #"^\[(?i:remote)\s+"origin"\]\s*(?:[#;].*)?$"#, options: .regularExpression) != nil
            } else if origin, let equals = line.firstIndex(of: "="),
                      line[..<equals].trimmingCharacters(in: .whitespaces).lowercased() == "url" {
                remote = configValue(String(line[line.index(after: equals)...]))
            }
        }
        guard var normalized = remote?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(), !normalized.isEmpty else { return nil }
        normalized = normalized.replacingOccurrences(of: #"^(?:[a-z][a-z0-9+.-]*://(?:[^@/]+@)?github\.com/|(?:[^@/]+@)?github\.com:)"#,
                                                      with: "https://github.com/", options: .regularExpression)
        // Only GitHub origins can produce a downloadable repository here. Homebrew also
        // strips suffixes for codeberg.org/gitlab.com, which remain unsupported sources.
        guard normalized.hasPrefix("https://github.com/") else { return nil }
        while normalized.hasSuffix("/") { normalized.removeLast() }
        if normalized.hasSuffix(".git") { normalized.removeLast(4) }
        let parts = normalized.dropFirst("https://github.com/".count).split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count == 2, parts.allSatisfy({ !$0.isEmpty && !$0.contains(where: { $0.isWhitespace || "?#:".contains($0) }) }) else { return nil }
        return GitHubRepository(owner: String(parts[0]), repo: String(parts[1]))
    }

    private static func configValue(_ raw: String) -> String {
        var value = "", quoted = false, escaped = false
        for character in raw.trimmingCharacters(in: .whitespaces) {
            if escaped {
                switch character {
                case "n": value.append("\n")
                case "t": value.append("\t")
                case "b": value.append("\u{8}")
                default: value.append(character)
                }
                escaped = false
            } else if character == "\\" { escaped = true }
            else if character == "\"" { quoted.toggle() }
            else if !quoted && (character == "#" || character == ";") { break }
            else { value.append(character) }
        }
        return value.trimmingCharacters(in: .whitespaces)
    }
}
