public struct StatusSourceSummary: Sendable, Equatable {
    public var id: String
    public var displayName: String
    public var defaultWatchedComponents: [String]

    public init(id: String, displayName: String, defaultWatchedComponents: [String]) {
        self.id = id
        self.displayName = displayName
        self.defaultWatchedComponents = defaultWatchedComponents
    }
}
