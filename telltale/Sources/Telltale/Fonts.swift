import AppKit
import SwiftUI

/// Barlow Semi Condensed, the visual doc's instrument-readout face (spec section 9.2): big
/// numerals, lamp captions and axis numbers, always with tabular figures. It ships in the bundle's
/// `Resources/Fonts` (OFL 1.1, `OFL.txt` beside it) and is registered for this process at launch.
/// When it can't be registered, the system font stands in and one line is logged **(plan call)**.
enum Fonts {
    static let regular = "BarlowSemiCondensed-Regular"
    static let medium = "BarlowSemiCondensed-Medium"

    /// The bundle's fonts folder (`Contents/Resources/Fonts`).
    static var bundled: URL? { Bundle.main.resourceURL?.appending(path: "Fonts", directoryHint: .isDirectory) }

    /// Registers every `.ttf` and `.otf` file in `directory` for this process. A font this process
    /// already registered counts as registered. Returns false, after logging one line, when the
    /// folder can't be read, holds no font, or any font fails.
    @discardableResult
    static func register(from directory: URL, log: (String) -> Void = { FileHandle.standardError.write(Data("\($0)\n".utf8)) }) -> Bool {
        let files: [URL]
        do {
            files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
                .filter { ["ttf", "otf"].contains($0.pathExtension.lowercased()) }
                .sorted { $0.lastPathComponent < $1.lastPathComponent }
        } catch {
            log("Telltale couldn't read its fonts at \(directory.path): \(error.localizedDescription). Using the system font.")
            return false
        }
        guard !files.isEmpty else {
            log("Telltale found no fonts at \(directory.path). Using the system font.")
            return false
        }
        var failed: [String] = []
        for file in files {
            var error: Unmanaged<CFError>?
            if CTFontManagerRegisterFontsForURL(file as CFURL, .process, &error) { continue }
            let failure = error?.takeRetainedValue()
            if let failure, CFErrorGetCode(failure) == CTFontManagerError.alreadyRegistered.rawValue { continue }
            failed.append(file.lastPathComponent)
        }
        guard failed.isEmpty else {
            log("Telltale couldn't register \(failed.joined(separator: ", ")). Using the system font.")
            return false
        }
        return true
    }

    /// Whether both faces resolve, so readouts use Barlow rather than the system font.
    static var isAvailable: Bool { NSFont(name: regular, size: 12) != nil && NSFont(name: medium, size: 12) != nil }

    /// A readout face at `size` with tabular figures: Barlow when registered, else the system font.
    static func gauge(_ size: CGFloat, medium: Bool = true) -> Font {
        let name = medium ? Self.medium : regular
        if NSFont(name: name, size: size) != nil {
            return Font.custom(name, fixedSize: size).monospacedDigit()
        }
        return Font.system(size: size, weight: medium ? .medium : .regular).monospacedDigit()
    }
}
