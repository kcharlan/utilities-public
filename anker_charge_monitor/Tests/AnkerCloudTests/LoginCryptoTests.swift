import CommonCrypto
import CryptoKit
import Foundation
import Testing
@testable import AnkerCloud

struct LoginVectors: Decodable {
    let privateScalarHex: String
    let publicKeyHex: String
    let sharedSecretHex: String
    let passwordB64: String
}

func loadVectors() throws -> LoginVectors {
    let url = try #require(Bundle.module.url(forResource: "login_vectors", withExtension: "json", subdirectory: "Fixtures"))
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    return try decoder.decode(LoginVectors.self, from: Data(contentsOf: url))
}

func bytes(hex: String) throws -> Data {
    let chars = Array(hex)
    #expect(chars.count.isMultiple(of: 2))
    return try Data(stride(from: 0, to: chars.count, by: 2).map { index in
        try #require(UInt8(String(chars[index...index + 1]), radix: 16))
    })
}

@Test func cryptoMatchesUpstreamVectors() throws {
    let v = try loadVectors()
    let crypto = LoginCrypto(privateKey: try .init(rawRepresentation: bytes(hex: v.privateScalarHex)))
    #expect(crypto.publicKeyHex == v.publicKeyHex)
    #expect(crypto.sharedSecretHex == v.sharedSecretHex)
    #expect(try crypto.encryptPassword("synthetic-password-123") == v.passwordB64)
}

@Test func encryptionPadsEmptyAlignedAndUTF8Passwords() throws {
    let v = try loadVectors()
    let crypto = LoginCrypto(privateKey: try .init(rawRepresentation: bytes(hex: v.privateScalarHex)))
    let key = try bytes(hex: v.sharedSecretHex)
    for password in ["", "0123456789abcdef", "synthetic-🔋-pässword", String(repeating: "x", count: 100)] {
        let ciphertext = try #require(Data(base64Encoded: crypto.encryptPassword(password)))
        #expect(ciphertext.count == (password.utf8.count / 16 + 1) * 16)
        // Decrypt independently with the upstream fixture's raw ECDH bytes.
        var plaintext = [UInt8](repeating: 0, count: ciphertext.count)
        var count = 0
        let status = key.withUnsafeBytes { keyBytes in
            ciphertext.withUnsafeBytes { input in
                CCCrypt(CCOperation(kCCDecrypt), CCAlgorithm(kCCAlgorithmAES), CCOptions(kCCOptionPKCS7Padding),
                        keyBytes.baseAddress, key.count, keyBytes.baseAddress,
                        input.baseAddress, ciphertext.count, &plaintext, ciphertext.count, &count)
            }
        }
        #expect(status == kCCSuccess)
        #expect(Data(plaintext.prefix(count)) == Data(password.utf8))
    }
}

@Test func defaultCryptoUsesFreshEphemeralKeys() {
    let first = LoginCrypto()
    let second = LoginCrypto()
    #expect(first.publicKeyHex.count == 130)
    #expect(first.publicKeyHex.hasPrefix("04"))
    #expect(first.publicKeyHex != second.publicKeyHex)
}
