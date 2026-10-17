import SwiftUI
import BrewVersionCore

struct SearchSection: View {
    let controller: WatchController
    @Binding var query: String
    @State private var selection = 0
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            TextField("Search formulae or casks", text: $query)
                .accessibilityLabel("Search formulae or casks")
                .onChange(of: query) { _, _ in selection = 0 }
                .task(id: query) {
                    if query.isEmpty { controller.clearSearch() }
                    else { await controller.search(query) }
                }
                .onSubmit { watchSelected() }
                .onKeyPress(.downArrow) { selection = min(selection + 1, max(0, controller.results.count - 1)); return .handled }
                .onKeyPress(.upArrow) { selection = max(0, selection - 1); return .handled }
            if !query.isEmpty {
                if tokenize(query).count == 1, let catalog = controller.catalog {
                    ForEach(Array(catalog.suggestions(prefix: query.trimmingCharacters(in: .whitespacesAndNewlines)).enumerated()), id: \.offset) { _, item in
                        Button("\(item.name.rawValue) · \(item.kind.rawValue)") { query = item.name.rawValue }.buttonStyle(.plain).font(.caption)
                    }
                }
                ForEach(Array(controller.results.enumerated()), id: \.offset) { index, result in
                    resultView(result).padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(index == selection ? Color.accentColor.opacity(0.12) : Color.clear, in: RoundedRectangle(cornerRadius: 6))
                        .contentShape(Rectangle()).onTapGesture { selection = index }
                }
                Button("Copy selected version") { copySelected() }.keyboardShortcut("c", modifiers: .command).hidden().frame(height: 0)
            }
        }
    }
    @ViewBuilder private func resultView(_ result: LookupResult) -> some View {
        switch result {
        case .found(let listing, let installed, let watched):
            HStack {
                VStack(alignment: .leading) {
                    Text("\(listing.name.rawValue) · \(listing.kind.rawValue) · \(ReleaseID(listing).displayVersion)")
                    Text(statusText(listing, installed: installed)).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if watched { Text("Watching").font(.caption) }
                else { Button("Watch") { Task { await controller.add(listing.name, kind: listing.kind) } }.disabled(!controller.canSave) }
            }
        case .invalid(let text):
            VStack(alignment: .leading) { Text(text); Text("Names use lowercase letters, numbers and @ + . _ -").font(.caption).foregroundStyle(.red) }
        case .notFound(let name):
            VStack(alignment: .leading) { Text(name.rawValue); Text("Not a Homebrew formula or cask. Check the spelling.").font(.caption).foregroundStyle(.secondary) }
        case .failed(let name, let error):
            VStack(alignment: .leading) { Text(name.rawValue); Text(error).font(.caption).foregroundStyle(.red) }
        }
    }
    private func watchSelected() {
        guard controller.canSave, controller.results.indices.contains(selection),
              case .found(let listing, _, false) = controller.results[selection] else { return }
        Task { await controller.add(listing.name, kind: listing.kind) }
    }
    private func copySelected() {
        guard controller.results.indices.contains(selection), case .found(let listing, _, _) = controller.results[selection] else { return }
        copyText(ReleaseID(listing).displayVersion)
    }
}
