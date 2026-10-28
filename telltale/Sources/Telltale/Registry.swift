import Foundation
import TelltaleCodex
import TelltaleCore
import TelltaleOpenAIStatus

/// The single registration list (spec section 5): plugins are compiled in, and snapping one in
/// means adding it here. Each usage source's `statusSourceID` names a status source below.
enum Registry {
    static func usageSources(paths: TelltalePaths) -> [any UsageSource] {
        [CodexUsageSource(codexHome: paths.codexHome)]
    }

    static func statusSources() -> [any StatusSource] {
        [OpenAIStatusSource(transport: URLSessionTransport())]
    }
}
