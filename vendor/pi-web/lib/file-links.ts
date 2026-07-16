function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function normalizeFilePathSlashes(filePath: string): string {
  if (/^[a-zA-Z]:[\\/]/.test(filePath) || filePath.startsWith("\\\\")) {
    return filePath.replace(/\\/g, "/");
  }
  return filePath;
}

function stripLineSuffix(filePath: string): string {
  return filePath.replace(/:\d+(?::\d+)?$/, "");
}

function normalizeLocalPath(filePath: string): string {
  const normalized = normalizeFilePathSlashes(filePath);
  const isWindowsDrive = /^[a-zA-Z]:\//.test(normalized);
  const isUnc = normalized.startsWith("//");
  const leadingSlash = normalized.startsWith("/") && !isWindowsDrive && !isUnc;
  const parts: string[] = [];

  for (const part of normalized.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (parts.length > 0 && parts[parts.length - 1] !== "..") {
        parts.pop();
      } else if (!leadingSlash && !isWindowsDrive && !isUnc) {
        parts.push(part);
      }
      continue;
    }
    parts.push(part);
  }

  const joined = parts.join("/");
  if (isWindowsDrive) return joined;
  if (isUnc) return `//${joined}`;
  return leadingSlash ? `/${joined}` : joined;
}

function isPathInside(candidate: string, root: string): boolean {
  const normalizedCandidate = normalizeLocalPath(candidate).replace(/\/+$/, "");
  const normalizedRoot = normalizeLocalPath(root).replace(/\/+$/, "");
  const useCaseInsensitive = /^[a-zA-Z]:\//.test(normalizedCandidate) || /^[a-zA-Z]:\//.test(normalizedRoot);
  const filePath = useCaseInsensitive ? normalizedCandidate.toLowerCase() : normalizedCandidate;
  const rootPath = useCaseInsensitive ? normalizedRoot.toLowerCase() : normalizedRoot;
  return filePath === rootPath || filePath.startsWith(`${rootPath}/`);
}

function looksLikeRelativeFileHref(href: string): boolean {
  if (href.startsWith("#") || href.startsWith("?")) return false;
  if (href.startsWith("./") || href.startsWith("../")) return true;
  if (href.includes("/")) return true;
  return /(^|\/)\.?[^/]+\.[^/.]+$/.test(href);
}

function fileUrlToPath(href: string): string | null {
  try {
    const url = new URL(href);
    if (url.protocol !== "file:") return null;
    const pathname = safeDecode(url.pathname);
    if (url.hostname) {
      return `//${url.hostname}${pathname.startsWith("/") ? pathname : `/${pathname}`}`;
    }
    if (/^\/[a-zA-Z]:\//.test(pathname)) return pathname.slice(1);
    return pathname;
  } catch {
    return null;
  }
}

export function resolveLocalFileHref(href: string | undefined, cwd?: string): string | null {
  if (!href) return null;

  const cleanHref = href.split("#", 1)[0].split("?", 1)[0].trim();
  if (!cleanHref) return null;

  let candidate: string | null = null;
  let candidateKind: "absolute" | "relative" | null = null;
  const decodedHref = safeDecode(cleanHref);
  const isBackslashUncPath = decodedHref.startsWith("\\\\");
  const normalizedHref = normalizeFilePathSlashes(decodedHref);
  const lowerHref = normalizedHref.toLowerCase();

  if (lowerHref.startsWith("/api/") || lowerHref.startsWith("/_next/")) return null;
  if (!isBackslashUncPath && normalizedHref.startsWith("//")) return null;
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/i.test(normalizedHref) && !lowerHref.startsWith("file:") && !/^[a-zA-Z]:\//.test(normalizedHref)) {
    return null;
  }

  if (lowerHref.startsWith("file:")) {
    candidate = fileUrlToPath(normalizedHref);
    candidateKind = candidate ? "absolute" : null;
  } else if (/^[a-zA-Z]:\//.test(normalizedHref)) {
    candidate = normalizedHref;
    candidateKind = "absolute";
  } else if (normalizedHref.startsWith("/")) {
    candidate = normalizedHref;
    candidateKind = "absolute";
  } else if (cwd && looksLikeRelativeFileHref(normalizedHref)) {
    candidate = `${normalizeFilePathSlashes(cwd).replace(/\/+$/, "")}/${normalizedHref}`;
    candidateKind = "relative";
  }

  if (!candidate) return null;

  const filePath = stripLineSuffix(normalizeLocalPath(candidate));
  if (candidateKind === "relative" && cwd && !isPathInside(filePath, cwd)) return null;
  return filePath;
}

// 判断一段行内代码文本是否"看起来像本地文件路径"，用于把 `reports/xx.md` 这类
// 行内代码渲染成可点击链接。刻意保守，避免把 `-65.04`、`2.4`、`gpt-5.5`、
// `link_budget` 这类数值/标识符误判成文件：
//   1) 不含空白、不以 http/协议开头；
//   2) 必须带扩展名（末段形如 name.ext，ext 为 1~8 位字母数字）；
//   3) 要么含路径分隔符（a/b.md、F:\x），要么末段是"多段点分 + 已知文本扩展名"
//      （单个裸文件名如 report.md 也允许，但纯数字如 9.11 不允许——靠扩展名字母兜底）。
const KNOWN_FILE_EXT = /\.(md|markdown|txt|csv|tsv|json|ya?ml|toml|ini|cfg|conf|log|py|pyi|ipynb|js|mjs|cjs|ts|tsx|jsx|sh|bash|c|h|cpp|cc|hpp|rs|go|java|rb|php|sql|html?|css|scss|xml|png|jpe?g|gif|webp|bmp|svg|avif|pdf|docx?|xlsx?|pptx?|zip|tar|gz|m|mat)$/i;

export function looksLikeFilePathText(text: string | undefined): boolean {
  if (!text) return false;
  const t = text.trim();
  if (!t || t.length > 260) return false;
  if (/\s/.test(t)) return false;                       // 路径不含空白
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(t)) return false; // http:// 等 URL 交给 <a> 处理
  if (t.startsWith("#") || t.startsWith("@")) return false;

  const hasSep = t.includes("/") || /^[a-zA-Z]:\\/.test(t) || t.includes("\\");
  const hasKnownExt = KNOWN_FILE_EXT.test(t);
  // 含分隔符 + 任意扩展名 → 视为路径；无分隔符（裸文件名）则必须是已知文本/常见扩展名，
  // 以排除 9.11 / 3.14 这类纯数字带点。
  if (hasSep) return /\.[a-z0-9]{1,8}$/i.test(t);
  return hasKnownExt;
}
