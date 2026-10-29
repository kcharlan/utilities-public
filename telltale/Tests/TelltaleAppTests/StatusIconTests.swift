// Port: brew_version/Tests/BrewVersionAppTests/NativeActionsTests.swift, StatusIcon cases and their helpers, 5e1e642.
// Adaptation: the lamp lens replaces the mug and the panel snapshot replaces StatusPresentation;
// the dot takes the most severe lamp's color, resolved for the bar's appearance.
//
// Source tests at 5e1e642 -> destination tests:
// - idleStatusIconIsTemplateMug -> idleStatusIconIsTemplateLens
// - alertStatusIconFollowsBarAppearanceAndKeepsAmberDot -> alertStatusIconFollowsBarAppearanceAndKeepsAmberDot
// - statusObservationPublishesAmberChanges -> statusObservationPublishesSnapshotChanges
// - nativeActionPolicies (its StatusPresentation accessibility lines) -> accessibilityNamesLitLamps
// Helpers: IconPixel, statusIconPixels.
// Telltale additions: templateWhenNothingLit, dotUsesMostSevereColor.
import AppKit
import Testing
import TelltaleCore
import TelltaleTestSupport
@testable import Telltale

private func snapshot(_ lit: [Signal: LampColor], unacknowledged: [Signal: LampColor]? = nil) -> PanelSnapshot {
    var snapshot = PanelSnapshot.waiting(sources: PanelWorld.sources, footer: "")
    for (signal, color) in lit { snapshot.lamps[signal] = color }
    snapshot.unacknowledged = unacknowledged ?? lit
    snapshot.labels[.provider] = "Example Status"
    return snapshot
}

