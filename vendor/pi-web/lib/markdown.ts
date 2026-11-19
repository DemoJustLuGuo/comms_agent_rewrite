import type { Options as ReactMarkdownOptions } from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

const markdownSanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code: [["className", /^language-./, "math-inline", "math-display"]],
    // img 默认放行（tagNames 与 src 属性都在 defaultSchema 内），但 protocols.src 只认
    // http(s)——plot 输出的站内路径 /api/files/… 会被剥掉，聊天区因此永远不显示图。
    // 这里把 src 收紧为「站内相对路径」：/ 开头且非 //（协议相对），http(s) 外链与
    // javascript: 一律拒绝——比默认 schema 更收紧，只影响站内图片内联。
    img: [
      "alt",
      "title",
      "height",
      "width",
      ["src", /^\/[^/]/],
    ],
  },
  strip: [...(defaultSchema.strip || []), "iframe", "object", "style", "form"],
};

export const markdownRemarkPlugins: ReactMarkdownOptions["remarkPlugins"] = [remarkGfm, remarkMath];
export const markdownPreviewRemarkPlugins: ReactMarkdownOptions["remarkPlugins"] = [remarkGfm];

export const markdownRehypePlugins: ReactMarkdownOptions["rehypePlugins"] = [
  rehypeRaw,
  [rehypeSanitize, markdownSanitizeSchema],
  [rehypeKatex, { throwOnError: false, strict: false }],
];

export const markdownPreviewRehypePlugins: ReactMarkdownOptions["rehypePlugins"] = [
  rehypeRaw,
  [rehypeSanitize, markdownSanitizeSchema],
];
