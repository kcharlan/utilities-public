import SwiftUI
import BrewVersionCore

struct SearchSection: View {
    let controller: WatchController
    let undo: WatchUndoAction
    @Bindable var input: SearchInput
    @FocusState private var searchFocused: Bool
    var focusGeneration = UUID()
    private var query: String { input.text }
    @State private var selection = 0
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            TextField("Search formulae or casks", text: $input.text)
                .accessibilityLabel("Search formulae or casks")
                .focused($searchFocused)
                .onAppear { searchFocused = true }
                .onChange(of: focusGeneration) { _, _ in searchFocused = true }
                .onChange(of: query) { _, _ in selection = 0 }
                .task(id: input.request) { await input.lookup(controller: controller) }
                .onSubmit { watchSelected() }
                .onKeyPress(.downArrow) { selection = min(selection + 1, max(0, controller.results.count - 1)); return .handled }
                .onKeyPress(.upArrow) { selection = max(0, selection - 1); return .handled }
            if !query.isEmpty {
                SearchResults(controller: controller, undo: undo, query: query, selection: $selection) { name, kind in
                    input.select(name: name, kind: kind)
                }
                Button("Copy selected version") { copySelected() }.keyboardShortcut("c", modifiers: .command).hidden().frame(height: 0)
            }
        }
    }
    private func watchSelected() {
        let selected = selection
        Task { await input.watchSelected(selected, undo: undo, controller: controller) }
    }
    private func copySelected() {
        guard controller.results.indices.contains(selection), case .found(let listing, _, _) = controller.results[selection] else { return }
        copyText(ReleaseID(listing).displayVersion)
    }
}

/// Keeps the input and popover footer outside the scrolling search content.
struct SearchResults: View {
    let controller: WatchController
    let undo: WatchUndoAction
    let query: String
    @Binding var selection: Int
    let selectSuggestion: (PackageName, PackageKind) -> Void
    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    if tokenize(query).count == 1, let catalog = controller.catalog {
                        ForEach(Array(catalog.suggestions(prefix: query.trimmingCharacters(in: .whitespacesAndNewlines)).enumerated()), id: \.offset) { _, item in
                            Button("\(item.name.rawValue) · \(item.kind.rawValue)") { selectSuggestion(item.name, item.kind) }.buttonStyle(.plain).font(.caption)
                        }
                    }
                    ForEach(Array(controller.results.enumerated()), id: \.offset) { index, result in
                        resultView(result).padding(8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(index == selection ? Color.accentColor.opacity(0.12) : Color.clear, in: RoundedRectangle(cornerRadius: 6))
                            .contentShape(Rectangle()).onTapGesture { selection = index }
                            .id(index)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }.frame(height: 300)
            .onChange(of: selection) { _, index in proxy.scrollTo(index) }
            .onChange(of: controller.results) { _, _ in proxy.scrollTo(selection) }
        }
    }
    @ViewBuilder private func resultView(_ result: LookupResult) -> some View {
        switch result {
        case .found(let listing, let installed, let watched):
            HStack {
                VStack(alignment: .leading) {
                    Text("\(listing.name.rawValue) · \(listing.kind.rawValue) · \(ReleaseID(listing).displayVersion)")
                    Text(statusText(listing, installed: installed)).font(.caption).foregroundStyle(.secondary)
                    if let note = installedSourceNote(installed) { Text(note).font(.caption).foregroundStyle(.secondary) }
                }
                Spacer()
                if watched { Text("Watching").font(.caption) }
                else { Button("Watch") { Task { await undo.watch(listing.name, kind: listing.kind, controller: controller) } }.disabled(!controller.canSave) }
            }
        case .invalid(let text):
            VStack(alignment: .leading) { Text(text); Text("Names use lowercase letters, numbers and @ + . _ -").font(.caption).foregroundStyle(.red) }
        case .notFound(let name):
            VStack(alignment: .leading) { Text(name.rawValue); Text("Not a Homebrew formula or cask. Check the spelling.").font(.caption).foregroundStyle(.secondary) }
        case .failed(let name, let error):
            VStack(alignment: .leading) { Text(name.rawValue); Text(error).font(.caption).foregroundStyle(.red) }
        }
    }
}
