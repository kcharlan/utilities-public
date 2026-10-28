import Foundation
import TelltaleCore

/// Reads RSS 2.0 `item` elements (title, link, pubDate) and notes whether the root was `rss`,
/// so an HTML page that happens to be well-formed XML isn't taken for an empty feed.
final class RSSReader: NSObject, XMLParserDelegate {
    private(set) var items: [RSSItem] = []
    private(set) var sawRSSRoot = false

    private var depth = 0
    private var inItem = false
    private var field: String?
    private var text = ""
    private var title: String?
    private var link: String?
    private var published: String?

    func parser(
        _ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?,
        qualifiedName: String?, attributes: [String: String]
    ) {
        depth += 1
        if depth == 1 { sawRSSRoot = elementName == "rss" }
        if elementName == "item" {
            inItem = true
            title = nil
            link = nil
            published = nil
        } else if inItem, ["title", "link", "pubDate"].contains(elementName) {
            field = elementName
            text = ""
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        if field != nil { text += string }
    }

    func parser(_ parser: XMLParser, foundCDATA CDATABlock: Data) {
        if field != nil { text += String(decoding: CDATABlock, as: UTF8.self) }
    }

    func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName: String?) {
        depth -= 1
        if elementName == "item" {
            inItem = false
            if let title, let link, let url = URL(string: link), let published, let date = Self.rfc822(published) {
                items.append(RSSItem(title: title, link: url, publishedAt: date))
            }
        } else if field == elementName {
            let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
            switch elementName {
            case "title": title = value.isEmpty ? nil : value
            case "link": link = value.isEmpty ? nil : value
            default: published = value.isEmpty ? nil : value
            }
            field = nil
        }
    }

    /// RFC 822 dates as RSS writes them, with a zone name or a numeric offset, seconds optional.
    static func rfc822(_ string: String) -> Date? {
        for format in ["EEE, dd MMM yyyy HH:mm:ss zzz", "EEE, dd MMM yyyy HH:mm zzz", "dd MMM yyyy HH:mm:ss zzz"] {
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.dateFormat = format
            if let date = formatter.date(from: string) { return date }
        }
        return nil
    }
}
