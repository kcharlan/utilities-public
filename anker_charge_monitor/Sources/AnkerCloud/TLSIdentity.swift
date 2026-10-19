import Foundation
import Security

/// Connection-owned, memory-only identity. Replaces mqtt.py create_client/
/// cleanup PEM files (anker-solix-api 8a5222b) with supported Security objects.
public final class TLSIdentity {
    public let identity: SecIdentity

    public init(certificatePEM: String, privateKeyPEM: String) throws {
        let keyData = try Self.decodePEM(privateKeyPEM, label: "RSA PRIVATE KEY")
        let certificateData = try Self.decodePEM(certificatePEM, label: "CERTIFICATE")
        // Security derives the RSA modulus size from PKCS#1, not DER byte count.
        let attributes: [CFString: Any] = [
            kSecAttrKeyType: kSecAttrKeyTypeRSA,
            kSecAttrKeyClass: kSecAttrKeyClassPrivate,
            kSecAttrIsPermanent: false
        ]
        guard let key = SecKeyCreateWithData(keyData as CFData, attributes as CFDictionary, nil) else {
            throw TLSIdentityError.invalidPrivateKey
        }
        guard let certificate = SecCertificateCreateWithData(nil, certificateData as CFData) else {
            throw TLSIdentityError.invalidCertificate
        }
        // This API checks the public key against the certificate and retains
        // both objects without inserting a Keychain item.
        guard let identity = SecIdentityCreate(nil, certificate, key) else {
            throw TLSIdentityError.mismatchedIdentity
        }
        self.identity = identity
    }

    private static func decodePEM(_ pem: String, label: String) throws -> Data {
        let lines = pem.trimmingCharacters(in: .whitespacesAndNewlines)
            .components(separatedBy: "\n").map { $0.hasSuffix("\r") ? String($0.dropLast()) : $0 }
        guard lines.count >= 3, lines.first == "-----BEGIN \(label)-----",
              lines.last == "-----END \(label)-----" else { throw TLSIdentityError.invalidPEM }
        let bodyLines = lines.dropFirst().dropLast()
        guard bodyLines.allSatisfy({ !$0.isEmpty }) else { throw TLSIdentityError.invalidPEM }
        let body = bodyLines.joined()
        guard let data = Data(base64Encoded: body), !data.isEmpty,
              data.base64EncodedString() == body else { throw TLSIdentityError.invalidPEM }
        // Require exactly one DER SEQUENCE before Security parses its contents.
        let bytes = Array(data)
        guard bytes.count >= 2, bytes[0] == 0x30 else { throw TLSIdentityError.invalidPEM }
        let lengthByte = Int(bytes[1])
        if lengthByte < 128 {
            guard lengthByte == bytes.count - 2 else { throw TLSIdentityError.invalidPEM }
        } else {
            let count = lengthByte & 0x7f
            guard count > 0, count <= MemoryLayout<Int>.size - 1,
                  bytes.count >= 2 + count, bytes[2] != 0 else { throw TLSIdentityError.invalidPEM }
            let length = bytes[2..<(2 + count)].reduce(0) { ($0 << 8) | Int($1) }
            guard length >= 128, length == bytes.count - 2 - count else { throw TLSIdentityError.invalidPEM }
        }
        return data
    }
}

/// Fixed diagnostics deliberately exclude PEM values and Security error details.
enum TLSIdentityError: Error, CustomStringConvertible {
    case invalidPEM, invalidPrivateKey, invalidCertificate, mismatchedIdentity
    var description: String {
        switch self {
        case .invalidPEM: "TLS identity has invalid PEM encoding"
        case .invalidPrivateKey: "TLS identity has an invalid RSA private key"
        case .invalidCertificate: "TLS identity has an invalid certificate"
        case .mismatchedIdentity: "TLS identity certificate and private key do not match"
        }
    }
}
