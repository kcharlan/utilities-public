// Telltale's app composition (spec sections 9.1 and 9.3, plan Review Focus "Non-installed collector
// launch", ruling R24), plus Telltale additions covering the ported ApplicationMenu and reopen
// behavior: brew_version/Tests/BrewVersionAppTests/NativeActionsTests.swift's
// appKitLifecycleRetainsStandardQuitAndEditingCommands and normalAppReopenShowsPopoverWithOrWithoutSettingsVisible
// at 5e1e642 (outside Task 11's port selection, adapted here).
import AppKit
import Foundation
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

@MainActor final class PopoverPresenterStub: PopoverPresenting {
    var opens = 0
    func showPopover() { opens += 1 }
}

/// A scratch world with injected paths, a fake `launchctl`, a notification stub and two synthetic
/// bundles that both carry Telltale's real identifier: one where `installedAppURL` points (standing
/// in for /Applications) and one in a build folder.
@MainActor private final class DelegateHarness {
    let directory: URL
    let paths: TelltalePaths
    let runner = FakeCommandRunner()
    let service = NotificationServiceStub()
    let presenter = PopoverPresenterStub()
    let installedApp: URL
    let installedExecutable: URL
    let buildExecutable: URL
    var quits = 0
    var failures: [String] = []

    init(_ directory: URL) throws {
        self.directory = directory
        paths = PanelWorld.paths(directory)
        installedApp = directory.appending(path: "Applications/Telltale.app", directoryHint: .isDirectory)
        installedExecutable = try Self.makeApp(installedApp)
        buildExecutable = try Self.makeApp(directory.appending(path: "build/release/Telltale.app", directoryHint: .isDirectory))
    }

    static func makeApp(_ app: URL) throws -> URL {
        let macOS = app.appending(path: "Contents/MacOS", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: macOS, withIntermediateDirectories: true)
        let info: [String: Any] = ["CFBundleExecutable": "Telltale", "CFBundleIdentifier": TelltaleRelease.bundleIdentifier, "CFBundlePackageType": "APPL"]
        try PropertyListSerialization.data(fromPropertyList: info, format: .xml, options: 0).write(to: app.appending(path: "Contents/Info.plist"))
        let binary = macOS.appending(path: "Telltale", directoryHint: .notDirectory)
        try Data("#!/bin/sh\nexit 0\n".utf8).write(to: binary)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: binary.path)
        return binary
    }

    func delegate(current: URL? = nil) -> AppDelegate {
        AppDelegate(
            paths: paths, currentExecutable: current ?? installedExecutable, installedAppURL: installedApp, runner: runner,
            sources: PanelWorld.sources, notificationService: service, uid: 4_242, calendar: Synth.newYork,
            eventSources: [], watchFiles: false,
            makeStatus: { [presenter] _, _ in presenter },
            quit: { [unowned self] in quits += 1 },
            reportFailure: { [unowned self] in failures.append($0) })
    }

    func launch(_ delegate: AppDelegate) {
        delegate.applicationDidFinishLaunching(Notification(name: NSApplication.didFinishLaunchingNotification))
    }

    func terminate(_ delegate: AppDelegate) {
        delegate.applicationWillTerminate(Notification(name: NSApplication.willTerminateNotification))
    }

    /// launchctl subcommands that change launchd state (everything but `print`).
    var stateChanges: [String] { runner.calls.compactMap(\.arguments.first).filter { $0 != "print" } }
    var plistExists: Bool { FileManager.default.fileExists(atPath: LaunchAgentManager(paths: paths, uid: 4_242, runner: runner).plistURL.path) }
    var databaseExists: Bool { FileManager.default.fileExists(atPath: paths.database.path) }
}

@MainActor private func withDelegate(_ body: (DelegateHarness) async throws -> Void) async throws {
    try await withAsyncScratchDirectory { try await body(try DelegateHarness($0)) }
}

@MainActor @Suite(.serialized) struct AppDelegateTests {
    @Test func launchRestoresCollectorWhenEnabledAndMissing() async throws {
        try await withDelegate { h in
            let delegate = h.delegate()
            h.launch(delegate)
            defer { h.terminate(delegate) }
            #expect(h.stateChanges.filter { $0 == "bootstrap" }.count == 1)
            #expect(h.plistExists && h.failures.isEmpty && h.quits == 0)
            #expect(delegate.isInstalledCopy && delegate.monitorStarted)
            // The dashboard's collector view may change launchd state only in the installed copy (R24).
            #expect(delegate.dashboard?.model.collector.canManage == true)
            let plist = try TestPaths.plistDictionary(at: LaunchAgentManager(paths: h.paths, uid: 4_242, runner: h.runner).plistURL)
            #expect((plist["ProgramArguments"] as? [String])?.first == h.installedExecutable.path)
            #expect(await eventually { h.service.authorizationRequests == 1 })

            // A relaunch with the plist in place leaves it alone.
            h.terminate(delegate)
            let again = h.delegate()
            h.launch(again)
            defer { h.terminate(again) }
            #expect(h.stateChanges.filter { $0 == "bootstrap" }.count == 1)
        }
    }

