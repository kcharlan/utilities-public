import Foundation
import Network
@preconcurrency import Security

protocol MQTTLink: Sendable {
    func open(host: String, port: UInt16, identity: SecIdentity, rootCA: SecCertificate) async throws
    func send(_ packet: MQTTPacket) async throws
    var packets: AsyncThrowingStream<MQTTPacket, Error> { get }
    func close() async
}

enum MQTTConnectionError: Error { case closed, timeout, refused, subscription, invalidCertificate }

/// The write and cancel operations NWMQTTLink needs from its connection, so a test
/// fixture can hold writes beneath the real link. Completions run on the link queue.
protocol MQTTByteConnection: AnyObject {
    func transmit(_ data: Data, completion: @escaping @Sendable (Error?) -> Void)
    func cancel()
}

extension NWConnection: MQTTByteConnection {
    func transmit(_ data: Data, completion: @escaping @Sendable (Error?) -> Void) {
        send(content: data, completion: .contentProcessed { completion($0) })
    }
}

/// Network state is confined to queue. TLS matches mqtt.py create_client,
/// anker-solix-api 8a5222b / PR §3.2: supplied root only, hostname verified.
/// Every pending send is resumed exactly once: by its write completion, or with
/// `closed` when the link finishes. Cancelling the connection does not guarantee a
/// completion, so finishing disposes of pending sends itself and a later
/// completion finds nothing to resume.
final class NWMQTTLink: MQTTLink, @unchecked Sendable {
    let packets: AsyncThrowingStream<MQTTPacket, Error>
    private let output: AsyncThrowingStream<MQTTPacket, Error>.Continuation
    private let queue: DispatchQueue
    private var connection: (any MQTTByteConnection)?
    private var pendingSends: [UInt64: CheckedContinuation<Void, Error>] = [:]
    private var nextSendID: UInt64 = 0
    private var opening: CheckedContinuation<Void, Error>?
    private var decoder = MQTTDecoder()
    private var closed = false

    init(queue: DispatchQueue = DispatchQueue(label: "PrimeMonitor.MQTT")) {
        self.queue = queue
        (packets, output) = AsyncThrowingStream.makeStream()
    }

    /// A link already open on `connection`, whose completions run on `queue`. Tests
    /// use it to exercise send disposal beneath the real link.
    convenience init(queue: DispatchQueue, attached connection: any MQTTByteConnection) {
        self.init(queue: queue)
        queue.sync { self.connection = connection }
    }

    static func evaluate(_ trust: SecTrust, host: String, root: SecCertificate) -> Bool {
        guard SecTrustSetPolicies(trust, SecPolicyCreateSSL(true, host as CFString)) == errSecSuccess,
              SecTrustSetAnchorCertificates(trust, [root] as CFArray) == errSecSuccess,
              SecTrustSetAnchorCertificatesOnly(trust, true) == errSecSuccess else { return false }
        return SecTrustEvaluateWithError(trust, nil)
    }

    func open(host: String, port: UInt16, identity: SecIdentity, rootCA: SecCertificate) async throws {
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                queue.async {
                    guard !self.closed, self.connection == nil else {
                        continuation.resume(throwing: MQTTConnectionError.closed); return
                    }
                    let tls = NWProtocolTLS.Options()
                    sec_protocol_options_set_local_identity(tls.securityProtocolOptions, sec_identity_create(identity)!)
                    sec_protocol_options_set_tls_server_name(tls.securityProtocolOptions, host)
                    sec_protocol_options_set_verify_block(tls.securityProtocolOptions, { _, trust, complete in
                        complete(Self.evaluate(sec_trust_copy_ref(trust).takeRetainedValue(), host: host, root: rootCA))
                    }, self.queue)
                    let connection = NWConnection(host: NWEndpoint.Host(host), port: NWEndpoint.Port(rawValue: port)!, using: NWParameters(tls: tls))
                    self.connection = connection; self.opening = continuation
                    connection.stateUpdateHandler = { state in
                        switch state {
                        case .ready:
                            self.opening?.resume(); self.opening = nil; self.receive(connection)
                        case let .failed(error): self.finish(error)
                        case .cancelled: self.finish(MQTTConnectionError.closed)
                        default: break
                        }
                    }
                    connection.start(queue: self.queue)
                }
            }
        } onCancel: { Task { await self.close() } }
    }

    func send(_ packet: MQTTPacket) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            queue.async {
                guard !self.closed, let connection = self.connection else {
                    continuation.resume(throwing: MQTTConnectionError.closed); return
                }
                let id = self.nextSendID
                self.nextSendID += 1
                self.pendingSends[id] = continuation
                connection.transmit(Data(packet.encoded())) { error in
                    // Inert after finish: close already resumed this send.
                    guard let continuation = self.pendingSends.removeValue(forKey: id) else { return }
                    if let error { continuation.resume(throwing: error) } else { continuation.resume() }
                }
            }
        }
    }

    private func receive(_ connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { data, _, complete, error in
            do {
                if let data { for packet in try self.decoder.feed(Array(data)) { self.output.yield(packet) } }
                if let error { self.finish(error) }
                else if complete { self.finish(MQTTConnectionError.closed) }
                else { self.receive(connection) }
            } catch { self.finish(error) }
        }
    }
    private func finish(_ error: Error) {
        closed = true
        opening?.resume(throwing: error); opening = nil
        output.finish(throwing: error)
        connection?.cancel(); connection = nil
        // Cancelling also discards queued writes; their sends end here, once.
        let pending = pendingSends
        pendingSends = [:]
        for continuation in pending.values { continuation.resume(throwing: MQTTConnectionError.closed) }
    }
    func close() async {
        await withCheckedContinuation { continuation in
            queue.async { self.finish(MQTTConnectionError.closed); continuation.resume() }
        }
    }
}

/// A single consumer inbox lets a deadline interrupt both network open and ack waits.
actor MQTTInbox {
    private var queued: [MQTTPacket] = []
    private var waiter: CheckedContinuation<MQTTPacket, Error>?
    private var failure: Error?
    func push(_ packet: MQTTPacket) {
        guard failure == nil else { return }
        if let waiter { self.waiter = nil; waiter.resume(returning: packet) } else { queued.append(packet) }
    }
    func fail(_ error: Error) { failure = error; waiter?.resume(throwing: error); waiter = nil; queued = [] }
    func next() async throws -> MQTTPacket {
        if let failure { throw failure }
        if !queued.isEmpty { return queued.removeFirst() }
        return try await withCheckedThrowingContinuation { waiter = $0 }
    }
}
