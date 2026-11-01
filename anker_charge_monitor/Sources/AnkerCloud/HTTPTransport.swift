import Foundation

public protocol HTTPTransport: Sendable {
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse)
}

/// Total timeout from anker-solix-api `apitypes.py`, REQUEST_TIMEOUT_DEF,
/// and `session.py`, request, commit 8a5222b.
public final class URLSessionTransport: NSObject, HTTPTransport, URLSessionTaskDelegate, @unchecked Sendable {
    private let configuration: URLSessionConfiguration

    public override convenience init() { self.init(protocolClasses: nil) }

    init(protocolClasses: [AnyClass]?) {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 10
        configuration.timeoutIntervalForResource = 10
        configuration.httpCookieStorage = nil
        configuration.urlCache = nil
        if let protocolClasses { configuration.protocolClasses = protocolClasses }
        self.configuration = configuration
        super.init()
    }

    public func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        guard request.url?.scheme?.lowercased() == "https" else { throw URLError(.unsupportedURL) }
        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse else { throw AnkerError.malformed }
        return (data, response)
    }

    public func urlSession(_ session: URLSession, task: URLSessionTask,
                           willPerformHTTPRedirection response: HTTPURLResponse,
                           newRequest request: URLRequest,
                           completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        guard let source = response.url, let target = request.url,
              target.scheme?.lowercased() == "https",
              target.host?.lowercased() == source.host?.lowercased(),
              (target.port ?? 443) == (source.port ?? 443) else {
            completionHandler(nil); return
        }
        completionHandler(request)
    }
}
