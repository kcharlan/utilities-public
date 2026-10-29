import Foundation

enum AppBundle {
    static func buildHelp(info: [String: Any]?) -> String? {
        guard let build = info?["CFBundleVersion"] as? String, !build.isEmpty else { return nil }
        return "Build \(build)"
    }
}