    @Test func launchDoesNotAutoEnableOutsideApplications() async throws {
        try await withDelegate { h in
            // A build-folder bundle carrying the real identifier.
            let delegate = h.delegate(current: h.buildExecutable)
            h.launch(delegate)
            defer { h.terminate(delegate) }
            await delegate.liveStore?.refresh()
            #expect(h.stateChanges.isEmpty)
            #expect(!h.plistExists && !delegate.isInstalledCopy)
            #expect(delegate.dashboard?.model.collector.canManage == false)
            // Through a symlink to the installed copy, it is the installed copy.
            let link = h.directory.appending(path: "linked-Telltale", directoryHint: .notDirectory)
            try FileManager.default.createSymbolicLink(at: link, withDestinationURL: h.installedExecutable)
            h.terminate(delegate)
            let linked = h.delegate(current: link)
            #expect(linked.isInstalledCopy)
        }
    }

    @Test func collectorOffByChoiceIsNotTurnedOn() async throws {
        try await withDelegate { h in
            try Store.open(h.paths.database, mode: .readWrite).set(.collectorEnabled, false)
            let delegate = h.delegate()
            h.launch(delegate)
            defer { h.terminate(delegate) }
            await delegate.liveStore?.refresh()
            #expect(h.stateChanges.isEmpty && !h.plistExists)
            #expect(delegate.liveStore?.snapshot.footer == "Collector off. Turn it on to keep watching.")
        }
    }

    @Test func secondUIInstanceQuits() async throws {
        try await withDelegate { h in
            let first = h.delegate()
            h.launch(first)
            let second = h.delegate()
            h.launch(second)
            #expect(h.quits == 1)
            #expect(second.liveStore == nil)
            h.terminate(first)
            let third = h.delegate()
            h.launch(third)
            defer { h.terminate(third) }
            #expect(h.quits == 1 && third.liveStore != nil)
        }
    }

    /// R24: outside the installed bundle the panel shows health read-only; nothing posts, nothing
    /// writes, and the database isn't created.
    @Test func nonInstalledCopyPostsNothingAndCreatesNoDatabase() async throws {
        try await withDelegate { h in
            // Not loaded and no runs: the installed copy would post a health notification.
            h.runner.respond(to: "print", with: CommandResult(status: 113, stdout: "", stderr: "Could not find service\n"))
            h.service.status = .authorized
            let delegate = h.delegate(current: h.buildExecutable)
            h.launch(delegate)
            defer { h.terminate(delegate) }
            #expect(!delegate.monitorStarted)
            for _ in 0..<3 { await delegate.liveStore?.refresh() }
            // No database yet, but the panel still shows that the collector isn't loaded.
            #expect(delegate.liveStore?.snapshot.collector == .red)
            #expect(delegate.liveStore?.snapshot.footer == "Telltale's collector isn't loaded. Open the Collector view to turn it back on.")
            #expect(h.service.requests.isEmpty && h.service.authorizationRequests == 0)
            #expect(!h.databaseExists && h.stateChanges.isEmpty)

            // With a database, health reads it but writes nothing back.
            try PanelWorld.seed(h.paths)
            let before = try Data(contentsOf: h.paths.database)
            for _ in 0..<3 { await delegate.liveStore?.refresh() }
            #expect(delegate.liveStore?.snapshot.collector == .red)
            #expect(delegate.liveStore?.snapshot.footer == "Telltale's collector isn't loaded. Open the Collector view to turn it back on.")
            #expect(try Store.open(h.paths.database, mode: .readOnly).value(.collectorHealthNotice) == nil)
            #expect(try Data(contentsOf: h.paths.database) == before)
            #expect(h.service.requests.isEmpty)
        }
    }

    @Test func normalAppReopenShowsPanel() async throws {
        try await withDelegate { h in
            let delegate = h.delegate()
            h.launch(delegate)
            defer { h.terminate(delegate) }
            #expect(h.presenter.opens == 0)
            #expect(delegate.applicationShouldHandleReopen(NSApplication.shared, hasVisibleWindows: false))
            #expect(delegate.applicationShouldHandleReopen(NSApplication.shared, hasVisibleWindows: true))
            #expect(h.presenter.opens == 2)
            // A notification click opens the panel too.
            delegate.notifier.showPopover?()
            #expect(h.presenter.opens == 3)
        }
    }

    @Test func appKitLifecycleRetainsStandardQuitAndEditingCommands() {
        let menu = ApplicationMenu.make()
        #expect(menu.items.first?.submenu?.title == "Telltale")
        let commands = menu.items.flatMap { $0.submenu?.items ?? [] }
        #expect(commands.first(where: { $0.keyEquivalent == "q" })?.title == "Quit Telltale")
        #expect(commands.first(where: { $0.keyEquivalent == "q" })?.action == #selector(NSApplication.terminate(_:)))
        #expect(commands.first(where: { $0.keyEquivalent == "v" })?.action == #selector(NSText.paste(_:)))
        #expect(commands.first(where: { $0.keyEquivalent == "a" })?.action == #selector(NSText.selectAll(_:)))
        let close = commands.first { $0.keyEquivalent == "w" }
        #expect(close?.action == #selector(NSWindow.performClose(_:)))
        #expect(close != nil && close?.target == nil)
        let undo = commands.first { $0.keyEquivalent == "z" && $0.keyEquivalentModifierMask == [.command] }
        let redo = commands.first { $0.keyEquivalent == "z" && $0.keyEquivalentModifierMask == [.command, .shift] }
        #expect(undo?.action == Selector(("undo:")))
        #expect(redo?.action == Selector(("redo:")))
    }
}
