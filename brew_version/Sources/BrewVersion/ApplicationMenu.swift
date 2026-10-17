import AppKit

/// NSApplication.run does not install SwiftUI App's standard command menus.
@MainActor enum ApplicationMenu {
    static func install() { NSApp.mainMenu = make() }
    static func make() -> NSMenu {
        let root = NSMenu()
        let app = NSMenuItem(title: "Brew Version", action: nil, keyEquivalent: "")
        let appMenu = NSMenu(title: "Brew Version")
        appMenu.addItem(withTitle: "Quit Brew Version", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        app.submenu = appMenu
        root.addItem(app)
        let edit = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        edit.submenu = editMenu
        root.addItem(edit)
        return root
    }
}
