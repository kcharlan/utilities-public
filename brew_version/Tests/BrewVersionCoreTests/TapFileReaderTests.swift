import Foundation
import Testing
@testable import BrewVersionCore

struct TapFileReaderTests {
    private let name = PackageName("synthetic-owner/synthetic-tap/synthetic-tool")!

    private func read(_ text: String, kind: PackageKind = .formula, arm64: Bool = true) -> Listing? {
        TapFileReader.listing(from: text, name: name, kind: kind, arm64: arm64)
    }

    @Test func explicitFormulaVersionAndRevision() {
        let result = read("version \"4.5.6\"\nrevision 2")
        #expect(result?.version == "4.5.6")
        #expect(result?.revision == 2)
        #expect(result?.name == name)
    }

    @Test func versionFromURL() {
        #expect(read("url \"https://github.com/synthetic-owner/synthetic-tool/releases/download/v9.0.1/synthetic-tool-9.0.1.tgz\"")?.version == "9.0.1")
    }

    @Test func interpolatedURLUsesExplicitVersion() {
        #expect(read(##"version "7.8""## + "\n" + ##"url "https://example.invalid/v#{version}/synthetic-tool-#{version}.zip""##)?.version == "7.8")
    }

    @Test func nestedBlocksDoNotLeakVersions() {
        let text = """
        resource "synthetic-resource" do
          url "https://example.invalid/synthetic-resource-1.2.3.tgz"
          stable do
            version "1.2.3"
          end
        end
        head do
          version "2.3.4"
        end
        bottle do
          version "3.4.5"
        end
        livecheck do
          version "4.5.0"
        end
        url "https://example.invalid/synthetic-tool-9.0.1.tgz"
        """
        #expect(read(text)?.version == "9.0.1")
    }

    @Test func conditionalArchBranches() {
        for arm in [true, false] {
            for predicate in ["arm?", "intel?"] {
                let matches = arm == (predicate == "arm?")
                let first = "if Hardware::CPU.\(predicate)\nversion \"4.5.6\"\n"
                #expect(read(first + "end", arm64: arm)?.version == (matches ? "4.5.6" : nil))
                #expect(read(first + "else\nversion \"7.8\"\nend", arm64: arm)?.version == (matches ? "4.5.6" : "7.8"))
            }
        }
        #expect(read("url \"https://example.invalid/synthetic-tool-4.5.6.tgz\" if OS.mac?\nrevision 2")?.revision == 2)
        #expect(read("if unknown?\nversion \"1.2.3\"\nelsif Hardware::CPU.arm?\nversion \"2.3.4\"\nelse\nversion \"3.4.5\"\nend\nversion \"7.8\"")?.version == "7.8")
        #expect(read("if Hardware::CPU.intel?\nversion \"4.5.6\"\nelsif Hardware::CPU.arm?\nversion \"7.8\"\nend")?.version == "7.8")
    }

    @Test func stableAndArchBlocks() {
        #expect(read("stable do\nversion '4.5.6'\nend")?.version == "4.5.6")
        let text = "on_macos do\non_arm do\nversion \"4.5.6\"\nend\non_intel do\nversion \"7.8\"\nend\nend"
        #expect(read(text, arm64: true)?.version == "4.5.6")
        #expect(read(text, arm64: false)?.version == "7.8")
    }

    @Test func multiLineGitURL() {
        let result = read("""
        url "https://github.com/synthetic-owner/synthetic-tool.git",
          tag: "v4.5.6",
          revision: "0123abcd"
        """)
        #expect(result?.version == "4.5.6")
        #expect(result?.revision == 0)
        #expect(read("url(\n\"https://example.invalid/synthetic-tool-7.8.zip\"\n)")?.version == "7.8")
        #expect(read("url \\\n\"https://example.invalid/synthetic-tool-7.8.zip\"")?.version == "7.8")
    }

    @Test func dynamicVersionsAreUnreadable() {
        for text in [##"version "#{x}""##, ##"version ENV["V"]"##, ##"version "1.#{y}""##,
                     ##"url "https://example.invalid/synthetic-tool-#{something_else}.zip""##, "desc 'Synthetic'",
                     ##"version "4.5.6".split(".").first"##] {
            #expect(read(text) == nil, "Unexpected listing for \(text)")
        }
    }

    @Test func dynamicExplicitVersionNeverFallsBack() {
        for version in [##""#{x}""##, ##"ENV["V"]"##, ##""1.#{y}""##, ##""4.5.6".freeze"##, "some_method"] {
            #expect(read("version \(version)\nurl \"https://example.invalid/synthetic-tool-9.0.1.zip\"") == nil)
        }
    }

    @Test func caskFields() {
        let result = read("""
        version "4.5.6"
        auto_updates true
        desc "Synthetic app"
        homepage "https://example.invalid/synthetic-app"
        app "Synthetic.app", target: "Synthetic Folder/Renamed.app"
        app 'Second.app'
        """, kind: .cask)
        #expect(result?.version == "4.5.6")
        #expect(result?.autoUpdates == true)
        #expect(result?.summary == "Synthetic app")
        #expect(result?.homepage?.absoluteString == "https://example.invalid/synthetic-app")
        #expect(result?.appNames == ["Renamed.app", "Second.app"])
    }

    @Test func completePackageWrappers() {
        let formula = """
        version "1.2.3"
        class SyntheticTool < Formula
          desc "Synthetic formula"
          def install
            version "2.3.4"
          end
          unless OS.mac?
            version "3.4.5"
          end
          case something
          when :other
            version "5.6.7"
          else
            version "6.7.8"
          end
          stable do
            version "4.5.6"
          end
        end
        revision 9
        """
        #expect(read(formula)?.version == "4.5.6")
        #expect(read(formula)?.revision == 0)
        #expect(read(formula)?.summary == "Synthetic formula")
        let cask = """
        version "1.2.3"
        cask "synthetic-app" do
          livecheck do
            version "2.3.4"
          end
          version "7.8"
          app "Synthetic.app"
        end
        app "Outside.app"
        """
        #expect(read(cask, kind: .cask)?.version == "7.8")
        #expect(read(cask, kind: .cask)?.appNames == ["Synthetic.app"])
        #expect(read("class SyntheticTool < Formula\nend\nversion '4.5.6'") == nil)
    }

    @Test func caskLatest() {
        #expect(read("version :latest", kind: .cask)?.version == "latest")
        #expect(read("version :latest") == nil)
    }

    @Test func commentsIgnored() {
        #expect(read("## version '1.2.3'\nversion '4.5.6' # synthetic comment")?.version == "4.5.6")
        #expect(read("version '4.5.6'\ndesc 'Synthetic # string' # comment")?.summary == "Synthetic # string")
    }

    @Test func firstStatementsWinEvenWhenUnreadable() {
        let text = """
        version "4.5.6"
        version "7.8"
        revision 2
        revision 9
        desc "First synthetic description"
        desc "Second synthetic description"
        homepage "https://example.invalid/first"
        homepage "https://example.invalid/second"
        auto_updates false
        auto_updates true
        """
        let result = read(text, kind: .cask)
        #expect(result?.version == "4.5.6")
        #expect(result?.revision == 2)
        #expect(result?.summary == "First synthetic description")
        #expect(result?.homepage?.absoluteString == "https://example.invalid/first")
        #expect(result?.autoUpdates == false)
        #expect(read("url dynamic_url\nurl 'https://example.invalid/synthetic-tool-4.5.6.zip'") == nil)
        #expect(read("version ENV['V']\nversion '4.5.6'") == nil)
    }
}
