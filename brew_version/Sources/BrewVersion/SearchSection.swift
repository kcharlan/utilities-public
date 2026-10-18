import SwiftUI
import BrewVersionCore

enum SearchChoice: Equatable {
    case suggestion(PackageName, PackageKind)
    case result(Int)
}
@MainActor func catalogPrefixChoices(controller: WatchController, query: String) -> [(name: PackageName, kind: PackageKind)] {
    guard tokenize(query).count == 1 else { return [] }
    return controller.suggestions(prefix: query.trimmingCharacters(in: .whitespacesAndNewlines)).map { ($0.name, $0.kind) }
}
func searchChoice(selection: Int, suggestions: [(name: PackageName, kind: PackageKind)], resultIndices: [Int]? = nil) -> SearchChoice {
    if suggestions.indices.contains(selection) { return .suggestion(suggestions[selection].name, suggestions[selection].kind) }
    let offset = max(0, selection - suggestions.count)
    return .result(resultIndices.flatMap { $0.indices.contains(offset) ? $0[offset] : nil } ?? offset)
}
func visibleSearchResultIndices(_ results: [LookupResult], query: String, hasSuggestions: Bool) -> [Int] {
    results.indices.filter { index in
        guard hasSuggestions, tokenize(query).count == 1, case .notFound(let name) = results[index] else { return true }
        return name.rawValue != query.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
func searchSelectionForRequest(_ request: SearchInput.Request, suggestions: [(name: PackageName, kind: PackageKind)]) -> Int {
    suggestions.firstIndex { $0.name.rawValue == request.text && $0.kind == request.kind } ?? 0
}

struct SearchSection: View {
    let controller: WatchController
    let undo: WatchUndoAction
    @Bindable var input: SearchInput
    @FocusState private var searchFocused: Bool
    var focusGeneration = UUID()
    var maximumHeight: CGFloat = 380
    private var query: String { input.text }
    @State private var selection = 0
    private var suggestions: [(name: PackageName, kind: PackageKind)] { catalogPrefixChoices(controller: controller, query: query) }
    private var resultIndices: [Int] { visibleSearchResultIndices(controller.results, query: query, hasSuggestions: !suggestions.isEmpty) }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary).accessibilityHidden(true)
                TextField("Add a formula or cask", text: $input.text).textFieldStyle(.plain)
                    .accessibilityLabel("Search formulae or casks")
                    .focused($searchFocused)
                    .onAppear { searchFocused = true }
                    .onChange(of: focusGeneration) { _, _ in searchFocused = true }
                    .onChange(of: input.request) { _, request in selection = searchSelectionForRequest(request, suggestions: suggestions) }
                    .task(id: input.request) { await input.lookup(controller: controller) }
                    .onSubmit { watchSelected() }
                    .onKeyPress(.downArrow) { selection = min(selection + 1, max(0, suggestions.count + resultIndices.count - 1)); return .handled }
                    .onKeyPress(.upArrow) { selection = max(0, selection - 1); return .handled }
                if !query.isEmpty {
                    Button { input.text = ""; searchFocused = true } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary) }
                        .buttonStyle(.plain).help("Clear search").accessibilityLabel("Clear search")
                }
            }.padding(.horizontal, 8).frame(height: 28).background(.quaternary, in: RoundedRectangle(cornerRadius: 7))
            if !query.isEmpty {
                SearchResults(controller: controller, undo: undo, query: query, selection: $selection, maximumHeight: maximumHeight) { name, kind in
                    input.select(name: name, kind: kind)
                }
                Button("Copy selected version") { copySelected() }.keyboardShortcut("c", modifiers: .command).hidden().frame(height: 0)
            }
        }
    }
    private func watchSelected() {
        let choice = searchChoice(selection: selection, suggestions: suggestions, resultIndices: resultIndices)
        Task { await input.watchChoice(choice, undo: undo, controller: controller) }
    }
    private func copySelected() {
        let choice = searchChoice(selection: selection, suggestions: suggestions, resultIndices: resultIndices)
        Task {
            if let version = await input.version(for: choice, controller: controller) { copyText(version) }
        }
    }
}

struct SearchResults: View {
    let controller: WatchController
    let undo: WatchUndoAction
    let query: String
    @Binding var selection: Int
    var maximumHeight: CGFloat = 380
    let selectSuggestion: (PackageName, PackageKind) -> Void
    private var suggestions: [(name: PackageName, kind: PackageKind)] { catalogPrefixChoices(controller: controller, query: query) }
    private var resultIndices: [Int] { visibleSearchResultIndices(controller.results, query: query, hasSuggestions: !suggestions.isEmpty) }
    var body: some View {
        ScrollViewReader { proxy in
            ContentSizedScroll(maximum: maximumHeight, initial: min(maximumHeight, CGFloat(controller.results.count * 48 + 60))) {
                VStack(alignment: .leading, spacing: 2) {
                    if !suggestions.isEmpty {
                        ForEach(Array(suggestions.enumerated()), id: \.offset) { index, item in
                            Button { selectSuggestion(item.name, item.kind) } label: {
                                PackageRow(name: item.name, kind: item.kind, compact: true,
                                           suggestionInstalled: controller.installedNames[item.kind]?.contains(item.name) == true, selected: index == selection)
                            }.buttonStyle(.plain).accessibilityLabel("\(item.name.rawValue), \(item.kind.rawValue) suggestion").id(index)
                        }
                    }
                    ForEach(Array(resultIndices.enumerated()), id: \.offset) { index, resultIndex in
                        resultView(controller.results[resultIndex], selected: index + suggestions.count == selection)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle()).onTapGesture { selection = index + suggestions.count }.id(index + suggestions.count)
                    }
                }
            }
            .onChange(of: selection) { _, index in proxy.scrollTo(index) }
            .onChange(of: controller.results) { _, _ in proxy.scrollTo(selection) }
        }
    }
    @ViewBuilder private func resultView(_ result: LookupResult, selected: Bool) -> some View {
        switch result {
        case .found(let listing, let installed, let watched):
            PackageRow(name: listing.name, kind: listing.kind, listing: listing, installed: installed,
                       amber: isUpdate(listing, installed: installed), selected: selected, watched: watched,
                       canSave: controller.canSave,
                       watch: { Task { await undo.watch(listing.name, kind: listing.kind, controller: controller) } })
        case .invalid(let text):
            Label { VStack(alignment: .leading) { Text(text); Text("Names use lowercase letters, numbers and @ + . _ -").font(.system(size: 11)).foregroundStyle(.red) } } icon: { Image(systemName: "exclamationmark.triangle") }.padding(8)
        case .notFound(let name):
            PackageRow(name: name, kind: nil, error: "Not a Homebrew formula or cask. Check the spelling.", selected: selected)
        case .failed(let name, let error):
            PackageRow(name: name, kind: nil, error: error, selected: selected)
        }
    }
    private func isUpdate(_ listing: Listing, installed: InstalledVersion?) -> Bool {
        if case .updateAvailable = updateStatus(listing: listing, installed: installed) { return true }
        return false
    }
}
