import Foundation
import Security
import Testing
@testable import AnkerCloud

func syntheticIdentityPEM(commonName: String = "PrimeMonitor Synthetic Test") throws -> (certificate: String, key: String) {
    var error: Unmanaged<CFError>?
    let key = try #require(SecKeyCreateRandomKey([
        kSecAttrKeyType: kSecAttrKeyTypeRSA, kSecAttrKeySizeInBits: 2048,
        kSecAttrIsPermanent: false
    ] as CFDictionary, &error))
    let bytes = try #require(SecKeyCopyExternalRepresentation(key, &error)) as Data
    let pem = "-----BEGIN RSA PRIVATE KEY-----\n" + bytes.base64EncodedString(options: .lineLength64Characters) + "\n-----END RSA PRIVATE KEY-----\n"
    // Self-sign this throwaway key without writing the private key to a file.
    let process = Process()
    process.executableURL = URL(filePath: "/usr/bin/openssl", directoryHint: .notDirectory)
    process.arguments = ["req", "-new", "-x509", "-sha256", "-key", "/dev/stdin", "-subj", "/CN=" + commonName, "-days", "1"]
    if commonName.hasSuffix(".invalid") {
        process.arguments! += ["-addext", "subjectAltName=DNS:" + commonName, "-addext", "extendedKeyUsage=serverAuth"]
    }
    let input = Pipe(), output = Pipe(), diagnostics = Pipe()
    process.standardInput = input; process.standardOutput = output; process.standardError = diagnostics
    try process.run()
    try input.fileHandleForWriting.write(contentsOf: Data(pem.utf8)); try input.fileHandleForWriting.close()
    let certificateBytes = try output.fileHandleForReading.readToEnd()
    let certificate = try #require(certificateBytes)
    process.waitUntilExit()
    #expect(process.terminationStatus == 0)
    return (try #require(String(data: certificate, encoding: .utf8)), pem)
}

private func observedIdentityDirectory(_ directory: URL) throws -> [String] {
    do { return try FileManager.default.contentsOfDirectory(atPath: directory.path(percentEncoded: false)).sorted() }
    catch let error as CocoaError where error.code == .fileReadNoSuchFile { return [] }
}

@Test func identityBuildsFromPEMWithoutDiskOrKeychainPersistence() throws {
    let legacyDirectory = FileManager.default.temporaryDirectory.appending(path: "PrimeMonitor", directoryHint: .isDirectory)
    let before = try observedIdentityDirectory(legacyDirectory)
    let pem = try syntheticIdentityPEM()
    let identity = try TLSIdentity(certificatePEM: pem.certificate, privateKeyPEM: pem.key)
    var privateKey: SecKey?, certificate: SecCertificate?
    #expect(SecIdentityCopyPrivateKey(identity.identity, &privateKey) == errSecSuccess)
    #expect(SecIdentityCopyCertificate(identity.identity, &certificate) == errSecSuccess)
    #expect(privateKey != nil && certificate != nil)
    // Exercise actual Security operations rather than replacing them with mocks.
    var signatureError: Unmanaged<CFError>?
    let challenge = Data("synthetic identity proof".utf8)
    let importedKey = try #require(privateKey)
    let importedCertificate = try #require(certificate)
    let signature = try #require(SecKeyCreateSignature(importedKey, .rsaSignatureMessagePKCS1v15SHA256, challenge as CFData, &signatureError))
    let publicKey = try #require(SecCertificateCopyKey(importedCertificate))
    #expect(SecKeyVerifySignature(publicKey, .rsaSignatureMessagePKCS1v15SHA256, challenge as CFData, signature, &signatureError))
    let certificateBody = pem.certificate.components(separatedBy: .newlines).filter { !$0.hasPrefix("-----") }.joined()
    #expect(SecCertificateCopyData(try #require(certificate)) as Data == Data(base64Encoded: certificateBody))
    let attributes = try #require(SecKeyCopyAttributes(importedKey) as? [CFString: Any])
    // SecKeyCreateWithData never inserts keys (SecKey.h). This SDK reports
    // isPermanent=true even for its floating RSA keys; test real Keychain
    // persistence below instead of treating that attribute as a storage probe.
    #expect(attributes[kSecAttrKeySizeInBits] as? Int == 2048)
    let label = try #require(attributes[kSecAttrApplicationLabel])
    var result: CFTypeRef?
    // Scope the real Keychain lookup to this freshly generated synthetic key.
    #expect(SecItemCopyMatching([
        kSecClass: kSecClassKey, kSecAttrApplicationLabel: label,
        kSecReturnPersistentRef: true, kSecMatchLimit: kSecMatchLimitOne
    ] as CFDictionary, &result) == errSecItemNotFound)
    #expect(result == nil)
    #expect(try observedIdentityDirectory(legacyDirectory) == before,
            "Identity material must never reach disk, including while alive")
    withExtendedLifetime(identity) {}
}

@Test func identityDirectoryObservationSortsEntriesAndRejectsNonDirectory() throws {
    let directory = FileManager.default.temporaryDirectory.appending(path: "prime-synthetic-observation-" + UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    #expect(try observedIdentityDirectory(directory).isEmpty)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    for name in ["z", "a"] { try Data().write(to: directory.appending(path: name)) }
    #expect(try observedIdentityDirectory(directory) == ["a", "z"])
    #expect(throws: CocoaError.self) { try observedIdentityDirectory(directory.appending(path: "a")) }
}

@Test func mismatchedCertificateAndPrivateKeyAreRejected() throws {
    let pem = try syntheticIdentityPEM()
    let other = try syntheticIdentityPEM()
    #expect(throws: TLSIdentityError.mismatchedIdentity) {
        _ = try TLSIdentity(certificatePEM: pem.certificate, privateKeyPEM: other.key)
    }
}

@Test func rejectsMalformedAndMultiplePEMObjectsWithSanitizedErrors() throws {
    let pem = try syntheticIdentityPEM()
    let malformedKeys = [
        "private-synthetic-marker", pem.key + pem.key,
        pem.key.replacingOccurrences(of: "RSA PRIVATE KEY", with: "PRIVATE KEY"),
        pem.key.replacingOccurrences(of: "\n", with: "\n!"),
        pem.key.replacingOccurrences(of: "-----END RSA PRIVATE KEY-----", with: "-----END CERTIFICATE-----"),
        "prefix" + pem.key, pem.key + "suffix",
        "-----BEGIN RSA PRIVATE KEY-----\nMAA=\n-----END RSA PRIVATE KEY-----"
    ]
    for key in malformedKeys {
        do {
            _ = try TLSIdentity(certificatePEM: pem.certificate, privateKeyPEM: key)
            Issue.record("Accepted malformed private key")
        } catch {
            #expect(error is TLSIdentityError)
            #expect(!String(describing: error).contains("private-synthetic-marker"))
            #expect(!String(describing: error).contains("-----"))
        }
    }
    for certificate in ["invalid synthetic certificate", pem.certificate + pem.certificate,
                        "-----BEGIN CERTIFICATE-----\nMAA=\n-----END CERTIFICATE-----"] {
        #expect(throws: TLSIdentityError.self) {
            _ = try TLSIdentity(certificatePEM: certificate, privateKeyPEM: pem.key)
        }
    }
    _ = try TLSIdentity(certificatePEM: pem.certificate.replacingOccurrences(of: "\n", with: "\r\n"), privateKeyPEM: pem.key)
}