@MainActor struct StatusIconTests {
    @Test func acknowledgedLampsDrawARing() throws {
        let image = try #require(StatusIcon.image(for: snapshot([.errors: .red], unacknowledged: [:])))
        for appearance in [NSAppearance.Name.darkAqua, .aqua] {
            let red = try lampRGB(.red, appearance: appearance)
            let pixels = try statusIconPixels(image, appearance: appearance).filter { $0.matches(red) }
            let diameter = StatusIcon.dotDiameter
            let dot = NSRect(x: image.size.width - diameter, y: image.size.height - diameter, width: diameter, height: diameter)
            #expect(!pixels.isEmpty && pixels.allSatisfy { dot.contains(NSPoint(x: $0.x, y: $0.y)) })
            #expect(!pixels.contains { abs($0.x - dot.midX) < 0.5 && abs($0.y - dot.midY) < 0.5 })
        }
    }
    @Test func acknowledgedRingHoleIsWideEnoughToTellFromAFilledDot() throws {
        // A 7 pt dot left a 4 pt hole that read as filled in the menu bar. The ring's
        // hole must stay clear for at least 6 pt across; the filled dot covers it.
        let diameter = StatusIcon.dotDiameter
        func inHole(_ pixel: IconPixel, _ size: NSSize) -> Bool {
            hypot(pixel.x - (size.width - diameter / 2), pixel.y - (size.height - diameter / 2)) < 3
        }
        let ring = try #require(StatusIcon.image(for: snapshot([.errors: .red], unacknowledged: [:])))
        let filled = try #require(StatusIcon.image(for: snapshot([.errors: .red])))
        for appearance in [NSAppearance.Name.darkAqua, .aqua] {
            #expect(!(try statusIconPixels(ring, appearance: appearance)).contains { inHole($0, ring.size) })
            let red = try lampRGB(.red, appearance: appearance)
            #expect((try statusIconPixels(filled, appearance: appearance)).filter { inHole($0, filled.size) }.allSatisfy { $0.matches(red) })
        }
    }
    @Test func newAlertFillsTheDotInItsColorOverAnAcknowledgedRed() throws {
        let image = try #require(StatusIcon.image(for: snapshot([.errors: .red, .speed: .amber], unacknowledged: [.speed: .amber])))
        for appearance in [NSAppearance.Name.darkAqua, .aqua] {
            let pixels = try statusIconPixels(image, appearance: appearance)
            let amber = try lampRGB(.amber, appearance: appearance), red = try lampRGB(.red, appearance: appearance)
            #expect(pixels.contains { $0.matches(amber) })
            #expect(!pixels.contains { $0.matches(red) })
        }
    }
    @Test func accessibilityMarksAcknowledgedLamps() {
        #expect(StatusIcon.accessibility(for: snapshot([.errors: .red, .speed: .amber], unacknowledged: [.speed: .amber])) == "Telltale: Speed amber, Errors red (acknowledged).")
    }
    @Test func idleStatusIconIsTemplateLens() throws {
        let idle = try #require(StatusIcon.image(for: snapshot([:])))
        #expect(idle.isTemplate)
        #expect(idle.accessibilityDescription == "Telltale: Nothing to report.")
    }
    @Test func templateWhenNothingLit() throws {
        // A waiting or quiet panel, and Collector merely running, stay a plain template.
        let quiet = try #require(StatusIcon.image(for: snapshot([:])))
        var running = snapshot([:]); running.collector = .green
        let image = try #require(StatusIcon.image(for: running))
        #expect(quiet.isTemplate && image.isTemplate)
        #expect(image.size == quiet.size)
        let pixels = try statusIconPixels(image, appearance: .aqua)
        #expect(!pixels.isEmpty, "the lens draws something")
    }
    @Test func alertStatusIconFollowsBarAppearanceAndKeepsAmberDot() throws {
        // macOS 27 renders a tinted template status image black, so the alert
        // lens must carry its own colours and resolve them at draw time.
        let idle = try #require(StatusIcon.image(for: snapshot([:])))
        let alert = try #require(StatusIcon.image(for: snapshot([.speed: .amber, .load: .amber])))
        #expect(!alert.isTemplate)
        #expect(alert.accessibilityDescription == "Telltale: Speed amber, Load amber.")
        #expect(alert.size.height == idle.size.height && alert.size.width > idle.size.width)
        let diameter = StatusIcon.dotDiameter
        let corner = NSRect(x: alert.size.width - diameter, y: alert.size.height - diameter, width: diameter, height: diameter)
        let lensPixels = try statusIconPixels(idle, appearance: .aqua).count
        for (appearance, outlineIsLight) in [(NSAppearance.Name.darkAqua, true), (.aqua, false), (.vibrantDark, true), (.vibrantLight, false)] {
            let pixels = try statusIconPixels(alert, appearance: appearance)
            let expected = try lampRGB(.amber, appearance: appearance)
            let amber = pixels.filter { $0.matches(expected) }, outline = pixels.filter { !$0.matches(expected) }
            #expect(!amber.isEmpty, "no amber dot in \(appearance.rawValue)")
            // The dot sits in the top-right corner.
            #expect(amber.allSatisfy { corner.contains(NSPoint(x: $0.x, y: $0.y)) })
            let brightness = outline.map(\.brightness).reduce(0, +) / Double(max(outline.count, 1))
            // The dot's clearance cuts the lens's corner, but most of the lens remains.
            #expect(outline.count * 2 > lensPixels, "no lens outline in \(appearance.rawValue)")
            #expect(outlineIsLight ? brightness > 0.8 : brightness < 0.3, "outline brightness \(brightness) in \(appearance.rawValue)")
        }
    }
    @Test func dotUsesMostSevereColor() throws {
        for (lit, color) in [([Signal.speed: LampColor.blue], LampColor.blue), ([.speed: .blue, .load: .amber], .amber),
                             ([.speed: .amber, .errors: .red, .link: .blue], .red), ([.collector: .red], .red)] {
            let image = try #require(StatusIcon.image(for: snapshot(lit)))
            for appearance in [NSAppearance.Name.darkAqua, .aqua] {
                let pixels = try statusIconPixels(image, appearance: appearance)
                let expected = try lampRGB(color, appearance: appearance)
                #expect(pixels.contains { $0.matches(expected) }, "no \(color) dot in \(appearance.rawValue)")
                for other in LampColor.allCases where other != color {
                    let rgb = try lampRGB(other, appearance: appearance)
                    #expect(!pixels.contains { $0.matches(rgb) }, "\(other) pixels for a \(color) dot in \(appearance.rawValue)")
                }
            }
        }
    }
    @Test func accessibilityNamesLitLamps() {
        #expect(StatusIcon.accessibility(for: snapshot([:])) == "Telltale: Nothing to report.")
        #expect(StatusIcon.accessibility(for: snapshot([.speed: .amber])) == "Telltale: Speed amber.")
        // Strip order, with the status source's caption for Provider and Collector last.
        #expect(StatusIcon.accessibility(for: snapshot([.collector: .red, .provider: .amber, .speed: .blue]))
            == "Telltale: Speed blue, Example Status amber, Collector red.")
    }
    @Test func statusObservationPublishesSnapshotChanges() async throws {
        try await withAsyncScratchDirectory { directory in
            let paths = PanelWorld.paths(directory)
            let writer = try PanelWorld.seed(paths)
            let live = PanelWorld.live(paths)
            var values: [String] = []
            let observation = StatusObservation(store: live) { values.append(StatusIcon.accessibility(for: $0)) }
            #expect(values == ["Telltale: Nothing to report."])
            try PanelWorld.addAlert(writer)
            await live.refresh()
            for _ in 0..<100 where values.count < 2 { await Task.yield() }
            #expect(values.last == "Telltale: Speed amber.")
            withExtendedLifetime(observation) {}
        }
    }
}
private struct IconPixel {
    let x: CGFloat, y: CGFloat, red: Double, green: Double, blue: Double
    var brightness: Double { (red + green + blue) / 3 }
    func matches(_ rgb: (Double, Double, Double), tolerance: Double = 0.08) -> Bool {
        abs(red - rgb.0) <= tolerance && abs(green - rgb.1) <= tolerance && abs(blue - rgb.2) <= tolerance
    }
}
/// A lamp color as `appearance` resolves it, in device RGB.
@MainActor private func lampRGB(_ color: LampColor, appearance: NSAppearance.Name) throws -> (Double, Double, Double) {
    var resolved: NSColor?
    try #require(NSAppearance(named: appearance)).performAsCurrentDrawingAppearance {
        resolved = Theme.nsColor(color).usingColorSpace(.deviceRGB)
    }
    let rgb = try #require(resolved)
    return (rgb.redComponent, rgb.greenComponent, rgb.blueComponent)
}
/// Draws `image` into a 2x bitmap the way the menu bar does, with `appearance`
/// current, and returns its mostly opaque pixels in image points (y up).
@MainActor private func statusIconPixels(_ image: NSImage, appearance: NSAppearance.Name) throws -> [IconPixel] {
    let scale = 2.0, size = image.size
    let rep = try #require(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * scale), pixelsHigh: Int(size.height * scale),
                                            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
    rep.size = size
    try #require(NSAppearance(named: appearance)).performAsCurrentDrawingAppearance {
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        image.draw(in: NSRect(origin: .zero, size: size))
        NSGraphicsContext.restoreGraphicsState()
    }
    var pixels: [IconPixel] = []
    for row in 0..<rep.pixelsHigh {
        for column in 0..<rep.pixelsWide {
            guard let color = rep.colorAt(x: column, y: row)?.usingColorSpace(.deviceRGB), color.alphaComponent > 0.6 else { continue }
            // Bitmap rows run top-down.
            pixels.append(IconPixel(x: (Double(column) + 0.5) / scale, y: size.height - (Double(row) + 0.5) / scale,
                                    red: color.redComponent, green: color.greenComponent, blue: color.blueComponent))
        }
    }
    return pixels
}
