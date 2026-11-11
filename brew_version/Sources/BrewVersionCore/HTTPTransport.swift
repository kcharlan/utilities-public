import Foundation

public struct HTTPResponse: Sendable {
    public let status: Int
    public let body: Data
    public let etag: String?
    public let headers: [String: String]

    public init(status: Int, body: Data, etag: String? = nil, headers: [String: String] = [:]) {
        self.status = status
        self.body = body
        self.etag = etag
        self.headers = Dictionary(headers.map { ($0.key.lowercased(), $0.value) }, uniquingKeysWith: { _, last in last })
    }
}

public protocol HTTPTransport: Sendable {
    func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse
}

public final class URLSessionTransport: NSObject, HTTPTransport, URLSessionTaskDelegate, @unchecked Sendable {
    // Immutable after initialization. Callers receive a copy so they cannot alter
    // cache or HTTPS policy while another task is making a request.
    private let sessionConfiguration: URLSessionConfiguration
    public var configuration: URLSessionConfiguration { sessionConfiguration.copy() as! URLSessionConfiguration }

    public init(requestTimeout: TimeInterval, resourceTimeout: TimeInterval, protocolClasses: [AnyClass]? = nil) {
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.timeoutIntervalForRequest = requestTimeout
        config.timeoutIntervalForResource = resourceTimeout
        if let protocolClasses { config.protocolClasses = protocolClasses }
        sessionConfiguration = config
        super.init()
    }

    public static func standard() -> URLSessionTransport {
        URLSessionTransport(requestTimeout: 10, resourceTimeout: 30)
    }

    public func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        guard url.scheme?.lowercased() == "https" else { throw URLError(.unsupportedURL) }
        var request = URLRequest(url: url)
        request.setValue(ifNoneMatch, forHTTPHeaderField: "If-None-Match")
        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (body, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        let headers = ["last-modified", "age", "x-cache", "date"].reduce(into: [String: String]()) { result, key in result[key] = response.value(forHTTPHeaderField: key) }
        return HTTPResponse(status: response.statusCode, body: body, etag: response.value(forHTTPHeaderField: "ETag"), headers: headers)
    }

    public func urlSession(_ session: URLSession, task: URLSessionTask,
                           willPerformHTTPRedirection response: HTTPURLResponse,
                           newRequest request: URLRequest,
                           completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(request.url?.scheme?.lowercased() == "https" ? request : nil)
    }
}

public struct LoggingTransport: HTTPTransport {
    private let base: any HTTPTransport
    private let log: any EventLogging
    public init(_ base: any HTTPTransport, log: any EventLogging) { self.base = base; self.log = log }
    public func get(_ url: URL, ifNoneMatch: String?) async throws -> HTTPResponse {
        let start = ContinuousClock.now
        func fields() -> [String: LogValue] {
            ["host": .string(url.host ?? ""), "path": .string(url.path), "ms": .int(Int(start.duration(to: .now).components.seconds * 1000 + start.duration(to: .now).components.attoseconds / 1_000_000_000_000_000))]
        }
        do {
            let response = try await base.get(url, ifNoneMatch: ifNoneMatch)
            if response.status != 304 {
                var values = fields(); values["status"] = .int(response.status)
                if let etag = response.etag { values["etag"] = .string(etag) }
                for (header, key) in [("last-modified", "lastModified"), ("age", "age"), ("x-cache", "xCache"), ("date", "date")] {
                    if let value = response.headers[header] { values[key] = .string(value) }
                }
                log.record("http", values)
            }
            return response
        } catch {
            var values = fields(); values["error"] = .string(error.localizedDescription); log.record("http", values)
            throw error
        }
    }
}
