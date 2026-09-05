"use client";

import { useMemo } from "react";

const HTML_TAG = /<\/?[a-z][\s\S]*>/i;
const ALLOWED_TAGS = new Set(["p", "br", "code", "strong", "em", "ul", "ol", "li", "pre"]);

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function sanitizeHtml(html: string): string {
  if (typeof window === "undefined") {
    return escapeHtml(html);
  }

  const doc = new DOMParser().parseFromString(html, "text/html");
  const walk = (node: Node): string => {
    if (node.nodeType === Node.TEXT_NODE) {
      return escapeHtml(node.textContent ?? "");
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return "";

    const el = node as Element;
    const tag = el.tagName.toLowerCase();
    if (!ALLOWED_TAGS.has(tag)) {
      return Array.from(el.childNodes).map(walk).join("");
    }

    if (tag === "br") return "<br />";
    const inner = Array.from(el.childNodes).map(walk).join("");
    return `<${tag}>${inner}</${tag}>`;
  };

  return Array.from(doc.body.childNodes).map(walk).join("");
}

function markdownToHtml(text: string): string {
  const lines = text.split("\n");
  const html: string[] = [];
  let inList = false;

  const closeList = () => {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      continue;
    }

    if (trimmed.startsWith("## ")) {
      closeList();
      html.push(`<p><strong>${inlineMarkdown(trimmed.slice(3))}</strong></p>`);
      continue;
    }

    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(trimmed.slice(2))}</li>`);
      continue;
    }

    closeList();
    html.push(`<p>${inlineMarkdown(trimmed)}</p>`);
  }

  closeList();
  return html.join("");
}

function inlineMarkdown(text: string): string {
  let out = escapeHtml(text);
  out = out.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  return out;
}

function toRenderableHtml(text: string): string {
  if (HTML_TAG.test(text)) {
    return sanitizeHtml(text);
  }
  return markdownToHtml(text);
}

export function AgentText({ text }: { text: string }) {
  const html = useMemo(() => toRenderableHtml(text), [text]);

  return (
    <div
      className="agent-prose"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
