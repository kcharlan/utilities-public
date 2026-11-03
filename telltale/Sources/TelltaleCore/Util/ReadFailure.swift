import Foundation

/// Preserve the most useful diagnostic supplied by the original error.
public func readFailureReason(_ error: any Error) -> String {
    if error is CocoaError || type(of: error) is NSError.Type { return error.localizedDescription }
    if let descriptive = (error as Any) as? any CustomStringConvertible { return descriptive.description }
    return error.localizedDescription
}
