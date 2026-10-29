import Testing
@testable import Telltale

@Suite struct AppBundleTests {
    @Test func buildHelpNamesTheBuildNumber() {
        #expect(AppBundle.buildHelp(info: ["CFBundleVersion": "synthetic-5"]) == "Build synthetic-5")
        #expect(AppBundle.buildHelp(info: [:]) == nil)
        #expect(AppBundle.buildHelp(info: nil) == nil)
        #expect(AppBundle.buildHelp(info: ["CFBundleVersion": ""]) == nil)
    }
}
