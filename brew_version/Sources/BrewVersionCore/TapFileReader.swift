import Foundation

/// Reads the supported literal subset of Homebrew's Ruby DSL without executing it.
public enum TapFileReader {
    public static let hostIsArm64: Bool = {
        #if arch(arm64)
        true
        #else
        false
        #endif
    }()

    public static func listing(from text: String, name: PackageName, kind: PackageKind,
                               arm64: Bool = hostIsArm64) -> Listing? {
        let statements = statements(in: text)
        let wrapped = statements.contains { isPackage($0, kind: kind) }
        var scopes: [Scope] = []
        var fields: [String: [Token]] = [:]
        var apps: [[Token]] = []
        for statement in statements {
            guard let command = statement.first?.word else { continue }
            let counting = scopes.last?.active ?? !wrapped
            switch command {
            case "end":
                if !scopes.isEmpty { scopes.removeLast() }
                continue
            case "else", "elsif":
                if var scope = scopes.popLast() {
                    if scope.architecture {
                        let selected = command == "else" ? true : architecture(statement.dropFirst(), arm64: arm64) == true
                        scope.active = scope.parentActive && !scope.branchTaken && selected
                        scope.branchTaken = scope.branchTaken || selected
                    }
                    scopes.append(scope)
                }
                continue
            default: break
            }
            if isPackage(statement, kind: kind), scopes.isEmpty {
                scopes.append(Scope(active: true, parentActive: true))
                continue
            }
            if ["if", "unless", "case", "class", "module", "def"].contains(command) {
                let selected = command == "if" ? architecture(statement.dropFirst(), arm64: arm64) : nil
                scopes.append(Scope(active: counting && selected == true, parentActive: counting,
                                    architecture: selected != nil, branchTaken: selected == true))
                continue
            }
            // Presence and first-statement precedence apply even when a field
            // has an unreadable block argument. Record it before suppressing
            // that block's body, while respecting the enclosing scope.
            if counting {
                let arguments = arguments(of: statement)
                if command == "app" { apps.append(arguments) }
                else if ["version", "url", "revision", "desc", "homepage", "auto_updates"].contains(command), fields[command] == nil {
                    fields[command] = arguments
                }
            }
            if statement.contains(.word("do")) {
                let allowed = statement == [.word(command), .word("do")] &&
                    (["stable", "on_macos"].contains(command) || command == (arm64 ? "on_arm" : "on_intel"))
                scopes.append(Scope(active: counting && allowed, parentActive: counting))
                continue
            }
        }

        let version: String?
        if let explicit = fields["version"] {
            version = kind == .cask && explicit == [.word(":latest")] ? "latest" : literal(explicit)
        } else if kind == .formula, let arguments = fields["url"], let url = call(arguments) {
            version = TapVersionDetector.detect(url: url.value, tag: url.keywords["tag"])
        } else { version = nil }
        guard let version, !version.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        let revision = fields["revision"].flatMap { tokens -> Int? in
            guard tokens.count == 1, let word = tokens.first?.word,
                  word.allSatisfy({ $0.isASCII && $0.isNumber }) else { return nil }
            return Int(word)
        } ?? 0
        let appNames = kind == .cask ? apps.compactMap { tokens -> String? in
            guard let app = call(tokens) else { return nil }
            let path = app.keywords["target"] ?? app.value
            let component = (path as NSString).lastPathComponent
            return component.isEmpty || component == "/" ? nil : component
        } : []
        return Listing(name: name, kind: kind, version: version, revision: revision,
                       autoUpdates: fields["auto_updates"] == [.word("true")],
                       summary: fields["desc"].flatMap(literal),
                       homepage: fields["homepage"].flatMap(literal).flatMap(URL.init(string:)),
                       appNames: appNames)
    }

    private struct Scope {
        var active: Bool
        let parentActive: Bool
        var architecture = false
        var branchTaken = false
    }

    private enum Token: Equatable {
        case word(String), string(String)
        var word: String? {
            if case let .word(value) = self { value } else { nil }
        }
    }

