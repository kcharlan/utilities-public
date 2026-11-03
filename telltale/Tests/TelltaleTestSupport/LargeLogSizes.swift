/// Sizes for the large-log regressions. Each is larger than the reader cap it replaced (16 MiB
/// plain line, 4 MiB compressed line, 64 MiB decompressed file, 128 MiB zstd window; removed in
/// #227) and at least 15% larger than the longest line and largest file in real local Codex and
/// Claude Code logs measured on 2026-11-03. Raise them if real logs outgrow that margin; never
/// lower them to fit a new cap.
public enum LargeLogSizes {
    public static let line = 20 * 1024 * 1024
    public static let file = 160 * 1024 * 1024
}
