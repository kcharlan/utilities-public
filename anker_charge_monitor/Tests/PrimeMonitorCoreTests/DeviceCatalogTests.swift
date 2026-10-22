import Foundation
import Testing
import PrimeMonitorCore

// Synthetic catalog documents only; names and IDs are invented.
private func document(brands: String = "{}", vendors: String = "{}", devices: String = "{}", extra: String = "") -> Data {
    Data(#"{"schema": 1, "brands": \#(brands), "vendors": \#(vendors), "devices": \#(devices)\#(extra)}"#.utf8)
}
private func rejection(_ data: Data) -> String? {
    do throws(DeviceCatalogError) { _ = try DeviceCatalog.decode(data); return nil } catch { return error.description }
}

@Suite struct DeviceCatalogTests {
    @Test func validKeysNormalizeAndNamesTrim() throws {
        let catalog = try DeviceCatalog.decode(document(
            brands: #"{"0": "Synthetic Zero", "7": " Synthetic Brand \n", "65534": "Synthetic Last"}"#,
            vendors: #"{"0a1b": "Synthetic Vendor", "FFFE": "Synthetic Upper"}"#,
            devices: #"{"0a1b:2C3d": "Synthetic Device"}"#,
            extra: #", "source": {"note": "synthetic"}, "unknown": [1, true, null]"#))
        #expect(catalog.brands == [0: "Synthetic Zero", 7: "Synthetic Brand", 65534: "Synthetic Last"])
        #expect(catalog.vendors == [0x0a1b: "Synthetic Vendor", 0xfffe: "Synthetic Upper"])
        #expect(catalog.devices == [DeviceKey(vendorID: 0x0a1b, productID: 0x2c3d): "Synthetic Device"])
        #expect(DeviceKey(catalogKey: "0a1b:2c3D") == DeviceKey(vendorID: 0x0a1b, productID: 0x2c3d))
        #expect(DeviceKey(vendorID: 0x0a1b, productID: 0x2c3d).catalogKey == "0A1B:2C3D")
        #expect(DeviceCatalog() == (try DeviceCatalog.decode(document())))
        #expect(DeviceCatalog().brands.isEmpty && DeviceCatalog().vendors.isEmpty && DeviceCatalog().devices.isEmpty)
    }

    @Test(arguments: ["01", "007", "-1", "+1", "65535", "65536", "1.0", "", " 1", "1 ", "x", "\u{0661}", "0x1"])
    func rejectedBrandKeys(_ key: String) {
        #expect(rejection(document(brands: #"{"\#(key)": "Synthetic"}"#))
                == "brands entry \"\(key)\": the key must be a decimal brand class from 0 to 65534 without leading zeros.")
    }

    @Test(arguments: ["5ac", "05ac0", "+5ac", "0x5a", "05ag", "", " 5ac", "\u{FF10}5ac"])
    func rejectedVendorKeys(_ key: String) {
        #expect(rejection(document(vendors: #"{"\#(key)": "Synthetic"}"#))
                == "vendors entry \"\(key)\": the key must be four hexadecimal digits.")
    }

    @Test(arguments: ["05ac", "05ac:", ":12ab", "05ac:12ab:0000", "05ac-12ab", "5ac:12ab", "05ac:+2ab", "05ac :12ab"])
    func rejectedDeviceKeys(_ key: String) {
        #expect(rejection(document(devices: #"{"\#(key)": "Synthetic"}"#))
                == "devices entry \"\(key)\": the key must be four hexadecimal vendor digits, a colon and four hexadecimal product digits.")
    }

    @Test func aliasesResolvingToOneKeyAreRejected() {
        #expect(rejection(document(vendors: #"{"0a1b": "Synthetic A", "0A1B": "Synthetic B"}"#))
                == "vendors entry \"0a1b\" repeats entry \"0A1B\".")
        #expect(rejection(document(devices: #"{"0a1b:2C3D": "Synthetic A", "0A1B:2c3d": "Synthetic B"}"#))
                == "devices entry \"0a1b:2C3D\" repeats entry \"0A1B:2c3d\".")
    }

    @Test func namesMustBeNonemptyStringsOfAtMost64Characters() throws {
        // Characters, not scalars or bytes: each thumbs-up with a modifier is one.
        let longest = String(repeating: "\u{1F44D}\u{1F3FD}", count: 64)
        #expect(try DeviceCatalog.decode(document(brands: #"{"7": "\#(longest)"}"#)).brands[7] == longest)
        #expect(rejection(document(brands: #"{"7": "\#(longest)x"}"#)) == "brands entry \"7\": the name is longer than 64 characters.")
        #expect(rejection(document(vendors: #"{"0a1b": " \t\n "}"#)) == "vendors entry \"0a1b\": the name is empty.")
        #expect(rejection(document(vendors: #"{"0a1b": ""}"#)) == "vendors entry \"0a1b\": the name is empty.")
        for value in ["1", "null", "true", "[\"Synthetic\"]", "{\"name\": \"Synthetic\"}"] {
            #expect(rejection(document(devices: #"{"0a1b:2c3d": \#(value)}"#)) == "devices entry \"0a1b:2c3d\": the name must be a string.")
        }
    }

    @Test func documentShapeAndSchemaAreRequired() {
        let schema = "The device catalog \"schema\" must be the integer 1."
        for value in ["\"1\"", "1.0", "1e0", "true", "2", "0", "null"] {
            #expect(rejection(Data(#"{"schema": \#(value), "brands": {}, "vendors": {}, "devices": {}}"#.utf8)) == schema)
        }
        #expect(rejection(Data(#"{"brands": {}, "vendors": {}, "devices": {}}"#.utf8)) == schema)
        #expect(rejection(Data(#"{"schema": 1, "vendors": {}, "devices": {}}"#.utf8)) == "The device catalog needs a \"brands\" object.")
        #expect(rejection(Data(#"{"schema": 1, "brands": {}, "vendors": [], "devices": {}}"#.utf8)) == "The device catalog needs a \"vendors\" object.")
        #expect(rejection(Data(#"{"schema": 1, "brands": {}, "vendors": {}, "devices": "none"}"#.utf8)) == "The device catalog needs a \"devices\" object.")
        #expect(rejection(Data("[]".utf8)) == "The device catalog must be a JSON object.")
        #expect(rejection(Data("1".utf8)) == "The device catalog must be a JSON object.")
        #expect(rejection(Data("{\"schema\": 1,".utf8)) == "The device catalog is not valid JSON.")
        #expect(rejection(Data()) == "The device catalog is not valid JSON.")
        // The typed error also carries the message for alerts and inline errors.
        #expect((DeviceCatalogError.schema as any Error).localizedDescription == schema)
    }

    @Test func labelsResolveDeviceThenBrandThenVendorThenHex() throws {
        let catalog = try DeviceCatalog.decode(document(
            brands: #"{"7": "Synthetic Brand"}"#, vendors: #"{"0a1b": "Synthetic Vendor"}"#,
            devices: #"{"0a1b:2c3d": "Synthetic Desk Lamp"}"#))
        #expect(catalog.label(for: .nothingAttached) == nil)
        #expect(catalog.label(for: .identifying) == "Identifying…")
        #expect(catalog.label(for: .identified(vendorID: 0x0a1b, productID: 0x2c3d, brandClass: 7, modelCode: 3)) == "Synthetic Desk Lamp")
        #expect(catalog.label(for: .identified(vendorID: 0x0a1b, productID: 0x0001, brandClass: 7, modelCode: nil)) == "Synthetic Brand")
        #expect(catalog.label(for: .identified(vendorID: 0x0a1b, productID: 0x0001, brandClass: 8, modelCode: nil)) == "Synthetic Vendor")
        #expect(catalog.label(for: .identified(vendorID: 0x0a1b, productID: 0x0001, brandClass: nil, modelCode: nil)) == "Synthetic Vendor")
        #expect(catalog.label(for: .identified(vendorID: 0x00c2, productID: 0x0e0f, brandClass: 8, modelCode: nil)) == "00C2:0E0F")
        #expect(DeviceCatalog().label(for: .identified(vendorID: 0xabcd, productID: 0x0001, brandClass: 7, modelCode: 1)) == "ABCD:0001")
    }

    @Test func trackedSeedNamesOnlyUpstreamBrandClasses() throws {
        let seed = URL(filePath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appending(path: "Resources/device_catalog.json", directoryHint: .notDirectory)
        let (catalog, object) = try DeviceCatalog.decodeDocument(Data(contentsOf: seed))
        // anker-solix-api 9e72894 `_A2345_0a00` key `be` comment; 11 and 16 are VID-only there.
        #expect(catalog.brands == [1: "Apple", 2: "Samsung", 3: "Xiaomi", 4: "Huawei", 10: "Anker", 12: "HP",
                                   13: "Dell", 14: "Lenovo", 15: "Microsoft", 17: "ASUS", 18: "MSI", 19: "Razer"])
        #expect(catalog.vendors.isEmpty && catalog.devices.isEmpty)
        let source = try #require(object["source"] as? [String: String])
        #expect(source["commit"] == "9e72894181aef868e7b3ed0ba05bd322d54bb5d7")
        #expect(source["path"] == "src/anker_solix_api/mqttmap.py")
    }
}
