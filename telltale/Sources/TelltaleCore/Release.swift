/// Identifiers from spec section 3. `Resources/Info.plist` and the deploy tool
/// restate them separately; `ReleaseTests` compares the plist to this type.
public enum TelltaleRelease {
    public static let version = "0.2.1"
    public static let displayName = "Telltale"
    public static let bundleIdentifier = "local.utilities.telltale"
    public static let collectorLabel = "local.utilities.telltale.collector"
}
