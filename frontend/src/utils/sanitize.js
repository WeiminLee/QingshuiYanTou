import DOMPurify from "dompurify";

/**
 * Sanitize HTML string for safe v-html rendering.
 * Uses DOMPurify defaults which strip <script>, <iframe>, event handlers, javascript: URLs.
 */
export function sanitize(html) {
  if (!html) return "";
  if (typeof html !== "string") return "";
  return DOMPurify.sanitize(html);
}
