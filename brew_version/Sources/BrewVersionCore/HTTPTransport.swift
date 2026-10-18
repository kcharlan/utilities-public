import Foundation

public struct HTTPResponse: Sendable {
    public let status: Int
    public let body: Data
    public let etag: String?

    public init(status: Int, body: Data, etag: String? = nil) {
        self.status = status
        self.body = body
        self.etag = etag
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
        return HTTPResponse(status: response.statusCode, body: body, etag: response.value(forHTTPHeaderField: "ETag"))
    }

    public func urlSession(_ session: URLSession, task: URLSessionTask,
                           willPerformHTTPRedirection response: HTTPURLResponse,
                           newRequest request: URLRequest,
                           completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(request.url?.scheme?.lowercased() == "https" ? request : nil)
    }
}