    private static func isPackage(_ tokens: [Token], kind: PackageKind) -> Bool {
        if kind == .formula {
            return tokens.first == .word("class") && tokens.suffix(2) == [.word("<"), .word("Formula")]
        }
        return tokens.count == 3 && tokens.first == .word("cask") &&
            tokens.last == .word("do") && literal([tokens[1]]) != nil
    }

    private static func architecture(_ tokens: ArraySlice<Token>, arm64: Bool) -> Bool? {
        switch Array(tokens) {
        case [.word("Hardware::CPU.arm?")]: arm64
        case [.word("Hardware::CPU.intel?")]: !arm64
        default: nil
        }
    }

    private static func arguments(of statement: [Token]) -> [Token] {
        var result = Array(statement.dropFirst())
        // A statement modifier does not introduce a scope. Its condition is not
        // evaluated: this reader selects only the documented architecture blocks.
        if let index = result.firstIndex(where: { $0 == .word("if") || $0 == .word("unless") }) {
            result = Array(result[..<index])
        }
        if result.first == .word("("), result.last == .word(")") {
            result = Array(result.dropFirst().dropLast())
        }
        return result
    }

    private static func literal(_ tokens: [Token]) -> String? {
        guard tokens.count == 1, case let .string(value) = tokens[0], !value.contains("#{") else { return nil }
        return value
    }

    private static func call(_ tokens: [Token]) -> (value: String, keywords: [String: String])? {
        guard let value = tokens.first.flatMap({ literal([$0]) }) else { return nil }
        var keywords: [String: String] = [:]
        var index = 1
        while index < tokens.count {
            guard index + 2 < tokens.count, tokens[index] == .word(","),
                  let keyword = tokens[index + 1].word, keyword.hasSuffix(":"),
                  let argument = literal([tokens[index + 2]]) else { return nil }
            let key = String(keyword.dropLast())
            if keywords[key] == nil { keywords[key] = argument }
            index += 3
        }
        return (value, keywords)
    }

    /// Tokenize strings and comments before recognizing statements or blocks, so
    /// Ruby words inside data cannot affect nesting. Commas, escaped newlines and
    /// open parentheses continue the current statement across physical lines.
    private static func statements(in text: String) -> [[Token]] {
        let characters = Array(text)
        var index = 0
        var current: [Token] = []
        var result: [[Token]] = []
        var parentheses = 0
        var continued = false
        func finish() {
            if !current.isEmpty { result.append(current); current = [] }
        }
        while index < characters.count {
            let character = characters[index]
            if character == "#" {
                while index < characters.count, characters[index] != "\n" { index += 1 }
                continue
            }
            if character == "\n" || character == ";" {
                if character == ";" || (parentheses == 0 && current.last != .word(",") && !continued) { finish() }
                continued = false
                index += 1
                continue
            }
            if character.isWhitespace { index += 1; continue }
            if character == "\\", index + 1 < characters.count, characters[index + 1] == "\n" {
                continued = true
                index += 1
                continue
            }
            if character == "\"" || character == "'" {
                let quote = character
                index += 1
                var value = ""
                var closed = false
                while index < characters.count {
                    let next = characters[index]
                    index += 1
                    if next == quote { closed = true; break }
                    if next == "\\", index < characters.count {
                        let escaped = characters[index]
                        index += 1
                        if escaped == quote || escaped == "\\" { value.append(escaped) }
                        else if quote == "\"", escaped == "n" { value.append("\n") }
                        else if quote == "\"", escaped == "t" { value.append("\t") }
                        else { value.append("\\"); value.append(escaped) }
                    } else { value.append(next) }
                }
                current.append(closed ? .string(value) : .word("unclosed-string"))
                continue
            }
            if ["(", ")", ","].contains(character) {
                if character == "(" { parentheses += 1 }
                if character == ")" { parentheses = max(0, parentheses - 1) }
                current.append(.word(String(character)))
                index += 1
                continue
            }
            let start = index
            while index < characters.count,
                  !characters[index].isWhitespace,
                  !["#", "\"", "'", "(", ")", ",", ";", "\\"].contains(characters[index]) { index += 1 }
            if start == index { index += 1 }
            current.append(.word(String(characters[start..<index])))
        }
        finish()
        return result
    }
}
