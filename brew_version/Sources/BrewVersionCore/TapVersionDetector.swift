import Foundation

/// Semantic port of Homebrew Version.detect/parse, version/parser.rb and
/// extend/pathname.rb at commit 3073d6a8c34f71da054b000cfdbb62594a07c969.
/// Copyright and BSD redistribution terms: Resources/Homebrew-LICENSE.txt.
public enum TapVersionDetector {
    public static func detect(url: String, tag: String? = nil) -> String? {
        // Homebrew decodes the whole spec as a form component, including '+'
        // as a space, even though it is not technically correct URL decoding.
        guard let spec = (tag ?? url).replacingOccurrences(of: "+", with: " ").removingPercentEncoding else {
            return nil
        }
        let filename = processedStem(spec)
        for parser in parsers {
            if let version = capture(parser.regex, in: parser.url ? spec : filename), !version.isEmpty {
                return parser.underscores ? version.replacingOccurrences(of: "_", with: ".") : version
            }
        }
        return nil
    }

    private struct Parser {
        let regex: NSRegularExpression
        let url: Bool
        let underscores: Bool
        init(_ pattern: String, url: Bool = false, underscores: Bool = false) {
            self.regex = expression(pattern)
            self.url = url
            self.underscores = underscores
        }
    }

    private static let numeric = #"(?:\d+(?:\.\d+)*)"#
    private static let dotted = #"(?:\d+(?:\.\d+)+)"#
    private static let minorOrPatch = #"(?:\d+(?:\.\d+){1,2})"#
    private static let content = #"(?:[._-](?i:bin|dist|stable|src|sources?|final|full))"#
    private static let prerelease = #"(?:[._-]?(?i:alpha|beta|pre|rc)\.?\d{0,2})"#

    // Keep exactly VERSION_PARSERS order: the first successful capture wins.
    private static let parsers: [Parser] = [
        Parser(#"(?:^|[._-]?)v?(\d{4}-\d{2}-\d{2})"#),
        Parser(#"github\.com/.+/(?:zip|tar)ball/(?:v|\w+-)?((?:\d+[._-])+\d*)$"#, url: true),
        Parser(#"github\.com/.+/releases/download/(?:[rvV]_?)?("# + dotted + #")/"#, url: true),
        Parser(#"[_-]([Rr]\d+[AaBb]\d*(?:-\d+)?)"#, url: true),
        Parser(#"((?:\d+_)+\d+)$"#, underscores: true),
        Parser(#"[_-]("# + dotted + #"-(?:p|P|rc|RC)?\d+)"# + content + #"?$"#),
        Parser(#"^v?("# + dotted + #"(?:-"# + numeric + #")+)"#),
        Parser(#"[-v]("# + numeric + #")$"#, url: true),
        Parser(#"-(\d+-\d+)"#),
        Parser(#"-("# + numeric + #")$"#),
        Parser(#"-("# + numeric + #"(?:.post\d+)?)$"#),
        Parser(#"-("# + numeric + #"(?:[abc]|rc|RC)\d*)$"#),
        Parser(#"-("# + numeric + #"-(?:alpha|beta|rc)\d*)$"#),
        Parser(#"-("# + minorOrPatch + #")-w(?:in)?(?:32|64)$"#),
        Parser(#"\.("# + minorOrPatch + #")\+opam$"#),
        Parser(#"[_-]("# + minorOrPatch + #"(?:-\d+)?)[._-](?:i[36]86|x86|x64(?:[_-](?:32|64))?)$"#),
        Parser(#"[-.vV]?("# + dotted + prerelease + #")"#),
        Parser(#"("# + numeric + #")$"#),
        Parser(#"[-vV]("# + dotted + #"[abc]?)"# + content + #"$"#),
        Parser(#"-("# + dotted + #")-"#),
        Parser(#"_("# + numeric + #"[abc]?)\.orig$"#),
        Parser(#"-v?(\d[^-]+)"#),
        Parser(#"_v?(\d[^_]+)"#),
        Parser(#"/(?:[rvV]_?)?(\d+\.\d+(?:\.\d+){0,2})"#, url: true),
        Parser(#"\.v(\d+[a-z]?)"#),
        Parser(#"[-.vV]?("# + dotted + prerelease + #"?)"#, url: true)
    ]

    private static let sourceForge = expression(#"(?:sourceforge\.net|sf\.net)/.*/download$"#)
    private static let noExtension = expression(#"\.[^a-zA-Z]+$"#)
    private static let bottle = expression(#"(\.[a-z0-9_]+\.bottle\.(?:\d+\.)?tar\.gz)$"#)
    private static let archive = expression(#"(\.(?:tar|cpio|pax)\.(?:gz|bz2|lz|xz|zst|Z))\Z"#)
    private static let versionExtension = expression(#"\b\d+\.\d+[^.]*\Z"#)

    private static func processedStem(_ spec: String) -> String {
        if matches(sourceForge, spec) {
            let trimmed = trimTrailingSlashes(spec)
            let parent = trimmed.lastIndex(of: "/").map { String(trimmed[..<$0]) } ?? "."
            return stem(parent)
        }
        if matches(noExtension, spec) { return basename(spec) }
        return stem(spec)
    }

    private static func trimTrailingSlashes(_ path: String) -> String {
        var result = path
        while result.count > 1 && result.hasSuffix("/") { result.removeLast() }
        return result
    }

    private static func basename(_ path: String) -> String {
        let path = trimTrailingSlashes(path)
        return path.split(separator: "/").last.map(String.init) ?? path
    }

    private static func stem(_ path: String) -> String {
        let name = basename(path)
        let ext: String
        if let suffix = capture(bottle, in: name) ?? capture(archive, in: name) {
            ext = suffix
        } else if matches(versionExtension, name) && !name.hasSuffix(".7z") {
            ext = ""
        } else if let dot = name.lastIndex(of: "."), dot != name.startIndex {
            ext = String(name[dot...])
        } else {
            ext = ""
        }
        // A \Z match can finish before a trailing LF. File.basename(name,
        // extname) removes only a literal suffix, not a match near the end.
        return name.hasSuffix(ext) ? String(name.dropLast(ext.count)) : name
    }

    private static func expression(_ pattern: String) -> NSRegularExpression {
        // Ruby's digit/word classes are ASCII for these version expressions.
        let pattern = pattern.replacingOccurrences(of: #"\d"#, with: "[0-9]")
            .replacingOccurrences(of: #"\w"#, with: "[A-Za-z0-9_]")
            // ICU's \Z accepts non-LF terminators even in Unix mode.
            .replacingOccurrences(of: #"\Z"#, with: #"(?=\n?\z)"#)
        // Ruby ^/$ are line anchors and its dot/anchors recognize only LF.
        // ICU's default line terminators also include CR and Unicode separators.
        return try! NSRegularExpression(pattern: pattern, options: [.anchorsMatchLines, .useUnixLineSeparators])
    }

    private static func matches(_ regex: NSRegularExpression, _ value: String) -> Bool {
        regex.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)) != nil
    }

    private static func capture(_ regex: NSRegularExpression, in value: String) -> String? {
        guard let match = regex.firstMatch(in: value, range: NSRange(value.startIndex..., in: value)),
              let range = Range(match.range(at: 1), in: value) else { return nil }
        return String(value[range])
    }
}
