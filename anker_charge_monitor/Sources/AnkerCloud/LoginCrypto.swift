import CommonCrypto
import CryptoKit
import Foundation

/// Ports anker-solix-api `session.py`, AnkerSolixClientSession's key agreement,
/// `_rawPublicKey` and `_encryptApiData`, commit 8a5222b. The server point is
/// public protocol material, shared by the EU and COM servers.
public struct LoginCrypto: Sendable {
    private static let serverPublicKey = try! P256.KeyAgreement.PublicKey(x963Representation: Data([
        0x04, 0xc5, 0xc0, 0x0c, 0x4f, 0x8d, 0x11, 0x97, 0xcc, 0x7c, 0x31, 0x67, 0xc5, 0x2b, 0xf7, 0xac,
        0xb0, 0x54, 0xd7, 0x22, 0xf0, 0xef, 0x08, 0xdc, 0xd7, 0xe0, 0x88, 0x32, 0x36, 0xe0, 0xd7, 0x2a,
        0x38, 0x68, 0xd9, 0x75, 0x0c, 0xb4, 0x7f, 0xa4, 0x61, 0x92, 0x48, 0xf3, 0xd8, 0x3f, 0x0f, 0x66,
        0x26, 0x71, 0xda, 0xdc, 0x6e, 0x2d, 0x31, 0xc2, 0xf4, 0x1d, 0xb0, 0x16, 0x16, 0x51, 0xc7, 0xc0,
        0x76
    ]))

    public let publicKeyHex: String
    private let sharedKey: Data

    public init(privateKey: P256.KeyAgreement.PrivateKey = .init()) {
        publicKeyHex = privateKey.publicKey.x963Representation.map { String(format: "%02x", $0) }.joined()
        // Validated P-256 keys always agree. No KDF: upstream uses the raw X coordinate.
        let secret = try! privateKey.sharedSecretFromKeyAgreement(with: Self.serverPublicKey)
        sharedKey = secret.withUnsafeBytes { Data($0) }
    }

    var sharedSecretHex: String {
        sharedKey.map { String(format: "%02x", $0) }.joined()
    }

    public func encryptPassword(_ password: String) throws -> String {
        let input = Data(password.utf8)
        let capacity = input.count + kCCBlockSizeAES128
        var output = [UInt8](repeating: 0, count: capacity)
        var count = 0
        let status = sharedKey.withUnsafeBytes { key in
            input.withUnsafeBytes { plaintext in
                CCCrypt(CCOperation(kCCEncrypt), CCAlgorithm(kCCAlgorithmAES), CCOptions(kCCOptionPKCS7Padding),
                        key.baseAddress, kCCKeySizeAES256, key.baseAddress,
                        plaintext.baseAddress, input.count, &output, capacity, &count)
            }
        }
        guard status == kCCSuccess else { throw AnkerError.malformed }
        return Data(output.prefix(count)).base64EncodedString()
    }
}
