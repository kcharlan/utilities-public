import { tool } from "@opencode-ai/plugin"
import path from "path"
import fs from "fs"
import { existsSync } from "fs"

export default tool({
  description:
    "Convert a document (PDF, DOCX, PPTX, HTML, XLSX) to canonical Markdown + JSON. " +
    "Fully local, no API calls. Returns the Markdown content inline plus output file paths.",
  args: {
    input_path: tool.schema
      .string()
      .describe("Absolute path to the input document"),
    output_dir: tool.schema
      .string()
      .describe("Directory where output files (.opencode.md, .opencode.json, .assets/) will be written"),
    extract_images: tool.schema
      .boolean()
      .optional()
      .default(false)
      .describe("Extract images (PDF page renders, DOCX embedded images)"),
    max_page_images: tool.schema
      .number()
      .optional()
      .default(50)
      .describe("Max PDF pages to render as images"),
    xlsx_max_cells: tool.schema
      .number()
      .optional()
      .default(2000000)
      .describe("Max cells to extract from XLSX"),
    strict: tool.schema
      .boolean()
      .optional()
      .default(false)
      .describe("Treat conversion warnings as errors (non-zero exit)"),
  },
  async execute(args, context) {
    // Resolve docpipe path using a few common locations.
    // Priority:
    // 1) utilities repo absolute path (this machine's install location)
    // 2) current worktree/docpipe/docpipe
    // 3) "docpipe" from PATH
    const preferredPath = "/Users/example/source/utilities/docpipe/docpipe"
    const worktreePath = path.resolve(context.worktree, "docpipe/docpipe")
    const docpipePath = existsSync(preferredPath)
      ? preferredPath
      : existsSync(worktreePath)
        ? worktreePath
        : "docpipe"

    const cmd = [
      docpipePath,
      "convert",
      "--input", args.input_path,
      "--out", args.output_dir,
      "--format", "md+json",
      "--xlsx-max-cells", String(args.xlsx_max_cells),
    ]

    if (args.extract_images) {
      cmd.push("--images", "--max-page-images", String(args.max_page_images))
    }
    if (args.strict) {
      cmd.push("--strict")
    }

    // Execute docpipe using Bun shell
    let result = ""
    try {
      result = await Bun.$`${cmd}`.text()
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      return [
        "## Conversion Failed",
        `- Tool command: \`${cmd.join(" ")}\``,
        `- Error: ${message}`,
        "",
        "Make sure docpipe is installed and executable:",
        "- `/Users/example/source/utilities/docpipe/docpipe`",
        "- or available on `PATH` as `docpipe`",
      ].join("\\n")
    }

    // Read the markdown output to return inline
    const baseName = path.basename(args.input_path).replace(/\.[^.]+$/, "")
    const mdPath = path.join(args.output_dir, `${baseName}.opencode.md`)
    const jsonPath = path.join(args.output_dir, `${baseName}.opencode.json`)
    const assetsDir = path.join(args.output_dir, `${baseName}.assets`)

    let markdownContent = ""
    try {
      markdownContent = fs.readFileSync(mdPath, "utf-8")
    } catch {
      // If markdown file doesn't exist, return just the conversion output
    }

    // Return inline markdown (truncated if very large) plus file paths
    const MAX_INLINE = 50000
    const truncated = markdownContent.length > MAX_INLINE
    const inlineMarkdown = truncated
      ? markdownContent.slice(0, MAX_INLINE) + "\n\n[... truncated, see full file]"
      : markdownContent

    return [
      `## Conversion Result`,
      `- **Markdown**: ${mdPath}`,
      `- **JSON**: ${jsonPath}`,
      `- **Assets**: ${fs.existsSync(assetsDir) ? assetsDir : "(none)"}`,
      ``,
      `## Content`,
      ``,
      inlineMarkdown,
      ``,
      result, // docpipe's summary output
    ].join("\n")
  },
})
