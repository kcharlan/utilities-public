import Darwin
import Foundation

public func strftimeTimestamp(_ date: Date) -> String {
    var epoch = time_t(date.timeIntervalSince1970)
    var local = tm()
    guard localtime_r(&epoch, &local) != nil else { return "" }
    var buffer = [CChar](repeating: 0, count: 256)
    let count = strftime(&buffer, buffer.count, "%Y-%m-%d %H:%M:%S %Z", &local)
    return String(decoding: buffer.prefix(count).map { UInt8(bitPattern: $0) }, as: UTF8.self)
}
